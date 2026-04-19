"""Tests for the secure session / keyring layer."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from monarch_mcp_server.secure_session import (
    KEYRING_SERVICE,
    KEYRING_USERNAME,
    SecureMonarchSession,
)


def _make_session_with_backend(use_keyring: bool) -> SecureMonarchSession:
    """Build a SecureMonarchSession with a forced backend choice."""
    with patch(
        "monarch_mcp_server.secure_session._keyring_available",
        return_value=use_keyring,
    ):
        return SecureMonarchSession()


class TestKeyringBackend:
    def test_save_calls_keyring_set(self):
        session = _make_session_with_backend(use_keyring=True)
        with patch("keyring.set_password") as mock_set, patch.object(
            session, "_cleanup_old_session_files"
        ):
            session.save_token("abc123")
        mock_set.assert_called_once_with(KEYRING_SERVICE, KEYRING_USERNAME, "abc123")

    def test_load_returns_keyring_value(self):
        session = _make_session_with_backend(use_keyring=True)
        with patch("keyring.get_password", return_value="abc123"):
            assert session.load_token() == "abc123"

    def test_load_returns_none_when_empty(self):
        session = _make_session_with_backend(use_keyring=True)
        with patch("keyring.get_password", return_value=None):
            assert session.load_token() is None

    def test_delete_calls_keyring_delete(self):
        session = _make_session_with_backend(use_keyring=True)
        with patch("keyring.delete_password") as mock_del, patch.object(
            session, "_delete_token_file"
        ), patch.object(session, "_cleanup_old_session_files"):
            session.delete_token()
        mock_del.assert_called_once_with(KEYRING_SERVICE, KEYRING_USERNAME)

    def test_keyring_save_failure_falls_back_to_file(self, tmp_path):
        session = _make_session_with_backend(use_keyring=True)
        with patch("keyring.set_password", side_effect=RuntimeError("no backend")), patch(
            "monarch_mcp_server.secure_session._TOKEN_DIR", tmp_path / "mm"
        ), patch(
            "monarch_mcp_server.secure_session._TOKEN_FILE", tmp_path / "mm" / "token"
        ), patch.object(session, "_cleanup_old_session_files"):
            session.save_token("fallback-tkn")
        assert (tmp_path / "mm" / "token").read_text() == "fallback-tkn"


class TestFileBackend:
    def test_save_writes_file_with_0600(self, tmp_path):
        token_dir = tmp_path / "mm"
        token_file = token_dir / "token"
        session = _make_session_with_backend(use_keyring=False)

        with patch(
            "monarch_mcp_server.secure_session._TOKEN_DIR", token_dir
        ), patch(
            "monarch_mcp_server.secure_session._TOKEN_FILE", token_file
        ), patch.object(session, "_cleanup_old_session_files"):
            session.save_token("tkn-file")

        assert token_file.read_text() == "tkn-file"
        # 0o600: owner read/write only
        assert token_file.stat().st_mode & 0o777 == 0o600
        assert token_dir.stat().st_mode & 0o777 == 0o700

    def test_load_reads_file(self, tmp_path):
        token_dir = tmp_path / "mm"
        token_dir.mkdir()
        token_file = token_dir / "token"
        token_file.write_text("tkn-persisted")

        session = _make_session_with_backend(use_keyring=False)
        with patch(
            "monarch_mcp_server.secure_session._TOKEN_FILE", token_file
        ):
            assert session.load_token() == "tkn-persisted"

    def test_load_returns_none_when_no_file(self, tmp_path):
        session = _make_session_with_backend(use_keyring=False)
        with patch(
            "monarch_mcp_server.secure_session._TOKEN_FILE", tmp_path / "nope"
        ):
            assert session.load_token() is None

    def test_delete_removes_file_and_empty_dir(self, tmp_path):
        token_dir = tmp_path / "mm"
        token_dir.mkdir()
        token_file = token_dir / "token"
        token_file.write_text("x")

        session = _make_session_with_backend(use_keyring=False)
        with patch(
            "monarch_mcp_server.secure_session._TOKEN_DIR", token_dir
        ), patch(
            "monarch_mcp_server.secure_session._TOKEN_FILE", token_file
        ), patch.object(session, "_cleanup_old_session_files"):
            session.delete_token()

        assert not token_file.exists()
        assert not token_dir.exists()


class TestGetAuthenticatedClient:
    def test_returns_client_when_token_present(self):
        session = _make_session_with_backend(use_keyring=True)
        mock_mm_cls = MagicMock()
        with patch("keyring.get_password", return_value="tkn"), patch(
            "monarch_mcp_server.secure_session.MonarchMoney", mock_mm_cls
        ):
            client = session.get_authenticated_client()
        mock_mm_cls.assert_called_once_with(token="tkn")
        assert client is mock_mm_cls.return_value

    def test_returns_none_when_no_token(self):
        session = _make_session_with_backend(use_keyring=True)
        with patch("keyring.get_password", return_value=None):
            assert session.get_authenticated_client() is None

    def test_returns_none_when_monarch_ctor_fails(self):
        session = _make_session_with_backend(use_keyring=True)
        mock_mm_cls = MagicMock(side_effect=ValueError("bad token"))
        with patch("keyring.get_password", return_value="tkn"), patch(
            "monarch_mcp_server.secure_session.MonarchMoney", mock_mm_cls
        ):
            assert session.get_authenticated_client() is None


class TestSaveAuthenticatedSession:
    def test_saves_token_from_mm(self):
        session = _make_session_with_backend(use_keyring=True)
        mm = MagicMock(token="new-tkn")
        with patch.object(session, "save_token") as mock_save:
            session.save_authenticated_session(mm)
        mock_save.assert_called_once_with("new-tkn")

    def test_noop_when_mm_has_no_token(self):
        session = _make_session_with_backend(use_keyring=True)
        mm = MagicMock(token=None)
        with patch.object(session, "save_token") as mock_save:
            session.save_authenticated_session(mm)
        mock_save.assert_not_called()
