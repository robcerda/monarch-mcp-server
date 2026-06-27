"""Tests for keyring backend detection and secure session storage."""

import sys
import types
from unittest.mock import MagicMock

import pytest

from monarch_mcp_server import secure_session as ss_module
from monarch_mcp_server.secure_session import _keyring_available


class _FakeKeyring:
    """Minimal stand-in for the `keyring` module used by detection tests."""

    def __init__(
        self,
        *,
        set_raises=None,
        get_returns=None,
        get_raises=None,
        delete_raises=None,
    ):
        self._set_raises = set_raises
        self._get_returns = get_returns
        self._get_raises = get_raises
        self._delete_raises = delete_raises
        self.set_calls = []
        self.get_calls = []
        self.delete_calls = []

    def set_password(self, service, username, value):
        self.set_calls.append((service, username, value))
        if self._set_raises:
            raise self._set_raises

    def get_password(self, service, username):
        self.get_calls.append((service, username))
        if self._get_raises:
            raise self._get_raises
        return self._get_returns

    def delete_password(self, service, username):
        self.delete_calls.append((service, username))
        if self._delete_raises:
            raise self._delete_raises


@pytest.fixture
def install_fake_keyring(monkeypatch):
    """Replace the importable `keyring` module with a controllable fake."""

    def _install(fake):
        module = types.ModuleType("keyring")
        module.set_password = fake.set_password
        module.get_password = fake.get_password
        module.delete_password = fake.delete_password
        monkeypatch.setitem(sys.modules, "keyring", module)
        return fake

    return _install


