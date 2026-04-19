"""Tests for the elicitation-based auth flow."""

from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from monarchmoney import RequireMFAException

from monarch_mcp_server.auth import (
    LoginForm,
    MFAForm,
    TokenForm,
    login_interactive,
    login_with_token_interactive,
    logout,
)


def _accept(model):
    return AcceptedElicitation(data=model)


class TestLoginInteractive:
    async def test_successful_login_no_mfa(self):
        ctx = AsyncMock()
        ctx.elicit.return_value = _accept(
            LoginForm(email="x@example.com", password="pw")
        )

        mock_mm = AsyncMock()
        mock_mm.login = AsyncMock()

        with patch(
            "monarch_mcp_server.auth.MonarchMoney", return_value=mock_mm
        ), patch(
            "monarch_mcp_server.auth.secure_session.save_authenticated_session"
        ) as mock_save:
            result = await login_interactive(ctx)

        assert "Logged in" in result
        mock_mm.login.assert_awaited_once_with(
            "x@example.com",
            "pw",
            use_saved_session=False,
            save_session=False,
        )
        mock_mm.multi_factor_authenticate.assert_not_awaited()
        mock_save.assert_called_once_with(mock_mm)

    async def test_login_cancelled_at_credentials(self):
        ctx = AsyncMock()
        ctx.elicit.return_value = DeclinedElicitation()

        with patch(
            "monarch_mcp_server.auth.secure_session.save_authenticated_session"
        ) as mock_save:
            result = await login_interactive(ctx)

        assert result == "Login cancelled."
        mock_save.assert_not_called()

    async def test_login_with_mfa(self):
        ctx = AsyncMock()
        ctx.elicit.side_effect = [
            _accept(LoginForm(email="x@example.com", password="pw")),
            _accept(MFAForm(mfa_code="123456")),
        ]

        mock_mm = AsyncMock()
        mock_mm.login = AsyncMock(side_effect=RequireMFAException("need mfa"))
        mock_mm.multi_factor_authenticate = AsyncMock()

        with patch(
            "monarch_mcp_server.auth.MonarchMoney", return_value=mock_mm
        ), patch(
            "monarch_mcp_server.auth.secure_session.save_authenticated_session"
        ) as mock_save:
            result = await login_interactive(ctx)

        assert "Logged in" in result
        mock_mm.multi_factor_authenticate.assert_awaited_once_with(
            "x@example.com", "pw", "123456"
        )
        mock_save.assert_called_once_with(mock_mm)
        assert ctx.elicit.await_count == 2

    async def test_mfa_cancelled(self):
        ctx = AsyncMock()
        ctx.elicit.side_effect = [
            _accept(LoginForm(email="x@example.com", password="pw")),
            DeclinedElicitation(),
        ]

        mock_mm = AsyncMock()
        mock_mm.login = AsyncMock(side_effect=RequireMFAException("need mfa"))

        with patch(
            "monarch_mcp_server.auth.MonarchMoney", return_value=mock_mm
        ), patch(
            "monarch_mcp_server.auth.secure_session.save_authenticated_session"
        ) as mock_save:
            result = await login_interactive(ctx)

        assert result == "Login cancelled."
        mock_mm.multi_factor_authenticate.assert_not_awaited()
        mock_save.assert_not_called()


class TestLoginWithTokenInteractive:
    async def test_successful_token_login(self):
        ctx = AsyncMock()
        ctx.elicit.return_value = _accept(TokenForm(token="tkn-live-xyz"))

        mock_mm = AsyncMock()
        mock_mm.get_subscription_details = AsyncMock(return_value={"ok": True})

        with patch(
            "monarch_mcp_server.auth.MonarchMoney", return_value=mock_mm
        ) as mock_cls, patch(
            "monarch_mcp_server.auth.secure_session.save_token"
        ) as mock_save:
            result = await login_with_token_interactive(ctx)

        mock_cls.assert_called_once_with(token="tkn-live-xyz")
        mock_mm.get_subscription_details.assert_awaited_once()
        mock_save.assert_called_once_with("tkn-live-xyz")
        assert "Session token saved" in result

    async def test_token_login_cancelled(self):
        ctx = AsyncMock()
        ctx.elicit.return_value = DeclinedElicitation()

        with patch(
            "monarch_mcp_server.auth.secure_session.save_token"
        ) as mock_save:
            result = await login_with_token_interactive(ctx)

        assert result == "Login cancelled."
        mock_save.assert_not_called()

    async def test_whitespace_token_rejected(self):
        ctx = AsyncMock()
        ctx.elicit.return_value = _accept(TokenForm(token="   "))

        with patch(
            "monarch_mcp_server.auth.secure_session.save_token"
        ) as mock_save, patch(
            "monarch_mcp_server.auth.MonarchMoney"
        ) as mock_cls:
            result = await login_with_token_interactive(ctx)

        assert "Empty token" in result
        mock_save.assert_not_called()
        mock_cls.assert_not_called()

    async def test_invalid_token_surfaces_error(self):
        ctx = AsyncMock()
        ctx.elicit.return_value = _accept(TokenForm(token="bad"))

        mock_mm = AsyncMock()
        mock_mm.get_subscription_details = AsyncMock(
            side_effect=Exception("401 Unauthorized")
        )

        with patch(
            "monarch_mcp_server.auth.MonarchMoney", return_value=mock_mm
        ), patch(
            "monarch_mcp_server.auth.secure_session.save_token"
        ) as mock_save:
            with pytest.raises(Exception, match="401 Unauthorized"):
                await login_with_token_interactive(ctx)

        mock_save.assert_not_called()


class TestLogout:
    async def test_clears_keyring(self):
        with patch(
            "monarch_mcp_server.auth.secure_session.delete_token"
        ) as mock_delete:
            result = await logout()

        assert "Cleared" in result
        mock_delete.assert_called_once()
