# -*- coding: utf-8 -*-
"""
    proxy.py
    ~~~~~~~~
    ⚡⚡⚡ Fast, Lightweight, Pluggable, TLS interception capable proxy server focused on
    Network monitoring, controls & Application development, testing, debugging.

    :copyright: (c) 2013-present by Abhinav Singh and contributors.
    :license: BSD, see LICENSE for more details.
"""
import logging
import multiprocessing
from typing import Optional, Any

from .store.base import CacheStore
from ...http.parser import HttpParser, httpParserTypes
from ...http.proxy import HttpProxyBasePlugin
from ...http.codes import httpStatusCodes
from ...http.methods import httpMethods
from ...common.constants import PROXY_AGENT_HEADER_VALUE
from ...common.utils import text_
from ...common.utils import build_http_response

logger = logging.getLogger(__name__)


class BaseCacheResponsesPlugin(HttpProxyBasePlugin):
    """Base cache plugin.

    It requires a storage backend to work with. Storage class
    must implement CacheStore interface.

    Different storage backends can be used per request if required.
    """

    class EnabledDescriptor:
        def __init__(self, enabled: bool = False) -> None:
            self.enabled = multiprocessing.Event()
            if enabled:
                self.enabled.set()

        def __get__(self, obj: Optional[object], owner: type) -> Any:
            if obj is None:
                return self.enabled
            return None

    # Dynamically enable / disable cache
    enabled = EnabledDescriptor(True)
    local = EnabledDescriptor(False)  # TODO configure using flags

    def __init__(
            self,
            *args: Any,
            **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.store: Optional[CacheStore] = None
        self.__local: Optional[bool] = None
        self.__enabled: Optional[bool] = None

    def set_store(self, store: CacheStore) -> None:
        self.store = store

    def before_upstream_connection(
            self, request: HttpParser) -> Optional[HttpParser]:
        self.__enabled = self.__class__.enabled.is_set()
        self.__local = self.__class__.local.is_set()
        if not self.__enabled:
            return request

        assert self.store
        logger.info("Upstream connexion %s:%d %s" %
                    (text_(request.host), request.port if request.port else 0, text_(request.path)))

        if (request.method == httpMethods.CONNECT):
            return request if not self.__local else None

        try:
            if self.store.is_cached(request):
                return None
        except Exception as e:
            logger.info('Caching disabled due to exception message: %s', str(e))

        return request

    def handle_client_request(
            self, request: HttpParser) -> Optional[HttpParser]:
        assert self.__enabled is not None
        assert self.__local is not None
        if not self.__enabled:
            return request

        assert self.store
        logger.info("Client request %s:%d %s" %
                    (text_(request.host), request.port if request.port else 0, text_(request.path)))

        if (request.method == httpMethods.CONNECT):
            return request

        try:
            msg = self.store.cache_request(request)
            if (msg.type == httpParserTypes.REQUEST_PARSER):
                if self.__local:
                    self.client.queue(memoryview(build_http_response(
                        httpStatusCodes.BAD_GATEWAY,
                        reason=b'Bad gateway',
                        headers={
                            b'Server': PROXY_AGENT_HEADER_VALUE,
                            b'Connection': b'close',
                        },
                        body=b'Ressource has not been cached yet. Please allow upstream.'
                    )))
                    return None
                return msg
            elif (msg.type == httpParserTypes.RESPONSE_PARSER):
                self.client.queue(memoryview(build_http_response(
                    int(msg.code) if msg.code is not None else 0,
                    reason=msg.reason,
                    headers={k: v for k, v in msg.headers.values()},
                    body=msg.body
                )))
                return None
            else:
                raise ValueError('Bad HTTPParser type: %s' % msg.type)
        except Exception as e:
            logger.info('Caching disabled due to exception message: %s', str(e))

        try:
            if self.store.is_cached(request):
                self.client.queue(memoryview(build_http_response(
                    httpStatusCodes.INTERNAL_SERVER_ERROR,
                    reason=b'Internal server error',
                    headers={
                        b'Server': PROXY_AGENT_HEADER_VALUE,
                        b'Connection': b'close',
                    }
                )))
        except Exception as e:
            logger.info('Caching disabled due to exception message: %s', str(e))

        return request

    def handle_upstream_chunk(self, chunk: memoryview) -> memoryview:
        assert self.__enabled is not None
        assert self.__local is not None
        if not self.__enabled:
            return chunk

        assert self.store
        return self.store.cache_response_chunk(chunk)

    def on_upstream_connection_close(self) -> None:
        assert self.__enabled is not None
        assert self.__local is not None
        if not self.__enabled:
            return

        assert self.store
        self.store.close()