class TestKeyringAvailable:
    def test_returns_true_when_probe_round_trips(self, install_fake_keyring):
        """A real backend (set + get returns same value + delete) is accepted."""
        fake = install_fake_keyring(_FakeKeyring(get_returns="1"))
        assert _keyring_available() is True
        assert len(fake.set_calls) == 1
        assert len(fake.get_calls) == 1
        assert len(fake.delete_calls) == 1

    def test_macos_keychain_class_name_collision_is_handled(
        self, install_fake_keyring
    ):
        """The macOS Keychain and fail backends share the class name `Keyring`.

        Previously this caused real macOS keyrings to be rejected by name and
        tokens to be written to a plaintext file. The probe roundtrip ignores
        class names entirely and only trusts what the backend can actually do.
        """
        fake = install_fake_keyring(_FakeKeyring(get_returns="1"))
        # Simulate the macOS Keychain class name to prove name has no effect.
        fake.__class__.__name__ = "Keyring"
        assert _keyring_available() is True

    def test_returns_false_when_set_raises(self, install_fake_keyring):
        """The fail backend raises on set_password — we must NOT trust it."""
        install_fake_keyring(_FakeKeyring(set_raises=RuntimeError("no backend")))
        assert _keyring_available() is False

    def test_returns_false_when_get_returns_none(self, install_fake_keyring):
        """A backend that silently drops writes is not safe to use."""
        install_fake_keyring(_FakeKeyring(get_returns=None))
        assert _keyring_available() is False

    def test_returns_false_when_get_returns_wrong_value(self, install_fake_keyring):
        """A backend that corrupts the round-trip is not safe to use."""
        install_fake_keyring(_FakeKeyring(get_returns="not-the-probe-value"))
        assert _keyring_available() is False

    def test_returns_false_when_get_raises(self, install_fake_keyring):
        install_fake_keyring(
            _FakeKeyring(set_raises=None, get_raises=RuntimeError("read failed"))
        )
        assert _keyring_available() is False

    def test_returns_false_when_delete_raises(self, install_fake_keyring):
        """Delete failure means cleanup is broken; don't trust the backend."""
        install_fake_keyring(
            _FakeKeyring(get_returns="1", delete_raises=RuntimeError("rm failed"))
        )
        assert _keyring_available() is False

    def test_returns_false_when_keyring_not_installed(self, monkeypatch):
        """If the keyring package is absent, treat as unavailable, don't crash."""

        real_import = __builtins__["__import__"] if isinstance(
            __builtins__, dict
        ) else __builtins__.__import__

        def fake_import(name, *args, **kwargs):
            if name == "keyring":
                raise ImportError("no keyring installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        assert _keyring_available() is False

    def test_probe_uses_dedicated_username(self, install_fake_keyring):
        """The probe must not clobber the real token username."""
        fake = install_fake_keyring(_FakeKeyring(get_returns="1"))
        _keyring_available()
        for _service, username, _value in fake.set_calls:
            assert username != ss_module.KEYRING_USERNAME
        for _service, username in fake.get_calls:
            assert username != ss_module.KEYRING_USERNAME


class _StorageFakeKeyring:
    """In-memory keyring fake that round-trips set/get/delete.

    Lets save_session_blob/load_session roundtrip without touching the
    real Keychain or the host filesystem.
    """

    def __init__(self):
        self._store = {}

    def set_password(self, service, username, value):
        self._store[(service, username)] = value

    def get_password(self, service, username):
        return self._store.get((service, username))

    def delete_password(self, service, username):
        self._store.pop((service, username), None)


@pytest.fixture
def storage_keyring(monkeypatch):
    """Install a roundtrip-capable fake keyring and return a fresh session."""
    fake = _StorageFakeKeyring()
    module = types.ModuleType("keyring")
    module.set_password = fake.set_password
    module.get_password = fake.get_password
    module.delete_password = fake.delete_password
    monkeypatch.setitem(sys.modules, "keyring", module)

    session = ss_module.SecureMonarchSession()
    # __init__ ran the probe and set _use_keyring=True via the fake.
    assert session._use_keyring is True
    return session, fake


class TestSessionStorageRoundTrip:
    """save_session_blob → load_session must round-trip every supported shape."""

    def test_token_mode_roundtrip(self, storage_keyring):
        session, _ = storage_keyring
        session.save_session_blob(
            token="tok-abc",
            device_uuid="dev-xyz",
            auth_mode="token",
        )

        loaded = session.load_session()
        assert loaded == {
            "token": "tok-abc",
            "device_uuid": "dev-xyz",
            "auth_mode": "token",
        }

    def test_cookie_mode_roundtrip_preserves_nested_dict(self, storage_keyring):
        """Cookies must come back as a nested dict, not flattened to strings."""
        session, _ = storage_keyring
        cookies = {
            "session_id": "session-value",
            "csrftoken": "csrf-value",
            "cf_clearance": "cf-value",
        }
        session.save_session_blob(
            cookies=cookies,
            device_uuid="dev-xyz",
            auth_mode="cookie",
        )

        loaded = session.load_session()
        assert loaded is not None
        assert loaded["auth_mode"] == "cookie"
        assert loaded["cookies"] == cookies
        assert loaded["device_uuid"] == "dev-xyz"

    def test_cookie_mode_with_token_fallback(self, storage_keyring):
        """When cookies and a token coexist, both must round-trip."""
        session, _ = storage_keyring
        session.save_session_blob(
            token="tok-abc",
            cookies={"session_id": "s", "csrftoken": "c"},
            device_uuid="dev",
            auth_mode="cookie",
        )

        loaded = session.load_session()
        assert loaded["auth_mode"] == "cookie"
        assert loaded["token"] == "tok-abc"
        assert loaded["cookies"] == {"session_id": "s", "csrftoken": "c"}

    def test_requires_token_or_cookies(self, storage_keyring):
        session, _ = storage_keyring
        with pytest.raises(ValueError):
            session.save_session_blob(auth_mode="token")


class TestBackwardCompatLoading:
    """Existing keyring entries must keep working after the cookie upgrade."""

    def test_legacy_bare_token_string(self, storage_keyring):
        """Very old installs stored the raw token as the keyring value."""
        session, fake = storage_keyring
        fake.set_password(
            ss_module.KEYRING_SERVICE,
            ss_module.KEYRING_USERNAME,
            "legacy-bare-token",
        )

        loaded = session.load_session()
        assert loaded == {"token": "legacy-bare-token", "auth_mode": "token"}

    def test_pre_cookie_json_blob(self, storage_keyring):
        """Pre-cookie entries had token + device_uuid but no auth_mode key."""
        session, fake = storage_keyring
        fake.set_password(
            ss_module.KEYRING_SERVICE,
            ss_module.KEYRING_USERNAME,
            '{"token": "t", "device_uuid": "d"}',
        )

        loaded = session.load_session()
        assert loaded["token"] == "t"
        assert loaded["device_uuid"] == "d"
        # Without an explicit auth_mode and no cookies, default to "token".
        assert loaded["auth_mode"] == "token"

    def test_blob_with_cookies_defaults_to_cookie_mode(self, storage_keyring):
        """If a blob has cookies but no auth_mode, infer cookie mode."""
        session, fake = storage_keyring
        fake.set_password(
            ss_module.KEYRING_SERVICE,
            ss_module.KEYRING_USERNAME,
            '{"cookies": {"session_id": "s", "csrftoken": "c"}}',
        )

        loaded = session.load_session()
        assert loaded["cookies"] == {"session_id": "s", "csrftoken": "c"}
        assert loaded["auth_mode"] == "cookie"

    def test_missing_token_and_cookies_returns_none(self, storage_keyring):
        """A blob with neither credential type is unusable."""
        session, fake = storage_keyring
        fake.set_password(
            ss_module.KEYRING_SERVICE,
            ss_module.KEYRING_USERNAME,
            '{"auth_mode": "token", "device_uuid": "d"}',
        )

        assert session.load_session() is None


class TestGetAuthenticatedClient:
    """get_authenticated_client must dispatch on the stored auth_mode."""

    def test_cookie_mode_calls_set_cookies_on_client(self, storage_keyring, monkeypatch):
        session, _ = storage_keyring
        session.save_session_blob(
            cookies={"session_id": "s", "csrftoken": "c"},
            auth_mode="cookie",
        )

        # Capture what set_cookies is invoked with.
        fake_client = MagicMock()
        monkeypatch.setattr(
            ss_module, "create_monarch_client", lambda **kwargs: fake_client
        )

        client = session.get_authenticated_client()
        assert client is fake_client
        fake_client.set_cookies.assert_called_once_with(
            {"session_id": "s", "csrftoken": "c"}
        )

    def test_token_mode_does_not_call_set_cookies(self, storage_keyring, monkeypatch):
        session, _ = storage_keyring
        session.save_session_blob(
            token="tok",
            device_uuid="dev",
            auth_mode="token",
        )

        fake_client = MagicMock()
        captured = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            return fake_client

        monkeypatch.setattr(ss_module, "create_monarch_client", fake_create)

        client = session.get_authenticated_client()
        assert client is fake_client
        assert captured == {"token": "tok", "device_uuid": "dev"}
        fake_client.set_cookies.assert_not_called()

    def test_no_session_returns_none(self, storage_keyring):
        session, _ = storage_keyring
        assert session.get_authenticated_client() is None
