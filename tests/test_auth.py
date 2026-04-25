"""Tests for elicitation-based auth tools."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from monarchmoney import RequireMFAException

from monarch_mcp_server import auth


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
