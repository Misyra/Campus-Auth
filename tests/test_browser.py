from __future__ import annotations


from src.utils.browser import BrowserContextManager


class TestBrowserContextManagerInit:

    def test_default_config(self):
        mgr = BrowserContextManager({})
        assert mgr.config == {}
        assert mgr.cancel_event is None
        assert mgr.browser_settings == {}

    def test_with_config(self):
        config = {
            "browser_settings": {"headless": False, "safe_mode": True},
        }
        mgr = BrowserContextManager(config)
        assert mgr.browser_settings["headless"] is False
        assert mgr.browser_settings["safe_mode"] is True

    def test_cancel_event(self):
        import threading
        evt = threading.Event()
        mgr = BrowserContextManager({}, cancel_event=evt)
        assert mgr.cancel_event is evt

    def test_is_cancelled_false(self):
        mgr = BrowserContextManager({})
        assert mgr._is_cancelled() is False

    def test_is_cancelled_true(self):
        import threading
        evt = threading.Event()
        evt.set()
        mgr = BrowserContextManager({}, cancel_event=evt)
        assert mgr._is_cancelled() is True


class TestBrowserArgs:

    def test_default_args(self):
        mgr = BrowserContextManager({})
        args = mgr._get_browser_args()
        assert "--no-sandbox" in args
        assert "--disable-dev-shm-usage" in args

    def test_disable_web_security(self):
        config = {"browser_settings": {"disable_web_security": True}}
        mgr = BrowserContextManager(config)
        args = mgr._get_browser_args()
        assert "--disable-web-security" in args

    def test_low_resource_mode(self):
        config = {"browser_settings": {"low_resource_mode": True}}
        mgr = BrowserContextManager(config)
        args = mgr._get_browser_args()
        assert "--blink-settings=imagesEnabled=false" in args

    def test_custom_args(self):
        config = {"browser_settings": {"browser_args": "--flag1 --flag2"}}
        mgr = BrowserContextManager(config)
        args = mgr._get_browser_args()
        assert "--flag1" in args
        assert "--flag2" in args


class TestExtraHeaders:

    def test_empty(self):
        mgr = BrowserContextManager({})
        assert mgr._get_extra_http_headers() == {}

    def test_valid_json(self):
        config = {"browser_settings": {"extra_headers_json": '{"X-Custom": "value"}'}}
        mgr = BrowserContextManager(config)
        headers = mgr._get_extra_http_headers()
        assert headers == {"X-Custom": "value"}

    def test_invalid_json(self):
        config = {"browser_settings": {"extra_headers_json": "not json"}}
        mgr = BrowserContextManager(config)
        assert mgr._get_extra_http_headers() == {}

    def test_non_dict_json(self):
        config = {"browser_settings": {"extra_headers_json": "[1, 2, 3]"}}
        mgr = BrowserContextManager(config)
        assert mgr._get_extra_http_headers() == {}
