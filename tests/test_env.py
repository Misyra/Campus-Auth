from __future__ import annotations

from src.utils.env import build_login_env_vars


class TestBuildLoginEnvVars:
    """Tests for build_login_env_vars()."""

    def test_task_url_resolves_runtime_username(self):
        """{{USERNAME}} in task_url must resolve to runtime_config username, not OS env."""
        vars = build_login_env_vars(
            {
                "auth_url": "http://example.com",
                "username": "testuser",
                "password": "testpass",
                "isp": "mobile",
            },
            task_url="http://{{USERNAME}}:{{PASSWORD}}@{{ISP}}.example.com",
        )
        assert vars["LOGIN_URL"] == "http://testuser:testpass@mobile.example.com"

    def test_task_url_resolves_all_runtime_vars(self):
        """All runtime vars (ISP, USERNAME, PASSWORD) must be available in task_url."""
        vars = build_login_env_vars(
            {
                "auth_url": "http://fallback.com",
                "username": "alice",
                "password": "secret123",
                "isp": "unicom",
            },
            task_url="http://{{ISP}}.auth.com?user={{USERNAME}}&pass={{PASSWORD}}",
        )
        assert vars["LOGIN_URL"] == "http://unicom.auth.com?user=alice&pass=secret123"

    def test_task_url_without_templates_uses_as_is(self):
        """task_url without templates is set directly as LOGIN_URL."""
        vars = build_login_env_vars(
            {"auth_url": "http://example.com"},
            task_url="http://portal.edu/login",
        )
        assert vars["LOGIN_URL"] == "http://portal.edu/login"

    def test_auth_url_fallback_when_no_task_url(self):
        """Without task_url, LOGIN_URL falls back to auth_url."""
        vars = build_login_env_vars(
            {"auth_url": "http://example.com", "username": "user1"},
        )
        assert vars["LOGIN_URL"] == "http://example.com"

    def test_runtime_username_overrides_os_username(self):
        """runtime_config USERNAME must override OS USERNAME in env_vars."""
        vars = build_login_env_vars(
            {"username": "campus_user"},
        )
        assert vars["USERNAME"] == "campus_user"

    def test_custom_variables_injected_before_task_url(self):
        """custom_variables must be available for task_url resolution."""
        vars = build_login_env_vars(
            {"auth_url": "http://example.com"},
            task_url="http://example.com?token={{API_TOKEN}}",
            custom_variables={"API_TOKEN": "abc123"},
        )
        assert vars["LOGIN_URL"] == "http://example.com?token=abc123"

    def test_empty_runtime_vars_not_injected(self):
        """Empty string runtime vars should not override OS env."""
        import os

        os_username = os.environ.get("USERNAME", "")
        vars = build_login_env_vars(
            {"auth_url": "http://example.com", "username": "", "password": "", "isp": ""},
        )
        # Empty username should NOT set USERNAME in env_vars
        if os_username:
            assert vars["USERNAME"] == os_username
