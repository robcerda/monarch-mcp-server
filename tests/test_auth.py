"""Tests for hard-disabled auth tools, cookie auth, and credential env behavior."""

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
    def test_no_session(self):
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_cookies",
            return_value=None,
        ), patch(
            "monarch_mcp_server.tools.auth.secure_session.load_token",
            return_value=None,
        ):
            result = asyncio.run(tools_auth.check_auth_status())
        assert "No authentication session" in result

    def test_with_cookies(self):
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_cookies",
            return_value=("sid", "csrf"),
        ), patch(
            "monarch_mcp_server.tools.auth.secure_session.load_token",
            return_value=None,
        ):
            result = asyncio.run(tools_auth.check_auth_status())
        assert "Session cookies found" in result
        # Must not mention the legacy-token warning when cookies are present.
        assert "legacy" not in result.lower()

    def test_with_legacy_token_only_warns(self):
        """When only a legacy token is stored, the user must see a warning."""
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_cookies",
            return_value=None,
        ), patch(
            "monarch_mcp_server.tools.auth.secure_session.load_token",
            return_value="legacy-token-value",
        ):
            result = asyncio.run(tools_auth.check_auth_status())
        assert "legacy" in result.lower()
        assert "May 2026" in result
        # Cookies are the cure — point the user at the right option.
        assert "cookie" in result.lower()
        # Never leak the actual token value into the status string.
        assert "legacy-token-value" not in result

    def test_cookies_take_precedence_over_legacy_token(self):
        """When both are stored, the cookie status wins (no broken-token warning)."""
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_cookies",
            return_value=("sid", "csrf"),
        ), patch(
            "monarch_mcp_server.tools.auth.secure_session.load_token",
            return_value="legacy-token",
        ):
            result = asyncio.run(tools_auth.check_auth_status())
        assert "Session cookies found" in result
        assert "legacy" not in result.lower()

    def test_env_email_does_not_imply_auto_login(self, monkeypatch):
        """MONARCH_EMAIL must be surfaced as unused, not as an active credential."""
        monkeypatch.setenv("MONARCH_EMAIL", "user@example.com")
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_cookies",
            return_value=None,
        ), patch(
            "monarch_mcp_server.tools.auth.secure_session.load_token",
            return_value=None,
        ):
            result = asyncio.run(tools_auth.check_auth_status())
        assert "user@example.com" in result
        assert "NOT used" in result


