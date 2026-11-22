"""Tests for elicitation-based auth tools."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from monarchmoney import RequireMFAException

from monarch_mcp_server import auth

# Captured at import time, before conftest's autouse fixture replaces the name
# in monarch_mcp_server.client with a mock. The cache invalidation test needs
# the real implementation to prove an unauthenticated process actually refuses.
_real_get_monarch_client = __import__(
    "monarch_mcp_server.client", fromlist=["get_monarch_client"]
).get_monarch_client


def make_ctx(*elicit_results):
    """Build a mock Context whose elicit() returns the given results in order."""
    ctx = MagicMock()
    ctx.elicit = AsyncMock(side_effect=list(elicit_results))
    return ctx


def accept(**fields):
    return SimpleNamespace(action="accept", data=SimpleNamespace(**fields))


def cancel():
    return SimpleNamespace(action="cancel", data=None)


@pytest.fixture(autouse=True)
def no_session_save():
    """Prevent real keyring writes during auth tests."""
    with patch("monarch_mcp_server.auth.secure_session") as mock:
        yield mock


class TestLoginInteractive:
    def test_happy_path_no_mfa(self, no_session_save):
        mm = AsyncMock()
        with patch("monarch_mcp_server.auth.MonarchMoney", return_value=mm):
            ctx = make_ctx(accept(email="a@b.com", password="pw"))
            result = asyncio.run(auth.login_interactive(ctx))
        assert "Logged in" in result
        mm.login.assert_awaited_once()
        no_session_save.save_authenticated_session.assert_called_once_with(mm)

    def test_mfa_required(self, no_session_save):
        mm = AsyncMock()
        mm.login.side_effect = RequireMFAException("mfa")
        with patch("monarch_mcp_server.auth.MonarchMoney", return_value=mm):
            ctx = make_ctx(
                accept(email="a@b.com", password="pw"),
                accept(mfa_code="123456"),
            )
            result = asyncio.run(auth.login_interactive(ctx))
        assert "Logged in" in result
        mm.multi_factor_authenticate.assert_awaited_once_with(
            "a@b.com", "pw", "123456"
        )
        no_session_save.save_authenticated_session.assert_called_once_with(mm)

    def test_user_cancels_initial_form(self, no_session_save):
        ctx = make_ctx(cancel())
        result = asyncio.run(auth.login_interactive(ctx))
        assert result == "Login cancelled."
        no_session_save.save_authenticated_session.assert_not_called()

    def test_user_cancels_mfa(self, no_session_save):
        mm = AsyncMock()
        mm.login.side_effect = RequireMFAException("mfa")
        with patch("monarch_mcp_server.auth.MonarchMoney", return_value=mm):
            ctx = make_ctx(accept(email="a@b.com", password="pw"), cancel())
            result = asyncio.run(auth.login_interactive(ctx))
        assert result == "Login cancelled."
        no_session_save.save_authenticated_session.assert_not_called()


class TestLoginWithTokenInteractive:
    def test_happy_path(self, no_session_save):
        mm = AsyncMock()
        with patch("monarch_mcp_server.auth.MonarchMoney", return_value=mm):
            ctx = make_ctx(accept(token="raw-token"))
            result = asyncio.run(auth.login_with_token_interactive(ctx))
        assert "saved" in result.lower()
        mm.get_subscription_details.assert_awaited_once()
        no_session_save.save_token.assert_called_once_with("raw-token")

    def test_strips_whitespace(self, no_session_save):
        mm = AsyncMock()
        with patch("monarch_mcp_server.auth.MonarchMoney", return_value=mm):
            ctx = make_ctx(accept(token="  token-with-spaces  "))
            asyncio.run(auth.login_with_token_interactive(ctx))
        no_session_save.save_token.assert_called_once_with("token-with-spaces")

    def test_empty_token_rejected(self, no_session_save):
        ctx = make_ctx(accept(token="   "))
        result = asyncio.run(auth.login_with_token_interactive(ctx))
        assert "Empty" in result
        no_session_save.save_token.assert_not_called()

    def test_user_cancels(self, no_session_save):
        ctx = make_ctx(cancel())
        result = asyncio.run(auth.login_with_token_interactive(ctx))
        assert result == "Login cancelled."
        no_session_save.save_token.assert_not_called()


class TestLogout:
    def test_clears_session(self, no_session_save):
        result = asyncio.run(auth.logout())
        assert "Cleared" in result
        no_session_save.delete_token.assert_called_once()


class TestClientCacheInvalidation:
    """Storage and the cached client must be kept in step.

    The cached MonarchMoney holds its own Authorization header, so it is
    unaffected by what is or is not in the keyring.
    """

    def test_logout_drops_the_cached_client(self, no_session_save):
        from monarch_mcp_server import client as client_module

        client_module._cached_client = object()
        asyncio.run(auth.logout())
        assert client_module._cached_client is None

    def test_login_drops_the_stale_cached_client(self, no_session_save):
        from monarch_mcp_server import client as client_module

        client_module._cached_client = object()
        mm = AsyncMock()
        with patch("monarch_mcp_server.auth.MonarchMoney", return_value=mm):
            ctx = make_ctx(accept(email="a@b.com", password="pw"))
            asyncio.run(auth.login_interactive(ctx))
        assert client_module._cached_client is None

    def test_token_login_drops_the_stale_cached_client(self, no_session_save):
        from monarch_mcp_server import client as client_module

        client_module._cached_client = object()
        mm = AsyncMock()
        with patch("monarch_mcp_server.auth.MonarchMoney", return_value=mm):
            ctx = make_ctx(accept(token="fresh-token"))
            asyncio.run(auth.login_with_token_interactive(ctx))
        assert client_module._cached_client is None

    def test_logged_out_process_cannot_serve_tool_calls(self, no_session_save):
        """The end to end property: after logout, the next call must re-auth.

        Before this, monarch_logout reported success while every subsequent
        get_accounts in that process still returned live financial data.
        """
        from monarch_mcp_server import client as client_module

        client_module._cached_client = object()
        asyncio.run(auth.logout())

        with patch.object(
            client_module.secure_session,
            "get_authenticated_client",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match="Authentication needed"):
                asyncio.run(_real_get_monarch_client())


class TestDebugSessionLoading:
    def test_no_session_message(self):
        from monarch_mcp_server.tools import auth as tools_auth

        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_session",
            return_value=None,
        ):
            result = asyncio.run(tools_auth.debug_session_loading())
        assert "No Monarch session" in result

    def test_token_present_does_not_leak_length(self):
        from monarch_mcp_server.tools import auth as tools_auth

        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_session",
            return_value={"token": "a-secret-token-value", "auth_mode": "token"},
        ):
            result = asyncio.run(tools_auth.debug_session_loading())
        assert "Session found" in result
        assert "auth_mode=token" in result
        assert "length" not in result.lower()
        assert "a-secret-token-value" not in result

    def test_cookie_session_reports_authenticated(self):
        """Cookie-mode sessions carry no token; they must not read as missing."""
        from monarch_mcp_server.tools import auth as tools_auth

        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_session",
            return_value={
                "cookies": {"session_id": "s3cr3t", "csrftoken": "c5rf"},
                "auth_mode": "cookie",
            },
        ):
            result = asyncio.run(tools_auth.debug_session_loading())
        assert "Session found" in result
        assert "auth_mode=cookie" in result
        assert "cookies" in result
        assert "s3cr3t" not in result
        assert "c5rf" not in result

    def test_keyring_failure_omits_traceback(self):
        from monarch_mcp_server.tools import auth as tools_auth

        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_session",
            side_effect=RuntimeError("keyring backend unavailable"),
        ):
            result = asyncio.run(tools_auth.debug_session_loading())
        assert "Keyring access failed" in result
        assert "RuntimeError" in result
        assert "keyring backend unavailable" in result
        assert "Traceback" not in result
        assert 'File "' not in result


class TestCheckAuthStatus:
    def test_cookie_session_reports_authenticated(self):
        from monarch_mcp_server.tools import auth as tools_auth

        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_session",
            return_value={
                "cookies": {"session_id": "s3cr3t"},
                "auth_mode": "cookie",
            },
        ):
            result = asyncio.run(tools_auth.check_auth_status())
        assert "Session found" in result
        assert "auth_mode=cookie" in result
        assert "s3cr3t" not in result

    def test_no_session_reports_missing(self):
        from monarch_mcp_server.tools import auth as tools_auth

        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_session",
            return_value=None,
        ):
            result = asyncio.run(tools_auth.check_auth_status())
        assert "No Monarch session" in result


class TestElicitNotSupported:
    """Older MCP SDKs (<1.10) do not expose Context.elicit."""

    def test_login_interactive_returns_upgrade_hint(self, no_session_save):
        ctx = SimpleNamespace()  # no elicit attribute
        result = asyncio.run(auth.login_interactive(ctx))
        assert "1.10" in result
        assert "login_setup.py" in result
        no_session_save.save_authenticated_session.assert_not_called()

    def test_login_with_token_returns_upgrade_hint(self, no_session_save):
        ctx = SimpleNamespace()
        result = asyncio.run(auth.login_with_token_interactive(ctx))
        assert "1.10" in result
        no_session_save.save_token.assert_not_called()


class TestCheckAuthStatusDoesNotEchoEnvEmail:
    """MONARCH_EMAIL authenticates nothing: it was read in one place, to print
    it. Echoing it implied setting it configured something, and handed the
    account email to any caller that reached the HTTP port."""

    def test_env_email_is_not_in_the_response(self, monkeypatch):
        from monarch_mcp_server.tools import auth as tools_auth

        monkeypatch.setenv("MONARCH_EMAIL", "someone@example.invalid")
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_session",
            return_value={"token": "t", "auth_mode": "token"},
        ):
            result = asyncio.run(tools_auth.check_auth_status())
        assert "someone@example.invalid" not in result
        assert "MONARCH_EMAIL" not in result
