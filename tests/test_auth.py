"""Tests for hard-disabled auth tools and credential env behavior."""

import asyncio
import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from monarch_mcp_server import auth
from monarch_mcp_server.tools import auth as tools_auth


class TestAuthHelpersDisabled:
    """The legacy elicitation auth flow is intentionally removed."""

    def test_login_interactive_raises(self):
        with pytest.raises(auth.AuthDisabledError):
            asyncio.run(auth.login_interactive(None))

    def test_login_with_token_raises(self):
        with pytest.raises(auth.AuthDisabledError):
            asyncio.run(auth.login_with_token_interactive(None))

    def test_logout_raises(self):
        with pytest.raises(auth.AuthDisabledError):
            asyncio.run(auth.logout())


class TestMcpAuthToolsDisabled:
    """The MCP-exposed login/logout tools refuse regardless of read-only flag."""

    def test_monarch_login_disabled(self):
        result = asyncio.run(tools_auth.monarch_login())
        payload = json.loads(result)
        assert payload["disabled"] is True
        assert payload["tool"] == "monarch_login"
        assert "login_setup.py" in payload["error"]

    def test_monarch_login_with_token_disabled(self):
        result = asyncio.run(tools_auth.monarch_login_with_token())
        payload = json.loads(result)
        assert payload["disabled"] is True
        assert payload["tool"] == "monarch_login_with_token"

    def test_monarch_logout_disabled(self):
        result = asyncio.run(tools_auth.monarch_logout())
        payload = json.loads(result)
        assert payload["disabled"] is True
        assert payload["tool"] == "monarch_logout"

    def test_disabled_even_when_read_only_off(self, monkeypatch):
        """Auth mutations are hard-disabled — not gated by the read-only flag."""
        monkeypatch.setenv("MONARCH_MCP_READ_ONLY", "false")
        for fn in (
            tools_auth.monarch_login,
            tools_auth.monarch_login_with_token,
            tools_auth.monarch_logout,
        ):
            payload = json.loads(asyncio.run(fn()))
            assert payload["disabled"] is True

    def test_setup_authentication_points_at_login_setup(self):
        result = asyncio.run(tools_auth.setup_authentication())
        assert "login_setup.py" in result
        assert "does not accept credentials" in result.lower()


class TestCheckAuthStatus:
    def test_no_token(self):
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_token",
            return_value=None,
        ):
            result = asyncio.run(tools_auth.check_auth_status())
        assert "No authentication token" in result

    def test_with_token(self):
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_token",
            return_value="some-token",
        ):
            result = asyncio.run(tools_auth.check_auth_status())
        assert "token found" in result.lower()

    def test_env_email_does_not_imply_auto_login(self, monkeypatch):
        """MONARCH_EMAIL must be surfaced as unused, not as an active credential."""
        monkeypatch.setenv("MONARCH_EMAIL", "user@example.com")
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_token",
            return_value=None,
        ):
            result = asyncio.run(tools_auth.check_auth_status())
        assert "user@example.com" in result
        assert "NOT used" in result


class TestDebugSessionLoading:
    def test_no_token_message(self):
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_token",
            return_value=None,
        ):
            result = asyncio.run(tools_auth.debug_session_loading())
        assert "No token" in result

    def test_token_present_does_not_leak_value(self):
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_token",
            return_value="a-secret-token-value",
        ):
            result = asyncio.run(tools_auth.debug_session_loading())
        assert "Token found" in result
        assert "a-secret-token-value" not in result

    def test_keyring_failure_omits_traceback(self):
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_token",
            side_effect=RuntimeError("keyring backend unavailable"),
        ):
            result = asyncio.run(tools_auth.debug_session_loading())
        assert "Keyring access failed" in result
        assert "RuntimeError" in result
        assert "Traceback" not in result


class TestNoEnvCredentialAutoLogin:
    """MONARCH_EMAIL/MONARCH_PASSWORD must not trigger an auto-login."""

    def test_get_monarch_client_ignores_env_credentials(self, monkeypatch):
        """Even with both env vars set, the client must not auto-login.

        We invoke the *real* factory (resolved at the function object level
        before the autouse patch is consulted) and assert it raises rather
        than calling MonarchMoney().login() with env credentials.
        """
        monkeypatch.setenv("MONARCH_EMAIL", "user@example.com")
        monkeypatch.setenv("MONARCH_PASSWORD", "hunter2")

        from monarch_mcp_server import client as client_module

        # The autouse patch in conftest replaces client_module.get_monarch_client
        # with an AsyncMock. We grab the real coroutine function via the
        # patcher's `_mock_name`/attribute? Easier: locate it on the module
        # globals it was originally defined in by reading source.
        # Strategy: import the source function via its qualified name from
        # the module's __dict__ using an internal copy we save once.
        real_fn = client_module.__dict__.get("_real_get_monarch_client")
        if real_fn is None:
            # Pull it out before tests patch it: load fresh from source.
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "_fresh_client_module", client_module.__file__
            )
            fresh = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(fresh)
            real_fn = fresh.get_monarch_client
            # Patch secure_session so it doesn't return a real client.
            fresh._cached_client = None
            with patch.object(
                fresh.secure_session,
                "get_authenticated_client",
                return_value=None,
            ):
                with pytest.raises(RuntimeError) as exc:
                    asyncio.run(real_fn())

        message = str(exc.value)
        assert "login_setup.py" in message
        assert "MONARCH_EMAIL" in message or "credentials" in message.lower()

    def test_client_module_does_not_read_env_credentials(self):
        """Guard against reintroducing silent env credential loading.

        We allow the strings to appear in user-facing error messages, but the
        client must never actually call os.getenv for the credential vars.
        """
        from monarch_mcp_server import client as client_module

        source = client_module.__file__
        with open(source, encoding="utf-8") as f:
            text = f.read()
        for bad in (
            'os.getenv("MONARCH_EMAIL"',
            "os.getenv('MONARCH_EMAIL'",
            'os.getenv("MONARCH_PASSWORD"',
            "os.getenv('MONARCH_PASSWORD'",
            'os.environ["MONARCH_PASSWORD"',
            "os.environ['MONARCH_PASSWORD'",
        ):
            assert bad not in text, f"unexpected env-credential lookup: {bad}"
        assert "load_dotenv" not in text
        assert "from dotenv" not in text

    def test_app_module_does_not_load_dotenv(self):
        """The MCP server entrypoint must not auto-load .env files."""
        from monarch_mcp_server import app as app_module

        with open(app_module.__file__, encoding="utf-8") as f:
            text = f.read()
        assert "load_dotenv" not in text
        assert "from dotenv" not in text