class TestDebugSessionLoading:
    def test_no_session_message(self):
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_cookies",
            return_value=None,
        ), patch(
            "monarch_mcp_server.tools.auth.secure_session.load_token",
            return_value=None,
        ):
            result = asyncio.run(tools_auth.debug_session_loading())
        assert "No session" in result

    def test_cookies_present(self):
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_cookies",
            return_value=("sid", "csrf"),
        ):
            result = asyncio.run(tools_auth.debug_session_loading())
        assert "cookies found" in result.lower()
        # Never leak cookie values.
        assert "sid" not in result.split("found")[0] or "session" in result.lower()

    def test_legacy_token_only_warns(self):
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_cookies",
            return_value=None,
        ), patch(
            "monarch_mcp_server.tools.auth.secure_session.load_token",
            return_value="a-secret-token-value",
        ):
            result = asyncio.run(tools_auth.debug_session_loading())
        assert "legacy" in result.lower()
        assert "a-secret-token-value" not in result

    def test_keyring_failure_omits_traceback(self):
        with patch(
            "monarch_mcp_server.tools.auth.secure_session.load_cookies",
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

    def test_login_setup_does_not_load_dotenv(self):
        """login_setup.py must not silently read credentials from a .env file."""
        from pathlib import Path

        import monarch_mcp_server

        repo_root = Path(monarch_mcp_server.__file__).resolve().parents[2]
        login_setup = repo_root / "login_setup.py"
        text = login_setup.read_text(encoding="utf-8")
        assert "load_dotenv" not in text
        assert "from dotenv" not in text


class TestCookieAuthSubclass:
    """The MonarchMoneyCookieAuth subclass must send cookies + x-csrftoken."""

    def test_subclass_strips_authorization_and_sets_csrftoken(self):
        """Cookie auth removes Authorization and installs x-csrftoken + Origin."""
        from monarch_mcp_server.cookie_auth import (
            WEB_ORIGIN,
            MonarchMoneyCookieAuth,
        )

        mm = MonarchMoneyCookieAuth(session_id="sid-val", csrftoken="csrf-val")
        # The legacy Authorization header MUST be absent.
        assert mm._headers.get("Authorization") is None
        # The x-csrftoken header must mirror the csrftoken cookie.
        assert mm._headers["x-csrftoken"] == "csrf-val"
        # Origin / Referer must point at the web app, not the API host.
        assert mm._headers["Origin"] == WEB_ORIGIN
        assert mm._headers["Referer"].startswith(WEB_ORIGIN)

    def test_cookies_payload(self):
        from monarch_mcp_server.cookie_auth import MonarchMoneyCookieAuth

        mm = MonarchMoneyCookieAuth(session_id="sid", csrftoken="csrf")
        assert mm._cookies() == {"session_id": "sid", "csrftoken": "csrf"}


class TestSecureSessionCookiePath:
    """Cookie save / load / delete and client preference."""

    def _fresh_session(self, tmp_path, monkeypatch):
        """Spin up an isolated SecureMonarchSession with file-based storage."""
        from monarch_mcp_server import secure_session as ss_module

        monkeypatch.setattr(ss_module, "_TOKEN_DIR", tmp_path)
        monkeypatch.setattr(ss_module, "_TOKEN_FILE", tmp_path / "token")
        monkeypatch.setattr(
            ss_module, "_COOKIES_FILE", tmp_path / "cookies.json"
        )
        session = ss_module.SecureMonarchSession()
        # Force the file-fallback path so the test doesn't poke the real keyring.
        session._use_keyring = False
        return session, ss_module

    def test_save_and_load_cookies_roundtrip(self, tmp_path, monkeypatch):
        session, _ = self._fresh_session(tmp_path, monkeypatch)
        session.save_cookies("sid-val", "csrf-val")
        assert session.load_cookies() == ("sid-val", "csrf-val")

    def test_cookies_file_is_owner_only_readable(self, tmp_path, monkeypatch):
        session, ss_module = self._fresh_session(tmp_path, monkeypatch)
        session.save_cookies("sid", "csrf")
        mode = (tmp_path / "cookies.json").stat().st_mode & 0o777
        assert mode == 0o600

    def test_delete_token_clears_both_cookies_and_token(
        self, tmp_path, monkeypatch
    ):
        session, _ = self._fresh_session(tmp_path, monkeypatch)
        session.save_cookies("sid", "csrf")
        session.save_token("legacy")
        session.delete_token()
        assert session.load_cookies() is None
        assert session.load_token() is None

    def test_get_authenticated_client_prefers_cookies(
        self, tmp_path, monkeypatch
    ):
        session, ss_module = self._fresh_session(tmp_path, monkeypatch)
        session.save_cookies("sid", "csrf")
        session.save_token("legacy-token-still-present")

        sentinel = object()
        captured = {}

        def fake_ctor(*, session_id, csrftoken):
            captured["sid"] = session_id
            captured["csrf"] = csrftoken
            return sentinel

        monkeypatch.setattr(ss_module, "MonarchMoneyCookieAuth", fake_ctor)
        # If the cookie path were skipped, this would be called instead.
        mm_called = {"called": False}

        def fake_mm(*args, **kwargs):
            mm_called["called"] = True
            return object()

        monkeypatch.setattr(ss_module, "MonarchMoney", fake_mm)

        client = session.get_authenticated_client()
        assert client is sentinel
        assert captured == {"sid": "sid", "csrf": "csrf"}
        assert mm_called["called"] is False

    def test_get_authenticated_client_falls_back_to_token(
        self, tmp_path, monkeypatch
    ):
        session, ss_module = self._fresh_session(tmp_path, monkeypatch)
        session.save_token("legacy-token")

        sentinel = object()
        captured = {}

        def fake_mm(*, token=None, **kwargs):
            captured["token"] = token
            return sentinel

        monkeypatch.setattr(ss_module, "MonarchMoney", fake_mm)
        # Ensure cookie ctor is never invoked when no cookies are stored.
        def boom(**kwargs):
            raise AssertionError(
                "MonarchMoneyCookieAuth should not be called without cookies"
            )

        monkeypatch.setattr(ss_module, "MonarchMoneyCookieAuth", boom)

        client = session.get_authenticated_client()
        assert client is sentinel
        assert captured == {"token": "legacy-token"}

    def test_get_authenticated_client_returns_none_with_no_session(
        self, tmp_path, monkeypatch
    ):
        session, _ = self._fresh_session(tmp_path, monkeypatch)
        assert session.get_authenticated_client() is None

    def test_save_authenticated_session_dispatches_on_cookie_subclass(
        self, tmp_path, monkeypatch
    ):
        session, ss_module = self._fresh_session(tmp_path, monkeypatch)

        from monarch_mcp_server.cookie_auth import MonarchMoneyCookieAuth

        mm = MonarchMoneyCookieAuth(session_id="sid", csrftoken="csrf")
        session.save_authenticated_session(mm)
        assert session.load_cookies() == ("sid", "csrf")
        # Legacy token must NOT have been written by the cookie path.
        assert session.load_token() is None


class TestLoginSetupCookieMenu:
    """The terminal-only login_setup.py must default to the cookie option."""

    def _login_setup_source(self):
        from pathlib import Path

        import monarch_mcp_server

        repo_root = Path(monarch_mcp_server.__file__).resolve().parents[2]
        return (repo_root / "login_setup.py").read_text(encoding="utf-8")

    def test_cookie_option_is_listed_first(self):
        text = self._login_setup_source()
        cookie_idx = text.find("Session cookies from browser")
        email_idx = text.find("Email and password")
        legacy_idx = text.find("Legacy session token paste")
        assert 0 < cookie_idx < email_idx < legacy_idx, (
            "Cookie option must appear first in the menu so it is the default."
        )

    def test_legacy_paths_labeled_broken(self):
        text = self._login_setup_source()
        assert "currently broken" in text

    def test_uses_cookie_auth_subclass(self):
        text = self._login_setup_source()
        assert "MonarchMoneyCookieAuth" in text
