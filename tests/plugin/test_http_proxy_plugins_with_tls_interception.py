# -*- coding: utf-8 -*-
"""
    proxy.py
    ~~~~~~~~
    ⚡⚡⚡ Fast, Lightweight, Pluggable, TLS interception capable proxy server focused on
    Network monitoring, controls & Application development, testing, debugging.

    :copyright: (c) 2013-present by Abhinav Singh and contributors.
    :license: BSD, see LICENSE for more details.
"""
import unittest
import socket
import selectors
import ssl
import os
import tempfile
from pathlib import Path

from unittest import mock
from typing import Any, cast

from proxy.common.constants import PROXY_AGENT_HEADER_VALUE
from proxy.common.utils import bytes_
from proxy.common.flags import Flags
from proxy.common.utils import build_http_request, build_http_response
from proxy.core.connection import TcpClientConnection, TcpServerConnection
from proxy.http.codes import httpStatusCodes
from proxy.http.methods import httpMethods
from proxy.http.handler import HttpProtocolHandler
from proxy.http.proxy import HttpProxyPlugin

from .utils import get_plugin_by_test_name
from .utils import with_and_without_upstream, without_upstream


class TestHttpProxyPluginExamplesWithTlsInterception(unittest.TestCase):

    def __init__(self, *args: Any, **kwArgs: Any) -> None:
        super().__init__(*args, **kwArgs)
        self.connect_upstream = True

    @mock.patch('selectors.DefaultSelector')
    @mock.patch('socket.fromfd')
    def setUp(self,
              mock_fromfd: mock.Mock,
              mock_selector: mock.Mock) -> None:
        self.mock_fromfd = mock_fromfd
        self.mock_selector = mock_selector

        self.fileno = 10
        self._addr = ('127.0.0.1', 54382)
        self.flags = Flags(
            ca_cert_file='ca-cert.pem',
            ca_key_file='ca-key.pem',
            ca_signing_key_file='ca-signing-key.pem',)
        self.plugin = mock.MagicMock()

        plugin = get_plugin_by_test_name(self._testMethodName)

        self.flags.plugins = {
            b'HttpProtocolHandlerPlugin': [HttpProxyPlugin],
            b'HttpProxyBasePlugin': [plugin],
        }
        self._conn = mock.MagicMock(spec=socket.socket)
        mock_fromfd.return_value = self._conn
        self.protocol_handler = HttpProtocolHandler(
            TcpClientConnection(self._conn, self._addr), flags=self.flags)
        self.protocol_handler.initialize()

    @mock.patch('ssl.wrap_socket')
    @mock.patch('ssl.create_default_context')
    @mock.patch('proxy.http.proxy.server.gen_public_key')
    @mock.patch('proxy.http.proxy.server.gen_csr')
    @mock.patch('proxy.http.proxy.server.sign_csr')
    @mock.patch('proxy.http.proxy.server.TcpServerConnection')
    def connect(self,
                mock_server_conn: mock.Mock,
                mock_sign_csr: mock.Mock,
                mock_gen_csr: mock.Mock,
                mock_gen_public_key: mock.Mock,
                mock_ssl_context: mock.Mock,
                mock_ssl_wrap: mock.Mock) -> None:
        self.mock_server_conn = mock_server_conn
        self.mock_ssl_context = mock_ssl_context
        self.mock_ssl_wrap = mock_ssl_wrap

        mock_sign_csr.return_value = True
        mock_gen_csr.return_value = True
        mock_gen_public_key.return_value = True

        self.server_ssl_connection = mock.MagicMock(spec=ssl.SSLSocket)
        self.mock_ssl_context.return_value.wrap_socket.return_value = self.server_ssl_connection
        self.client_ssl_connection = mock.MagicMock(spec=ssl.SSLSocket)
        self.mock_ssl_wrap.return_value = self.client_ssl_connection

        self.server = self.mock_server_conn.return_value
        self.server.addr = ('uni.corn', 433)

        def has_buffer() -> bool:
            return cast(bool, self.server.queue.called)

        def closed() -> bool:
            return not self.server.connect.called

        def mock_connection() -> Any:
            if self.mock_ssl_context.return_value.wrap_socket.called:
                return self.server_ssl_connection
            return self._conn

        # Do not mock the original wrap method
        self.server.wrap.side_effect = \
            lambda x, y: TcpServerConnection.wrap(self.server, x, y)

        self.server.has_buffer.side_effect = has_buffer
        type(self.server).closed = mock.PropertyMock(side_effect=closed)
        type(
            self.server).connection = mock.PropertyMock(
            side_effect=mock_connection)

        self.mock_selector.return_value.select.side_effect = [
            [(selectors.SelectorKey(
                fileobj=self._conn,
                fd=self._conn.fileno,
                events=selectors.EVENT_READ,
                data=None), selectors.EVENT_READ)],
            [(selectors.SelectorKey(
                fileobj=self.client_ssl_connection,
                fd=self.client_ssl_connection.fileno,
                events=selectors.EVENT_READ,
                data=None), selectors.EVENT_READ)],
            [(selectors.SelectorKey(
                fileobj=self.server_ssl_connection,
                fd=self.server_ssl_connection.fileno,
                events=selectors.EVENT_WRITE,
                data=None), selectors.EVENT_WRITE)],
            [(selectors.SelectorKey(
                fileobj=self.server_ssl_connection,
                fd=self.server_ssl_connection.fileno,
                events=selectors.EVENT_READ,
                data=None), selectors.EVENT_READ)],
            [(selectors.SelectorKey(
                fileobj=self.client_ssl_connection,
                fd=self.client_ssl_connection.fileno,
                events=selectors.EVENT_WRITE,
                data=None), selectors.EVENT_WRITE)],
            [(selectors.SelectorKey(
                fileobj=self.server_ssl_connection,
                fd=self.server_ssl_connection.fileno,
                events=selectors.EVENT_READ,
                data=None), selectors.EVENT_READ)],
        ]

        def send(raw: bytes) -> int:
            return len(raw)

        self._conn.send.side_effect = send
        self._conn.recv.return_value = build_http_request(
            httpMethods.CONNECT, b'uni.corn:443'
        )
        self.protocol_handler.run_once()

        self.assertEqual(mock_sign_csr.call_count, 1)
        self.assertEqual(mock_gen_csr.call_count, 1)
        self.assertEqual(mock_gen_public_key.call_count, 1)

        if self.connect_upstream:
            self.mock_server_conn.assert_called_once_with('uni.corn', 443)
            self.server.connect.assert_called()
            self.assertEqual(self.server.connection, self.server_ssl_connection)
        else:
            self.mock_server_conn.assert_not_called()

        self.assertEqual(
            self.protocol_handler.client.connection,
            self.client_ssl_connection)
        self._conn.send.assert_called_with(
            HttpProxyPlugin.PROXY_TUNNEL_ESTABLISHED_RESPONSE_PKT
        )
        self.assertFalse(self.protocol_handler.client.has_buffer())

    def tearDown(self) -> None:
        tmpDir = Path(tempfile.gettempdir())
        for f in tmpDir.glob('proxy-cache-*'):
            if f.is_file():
                os.remove(f)
        if tmpDir.joinpath('list.txt').is_file():
            os.remove(tmpDir / 'list.txt')

    def test_modify_post_data_plugin(self) -> None:
        self.connect()

        original = b'{"key": "value"}'
        modified = b'{"key": "modified"}'
        self.client_ssl_connection.recv.return_value = build_http_request(
            b'POST', b'/',
            headers={
                b'Host': b'uni.corn',
                b'Content-Type': b'application/x-www-form-urlencoded',
                b'Content-Length': bytes_(len(original)),
            },
            body=original
        )
        self.protocol_handler.run_once()
        self.server.queue.assert_called_with(
            build_http_request(
                b'POST', b'/',
                headers={
                    b'Host': b'uni.corn',
                    b'Content-Length': bytes_(len(modified)),
                    b'Content-Type': b'application/json',
                },
                body=modified
            )
        )

    def test_man_in_the_middle_plugin(self) -> None:
        self.connect()

        request = build_http_request(
            b'GET', b'/',
            headers={
                b'Host': b'uni.corn',
            }
        )
        self.client_ssl_connection.recv.return_value = request

        # Client read
        self.protocol_handler.run_once()
        self.server.queue.assert_called_once_with(request)

        # Server write
        self.protocol_handler.run_once()
        self.server.flush.assert_called_once()

        # Server read
        self.server.recv.return_value = \
            build_http_response(
                httpStatusCodes.OK,
                reason=b'OK', body=b'Original Response From Upstream')
        self.protocol_handler.run_once()
        self.assertEqual(
            self.protocol_handler.client.buffer[0].tobytes(),
            build_http_response(
                httpStatusCodes.OK,
                reason=b'OK', body=b'Hello from man in the middle')
        )

    def test_cache_responses_plugin_cache(self) -> None:
        self.connect()

        request = build_http_request(
            b'GET', b'/get',
            headers={
                b'Host': b'uni.corn',
            }
        )
        server_response = build_http_response(
            httpStatusCodes.OK,
            reason=b'OK',
            body=b'Original Response From Upstream'
        )

        # Client read:
        self.client_ssl_connection.recv.return_value = request
        self.protocol_handler.run_once()
        self.server.queue.assert_called_once_with(build_http_request(
            b'GET', b'/get',
            headers={
                b'Host': b'uni.corn',
            }
        ))

        # Server write:
        self.protocol_handler.run_once()
        self.server.flush.assert_called_once()

        # Server read:
        self.server.recv.return_value = memoryview(server_response)
        self.protocol_handler.run_once()

        # Client write:
        self.client_ssl_connection.send.return_value = len(server_response)
        self.protocol_handler.run_once()
        self.client_ssl_connection.send.assert_called_once_with(server_response)

        # Server close connection:
        self.server.recv.return_value = None
        self.protocol_handler.run_once()
        self.protocol_handler.shutdown()

        with open(Path(tempfile.gettempdir()) / 'list.txt', 'rt') as cache_list:
            cache_lines = list(cache_list)
            self.assertEqual(len(cache_lines), 1)
            method, host, path, body, cache_file_name = cache_lines[0].strip().split(' ')
            self.assertEqual(method, 'GET')
            self.assertEqual(host, 'uni.corn')
            self.assertEqual(path, '/get')
            self.assertEqual(body, 'None')
        with open(Path(tempfile.gettempdir()) / ('proxy-cache-' + cache_file_name), 'rb') as cache_file:
            self.assertEqual(cache_file.read(), server_response)

    @with_and_without_upstream
    def test_cache_responses_plugin_load(self) -> None:
        request = build_http_request(
            b'GET', b'/get',
            headers={
                b'Host': b'uni.corn',
            }
        )
        cache_response = build_http_response(
            httpStatusCodes.OK,
            reason=b'OK',
            body=b'Response From Cache'
        )

        # Setup cache:
        with open(Path(tempfile.gettempdir()) / 'list.txt', 'wt') as cache_list:
            cache_list.write('CONNECT uni.corn / None connect\n')
            cache_list.write('GET uni.corn /get None test\n')
        with open(Path(tempfile.gettempdir()) / 'proxy-cache-connect', 'wb'):
            pass
        with open(Path(tempfile.gettempdir()) / 'proxy-cache-test', 'wb') as cache_file:
            cache_file.write(cache_response)

        self.connect()

        # Setup selector:
        self.mock_selector.return_value.select.side_effect = [
            [(selectors.SelectorKey(
                fileobj=self.client_ssl_connection,
                fd=self.client_ssl_connection.fileno,
                events=selectors.EVENT_READ,
                data=None), selectors.EVENT_READ)],
            [(selectors.SelectorKey(
                fileobj=self.client_ssl_connection,
                fd=self.client_ssl_connection.fileno,
                events=selectors.EVENT_WRITE,
                data=None), selectors.EVENT_WRITE)],
            [(selectors.SelectorKey(
                fileobj=self.client_ssl_connection,
                fd=self.client_ssl_connection.fileno,
                events=selectors.EVENT_READ,
                data=None), selectors.EVENT_READ)],
        ]

        # Client read:
        self.client_ssl_connection.recv.return_value = request
        self.protocol_handler.run_once()
        self.server_ssl_connection.send.assert_not_called()

        # Client write:
        self.client_ssl_connection.send.return_value = len(cache_response)
        self.protocol_handler.run_once()
        self.client_ssl_connection.send.assert_called_once_with(cache_response)

        # Client close connection:
        self.client_ssl_connection.recv.return_value = b''
        self.protocol_handler.run_once()
        self.protocol_handler.shutdown()

    @without_upstream
    def test_cache_responses_plugin_not_cached(self) -> None:
        request = build_http_request(
            b'GET', b'/get',
            headers={
                b'Host': b'uni.corn',
            }
        )
        cache_response = build_http_response(
            httpStatusCodes.BAD_GATEWAY,
            reason=b'Bad gateway',
            headers={
                b'Server': PROXY_AGENT_HEADER_VALUE,
                b'Connection': b'close',
            },
            body=b'Ressource has not been cached yet. Please allow upstream.'
        )

        self.connect()

        # Setup selector:
        self.mock_selector.return_value.select.side_effect = [
            [(selectors.SelectorKey(
                fileobj=self.client_ssl_connection,
                fd=self.client_ssl_connection.fileno,
                events=selectors.EVENT_READ,
                data=None), selectors.EVENT_READ)],
            [(selectors.SelectorKey(
                fileobj=self.client_ssl_connection,
                fd=self.client_ssl_connection.fileno,
                events=selectors.EVENT_WRITE,
                data=None), selectors.EVENT_WRITE)],
            [(selectors.SelectorKey(
                fileobj=self.client_ssl_connection,
                fd=self.client_ssl_connection.fileno,
                events=selectors.EVENT_READ,
                data=None), selectors.EVENT_READ)],
        ]

        # Client read:
        self.client_ssl_connection.recv.return_value = request
        self.protocol_handler.run_once()
        self.server_ssl_connection.send.assert_not_called()

        # Client write:
        self.client_ssl_connection.send.return_value = len(cache_response)
        self.protocol_handler.run_once()
        self.client_ssl_connection.send.assert_called_once_with(cache_response)

        # Client close connection:
        self.client_ssl_connection.recv.return_value = b''
        self.protocol_handler.run_once()
        self.protocol_handler.shutdown()

    @with_and_without_upstream
    def test_cache_responses_plugin_load_pipelined(self) -> None:
        requests = []
        cache_responses = []

        # Setup cache:
        with open(Path(tempfile.gettempdir()) / 'list.txt', 'wt') as cache_list:
            for r in range(1, 3):
                cache_list.write('GET uni.corn /test%d None test%d\n' % (r, r))
                requests.append(build_http_request(
                    b'GET', b'/test%d' % r,
                    headers={
                        b'Host': b'uni.corn',
                    }
                ))
                cache_responses.append(build_http_response(
                    httpStatusCodes.OK,
                    reason=b'OK',
                    body=b'Response %d From Cache' % r
                ))
                with open(Path(tempfile.gettempdir()) / ('proxy-cache-test%d' % r), 'wb') as cache_file:
                    cache_file.write(cache_responses[-1])

        self.connect()

        # Setup selector:
        self.mock_selector.return_value.select.side_effect = [
            [(selectors.SelectorKey(
                fileobj=self.client_ssl_connection,
                fd=self.client_ssl_connection.fileno,
                events=selectors.EVENT_READ,
                data=None), selectors.EVENT_READ)],
            [(selectors.SelectorKey(
                fileobj=self.client_ssl_connection,
                fd=self.client_ssl_connection.fileno,
                events=selectors.EVENT_WRITE,
                data=None), selectors.EVENT_WRITE)],
            [(selectors.SelectorKey(
                fileobj=self.client_ssl_connection,
                fd=self.client_ssl_connection.fileno,
                events=selectors.EVENT_READ,
                data=None), selectors.EVENT_READ)],
            [(selectors.SelectorKey(
                fileobj=self.client_ssl_connection,
                fd=self.client_ssl_connection.fileno,
                events=selectors.EVENT_WRITE,
                data=None), selectors.EVENT_WRITE)],
            [(selectors.SelectorKey(
                fileobj=self.client_ssl_connection,
                fd=self.client_ssl_connection.fileno,
                events=selectors.EVENT_READ,
                data=None), selectors.EVENT_READ)],
        ]

        for r in range(0, len(requests)):
            # Client read:
            self.client_ssl_connection.recv.return_value = requests[r]
            self.protocol_handler.run_once()
            self.server_ssl_connection.send.assert_not_called()

            # Client write:
            self.client_ssl_connection.send.return_value = len(cache_responses[r])
            self.protocol_handler.run_once()
            self.client_ssl_connection.send.assert_called_with(cache_responses[r])

        # Client close connection:
        self.client_ssl_connection.recv.return_value = b''
        self.protocol_handler.run_once()
        self.protocol_handler.shutdown()
