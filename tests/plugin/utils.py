# -*- coding: utf-8 -*-
"""
    proxy.py
    ~~~~~~~~
    ⚡⚡⚡ Fast, Lightweight, Pluggable, TLS interception capable proxy server focused on
    Network monitoring, controls & Application development, testing, debugging.

    :copyright: (c) 2013-present by Abhinav Singh and contributors.
    :license: BSD, see LICENSE for more details.
"""
from typing import Any, Type, Callable
from proxy.http.proxy import HttpProxyBasePlugin

from proxy.plugin import ModifyPostDataPlugin, ProposedRestApiPlugin, RedirectToCustomServerPlugin, \
    FilterByUpstreamHostPlugin, CacheResponsesPlugin, ManInTheMiddlePlugin, FilterByURLRegexPlugin


def with_and_without_upstream(fun: Callable[..., None]) -> Callable[..., None]:
    def decorated_fun(self: Any, *args: Any, **kwArgs: Any) -> None:
        with self.subTest(msg='Without upstream'):
            CacheResponsesPlugin.local.set()
            if hasattr(self, 'connect_upstream'):
                self.connect_upstream = False
            self.setUp()
            fun(self, *args, **kwArgs)
        with self.subTest(msg='With upstream'):
            CacheResponsesPlugin.local.clear()
            if hasattr(self, 'connect_upstream'):
                self.connect_upstream = True
            self.setUp()
            fun(self, *args, **kwArgs)
    return decorated_fun


def get_plugin_by_test_name(test_name: str) -> Type[HttpProxyBasePlugin]:
    plugin: Type[HttpProxyBasePlugin] = ModifyPostDataPlugin
    if test_name == 'test_modify_post_data_plugin':
        plugin = ModifyPostDataPlugin
    elif test_name == 'test_proposed_rest_api_plugin':
        plugin = ProposedRestApiPlugin
    elif test_name == 'test_redirect_to_custom_server_plugin':
        plugin = RedirectToCustomServerPlugin
    elif test_name == 'test_filter_by_upstream_host_plugin':
        plugin = FilterByUpstreamHostPlugin
    elif test_name.startswith('test_cache_responses_plugin'):
        plugin = CacheResponsesPlugin
    elif test_name == 'test_man_in_the_middle_plugin':
        plugin = ManInTheMiddlePlugin
    elif test_name == 'test_filter_by_url_regex_plugin':
        plugin = FilterByURLRegexPlugin
    return plugin
