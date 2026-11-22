"""Tests for keyring backend detection and secure session storage."""

import json
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
        fake = install_fake_keyring(_FakeKeyring(get_returns=ss_module._PROBE_VALUE))
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
        fake = install_fake_keyring(_FakeKeyring(get_returns=ss_module._PROBE_VALUE))
        # Simulate the macOS Keychain class name to prove name has no effect.
        fake.__class__.__name__ = "Keyring"
        assert _keyring_available() is True

    def test_probe_uses_chunk_sized_payload(self, install_fake_keyring):
        """A 1-byte probe passes on backends whose real saves fail.

        Windows Credential Manager accepts tiny writes but rejects blobs over
        ~2560 bytes, so the probe must write a full chunk to prove that
        chunk-sized saves actually work.
        """
        fake = install_fake_keyring(_FakeKeyring(get_returns=ss_module._PROBE_VALUE))
        _keyring_available()
        (_service, _username, value) = fake.set_calls[0]
        assert len(value) == ss_module._KEYRING_CHUNK_SIZE

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

    def test_delete_failure_does_not_reject_a_working_backend(
        self, install_fake_keyring
    ):
        """A backend that stores and returns the sentinel is usable.

        Rejecting it because the probe could not clean itself up downgrades a
        working keyring to plaintext file storage, which is strictly worse than
        leaving one stale sentinel entry behind.
        """
        install_fake_keyring(
            _FakeKeyring(
                get_returns=ss_module._PROBE_VALUE,
                delete_raises=RuntimeError("rm failed"),
            )
        )
        assert _keyring_available() is True

    def test_probe_username_is_process_scoped(self):
        """Concurrent server processes must not race on one shared sentinel.

        MCP hosts start more than one server process. With a single shared
        probe username their probes interleave, one process deletes the
        sentinel the other just wrote, and that process concludes the keyring
        is unusable for its whole lifetime.
        """
        import os

        assert str(os.getpid()) in ss_module._PROBE_USERNAME

    def test_probe_cleans_up_even_when_get_raises(self, install_fake_keyring):
        """A failed probe must not leave its sentinel behind."""
        fake = install_fake_keyring(
            _FakeKeyring(get_raises=RuntimeError("read failed"))
        )
        assert _keyring_available() is False
        assert [u for _s, u in fake.delete_calls] == [ss_module._PROBE_USERNAME]

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
        fake = install_fake_keyring(_FakeKeyring(get_returns=ss_module._PROBE_VALUE))
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
def storage_keyring(monkeypatch, tmp_path):
    """Install a roundtrip-capable fake keyring and return a fresh session."""
    fake = _StorageFakeKeyring()
    module = types.ModuleType("keyring")
    module.set_password = fake.set_password
    module.get_password = fake.get_password
    module.delete_password = fake.delete_password
    monkeypatch.setitem(sys.modules, "keyring", module)
    # Sandbox the file fallback so tests never read or write the real
    # ~/.monarch-mcp-server/token on the host machine.
    monkeypatch.setattr(ss_module, "_TOKEN_DIR", tmp_path / "fallback")
    monkeypatch.setattr(ss_module, "_TOKEN_FILE", tmp_path / "fallback" / "token")

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


class _WindowsLimitedKeyring(_StorageFakeKeyring):
    """Simulates Windows Credential Manager's CRED_MAX_CREDENTIAL_BLOB_SIZE.

    The WinVault backend stores passwords as UTF-16 (2 bytes/char) and the
    OS rejects blobs over ~2560 bytes, so writes over 1280 characters fail
    with the (1783, 'CredWrite', 'The stub received bad data') error.
    """

    MAX_CHARS = 1280

    def set_password(self, service, username, value):
        if len(value) > self.MAX_CHARS:
            raise OSError(1783, "CredWrite", "The stub received bad data")
        super().set_password(service, username, value)


def _oversized_cookies():
    """Cookies large enough that the JSON blob exceeds one keyring entry."""
    return {
        "session_id": "s" * 200,
        "csrftoken": "c" * 100,
        "cf_clearance": "f" * 3000,
    }


class TestChunkedKeyringStorage:
    """Blobs too large for one Windows credential must chunk transparently."""

    def test_oversized_blob_roundtrips(self, storage_keyring):
        session, fake = storage_keyring
        cookies = _oversized_cookies()
        session.save_session_blob(
            token="tok-abc",
            device_uuid="dev-xyz",
            cookies=cookies,
            auth_mode="cookie",
        )

        loaded = session.load_session()
        assert loaded is not None
        assert loaded["token"] == "tok-abc"
        assert loaded["device_uuid"] == "dev-xyz"
        assert loaded["cookies"] == cookies
        assert loaded["auth_mode"] == "cookie"

    def test_oversized_blob_is_stored_in_chunks(self, storage_keyring):
        session, fake = storage_keyring
        session.save_session_blob(cookies=_oversized_cookies(), auth_mode="cookie")

        main = fake.get_password(ss_module.KEYRING_SERVICE, ss_module.KEYRING_USERNAME)
        index = json.loads(main)
        count = index[ss_module._CHUNK_MARKER]
        generation = index[ss_module._CHUNK_GEN_MARKER]
        assert count >= 2

        for i in range(count):
            chunk = fake.get_password(
                ss_module.KEYRING_SERVICE, ss_module._chunk_username(i, generation)
            )
            assert chunk is not None
            # Every entry must fit within one Windows credential blob.
            assert len(chunk) <= ss_module._KEYRING_CHUNK_SIZE
        # No orphan entries past the recorded count.
        assert (
            fake.get_password(
                ss_module.KEYRING_SERVICE,
                ss_module._chunk_username(count, generation),
            )
            is None
        )

    def test_oversized_blob_saves_on_windows_sized_backend(
        self, monkeypatch, tmp_path
    ):
        """The exact production failure: a big cookie blob on Windows.

        Before chunking, set_password raised (1783, 'CredWrite', ...) and the
        session fell back to a plaintext file. With chunking every write is
        under the limit, so the save must succeed inside the keyring.
        """
        fake = _WindowsLimitedKeyring()
        module = types.ModuleType("keyring")
        module.set_password = fake.set_password
        module.get_password = fake.get_password
        module.delete_password = fake.delete_password
        monkeypatch.setitem(sys.modules, "keyring", module)
        # Point the file fallback at a sandbox so we can prove it stays unused.
        monkeypatch.setattr(ss_module, "_TOKEN_DIR", tmp_path / "fallback")
        monkeypatch.setattr(ss_module, "_TOKEN_FILE", tmp_path / "fallback" / "token")

        session = ss_module.SecureMonarchSession()
        assert session._use_keyring is True

        cookies = _oversized_cookies()
        session.save_session_blob(cookies=cookies, auth_mode="cookie")

        assert not (tmp_path / "fallback" / "token").exists(), (
            "oversized session must not fall back to plaintext file storage"
        )
        loaded = session.load_session()
        assert loaded["cookies"] == cookies

    def test_small_save_after_oversized_removes_stale_chunks(self, storage_keyring):
        session, fake = storage_keyring
        session.save_session_blob(cookies=_oversized_cookies(), auth_mode="cookie")
        session.save_session_blob(token="tiny-token", auth_mode="token")

        loaded = session.load_session()
        assert loaded == {"token": "tiny-token", "auth_mode": "token"}
        # All chunk entries from the earlier oversized save must be gone.
        for generation in (None, *ss_module._CHUNK_GENERATIONS):
            assert (
                fake.get_password(
                    ss_module.KEYRING_SERVICE,
                    ss_module._chunk_username(0, generation),
                )
                is None
            )

    def test_shrinking_oversized_save_removes_extra_chunks(self, storage_keyring):
        """A smaller (but still chunked) save must not leave orphan chunks."""
        session, fake = storage_keyring
        session.save_session_blob(
            cookies={"cf_clearance": "f" * 8000}, auth_mode="cookie"
        )
        session.save_session_blob(
            cookies={"cf_clearance": "f" * 2000}, auth_mode="cookie"
        )

        loaded = session.load_session()
        assert loaded["cookies"] == {"cf_clearance": "f" * 2000}
        main = fake.get_password(ss_module.KEYRING_SERVICE, ss_module.KEYRING_USERNAME)
        index = json.loads(main)
        count = index[ss_module._CHUNK_MARKER]
        assert (
            fake.get_password(
                ss_module.KEYRING_SERVICE,
                ss_module._chunk_username(count, index[ss_module._CHUNK_GEN_MARKER]),
            )
            is None
        )

    def test_delete_token_removes_index_and_chunks(self, storage_keyring):
        session, fake = storage_keyring
        session.save_session_blob(cookies=_oversized_cookies(), auth_mode="cookie")

        session.delete_token()

        assert fake._store == {}
        assert session.load_session() is None

    def test_missing_chunk_treated_as_no_session(self, storage_keyring):
        """A corrupted chunked entry must not crash or return partial JSON."""
        session, fake = storage_keyring
        session.save_session_blob(cookies=_oversized_cookies(), auth_mode="cookie")
        index = json.loads(
            fake.get_password(ss_module.KEYRING_SERVICE, ss_module.KEYRING_USERNAME)
        )
        fake.delete_password(
            ss_module.KEYRING_SERVICE,
            ss_module._chunk_username(1, index[ss_module._CHUNK_GEN_MARKER]),
        )

        assert session.load_session() is None

    def test_single_entry_format_unchanged_for_small_blobs(self, storage_keyring):
        """Small sessions must keep the exact pre-chunking storage format."""
        session, fake = storage_keyring
        session.save_session_blob(token="tok", device_uuid="dev", auth_mode="token")

        main = fake.get_password(ss_module.KEYRING_SERVICE, ss_module.KEYRING_USERNAME)
        parsed = json.loads(main)
        assert ss_module._CHUNK_MARKER not in parsed
        assert parsed["token"] == "tok"


class TestFailedSaveIsNonDestructive:
    """A save that fails must never cost the user the session they had.

    Chunk entries are written under a generation tag and the index is flipped
    only once every chunk is stored, so a partial write is invisible.
    """

    def test_partial_chunk_write_leaves_previous_session_intact(
        self, storage_keyring, monkeypatch
    ):
        session, fake = storage_keyring
        good = {"session_id": "s" * 200, "cf_clearance": "f" * 3000}
        session.save_session_blob(cookies=good, auth_mode="cookie")
        assert session.load_session()["cookies"] == good

        # Fail midway through writing the replacement, the way Windows
        # Credential Manager does when it runs out of credential space.
        calls = {"n": 0}
        real_set = fake.set_password

        def flaky_set(service, username, value):
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError(1783, "CredWrite", "The stub received bad data")
            return real_set(service, username, value)

        monkeypatch.setitem(
            sys.modules,
            "keyring",
            _module_from(fake, set_password=flaky_set),
        )

        with pytest.raises(OSError):
            session._keyring_save("x" * 5000)

        # The session the user actually had is still there and still correct.
        assert session.load_session()["cookies"] == good

    def test_corrupt_keyring_entry_falls_through_to_file_fallback(
        self, storage_keyring, monkeypatch, tmp_path
    ):
        """A bad keyring read must not strand a user who has a good file."""
        session, fake = storage_keyring
        session._save_token_file(
            json.dumps({"token": "file-token", "auth_mode": "token"})
        )
        fake.set_password(
            ss_module.KEYRING_SERVICE,
            ss_module.KEYRING_USERNAME,
            '{"auth_mode": "cookie", "token": "eyJ0eX',
        )

        loaded = session.load_session()
        assert loaded is not None, "a corrupt keyring entry hid a good session"
        assert loaded["token"] == "file-token"

    def test_legacy_ungenerationed_chunks_still_load(self, storage_keyring):
        """Sessions written before generations existed must survive upgrade."""
        session, fake = storage_keyring
        blob = json.dumps({"token": "t" * 2000, "auth_mode": "token"})
        chunks = [
            blob[i : i + ss_module._KEYRING_CHUNK_SIZE]
            for i in range(0, len(blob), ss_module._KEYRING_CHUNK_SIZE)
        ]
        for i, chunk in enumerate(chunks):
            fake.set_password(
                ss_module.KEYRING_SERVICE, ss_module._chunk_username(i), chunk
            )
        fake.set_password(
            ss_module.KEYRING_SERVICE,
            ss_module.KEYRING_USERNAME,
            json.dumps({ss_module._CHUNK_MARKER: len(chunks)}),
        )

        assert session.load_session()["token"] == "t" * 2000

    def test_next_save_after_legacy_chunks_does_not_clobber_them(
        self, storage_keyring
    ):
        """The first generationed save must not overwrite the live legacy data."""
        session, fake = storage_keyring
        blob = json.dumps({"token": "t" * 2000, "auth_mode": "token"})
        chunks = [
            blob[i : i + ss_module._KEYRING_CHUNK_SIZE]
            for i in range(0, len(blob), ss_module._KEYRING_CHUNK_SIZE)
        ]
        for i, chunk in enumerate(chunks):
            fake.set_password(
                ss_module.KEYRING_SERVICE, ss_module._chunk_username(i), chunk
            )
        fake.set_password(
            ss_module.KEYRING_SERVICE,
            ss_module.KEYRING_USERNAME,
            json.dumps({ss_module._CHUNK_MARKER: len(chunks)}),
        )

        session.save_session_blob(cookies={"cf_clearance": "n" * 3000}, auth_mode="cookie")

        assert session.load_session()["cookies"] == {"cf_clearance": "n" * 3000}
        # The superseded legacy chunks are cleaned up, not left dangling.
        assert (
            fake.get_password(
                ss_module.KEYRING_SERVICE, ss_module._chunk_username(0)
            )
            is None
        )


def _module_from(fake, **overrides):
    module = types.ModuleType("keyring")
    module.set_password = overrides.get("set_password", fake.set_password)
    module.get_password = overrides.get("get_password", fake.get_password)
    module.delete_password = overrides.get("delete_password", fake.delete_password)
    return module


@pytest.fixture
def file_session(monkeypatch, tmp_path):
    """A session forced onto the file fallback, sandboxed to tmp_path."""
    monkeypatch.setattr(ss_module, "_keyring_available", lambda: False)
    monkeypatch.setattr(ss_module, "_TOKEN_DIR", tmp_path / "store")
    monkeypatch.setattr(ss_module, "_TOKEN_FILE", tmp_path / "store" / "token")
    session = ss_module.SecureMonarchSession()
    assert session._use_keyring is False
    return session, tmp_path / "store" / "token"


class TestFileFallbackWrites:
    """The file fallback holds a full access credential; treat it as one."""

    def test_non_ascii_round_trips_regardless_of_locale(self, tmp_path, monkeypatch):
        """The fallback is written UTF-8, so it must be read UTF-8.

        read_text() with no encoding uses the locale's preferred encoding,
        which on a non-UTF-8 Windows console is cp1252. A session blob holding
        any non-ASCII character then either raises UnicodeDecodeError or
        decodes to a different string than was stored, so the credential comes
        back silently corrupt rather than missing.
        """
        token_file = tmp_path / "token.json"
        monkeypatch.setattr(ss_module, "_TOKEN_FILE", token_file)

        blob = json.dumps(
            {"token": "abc", "name": "Zoë – café"}, ensure_ascii=False
        )
        assert any(ord(c) > 127 for c in blob)
        ss_module._write_secret_file(token_file, blob)

        assert token_file.read_bytes().decode("utf-8") == blob
        assert ss_module.SecureMonarchSession()._load_token_file() == blob

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason=(
            "POSIX mode bits are not how Windows protects this file. "
            "os.stat() there reports a synthesised mode that ignores the ACL, "
            "so the assertion below cannot express the property. The Windows "
            "equivalent -- DPAPI encryption, which makes the bytes unreadable "
            "to another local user regardless of ACL -- is covered by the "
            "DPAPI tests."
        ),
    )
    def test_file_is_never_world_readable(self, file_session):
        """0600 must be set at creation, not after the bytes are on disk.

        write_text creates the file under the process umask (typically 0644)
        and only then chmods, leaving a window where any local user can read
        the token.
        """
        import os
        import stat as stat_module

        session, token_file = file_session
        session.save_session_blob(token="tok", auth_mode="token")

        mode = stat_module.S_IMODE(os.stat(token_file).st_mode)
        assert mode == 0o600, oct(mode)
        dir_mode = stat_module.S_IMODE(os.stat(token_file.parent).st_mode)
        assert dir_mode == 0o700, oct(dir_mode)

    def test_write_is_atomic_via_replace(self, file_session, monkeypatch):
        """A reader must never observe a partially written blob."""
        import os

        session, token_file = file_session
        session.save_session_blob(token="original", auth_mode="token")

        seen = {}
        real_replace = os.replace

        def spy_replace(src, dst):
            # Before the rename lands, the live file still holds the old blob.
            seen["during"] = ss_module._TOKEN_FILE.read_text(encoding="utf-8")
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", spy_replace)
        session.save_session_blob(token="replacement", auth_mode="token")

        # On Windows the blob is DPAPI-encrypted at rest, so the old token is
        # never present as plaintext. Decrypt before asserting, or the test
        # checks the storage format rather than the atomicity it is named for.
        during = seen["during"]
        if during.startswith(ss_module._DPAPI_PREFIX):
            during = ss_module._dpapi_decrypt(during)
        assert "original" in during
        assert session.load_session()["token"] == "replacement"

    def test_failed_write_leaves_no_temp_file_behind(self, file_session, monkeypatch):
        import os

        session, token_file = file_session
        session.save_session_blob(token="good", auth_mode="token")

        def boom(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            session.save_session_blob(token="doomed", auth_mode="token")

        assert session.load_session()["token"] == "good"
        assert list(token_file.parent.iterdir()) == [token_file]


class TestCorruptedSessionHandling:
    """A truncated JSON blob must not be reinterpreted as a bare token."""

    def test_truncated_json_is_not_treated_as_a_legacy_token(self, file_session):
        """The exact half-written-blob shape from a crash mid save.

        Read back as a token it becomes an Authorization header of garbage,
        and every call 401s for the life of the process.
        """
        session, token_file = file_session
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text('{"auth_mode": "cookie", "token": "eyJ0eX')

        assert session.load_session() is None

    def test_truncated_json_array_is_also_rejected(self, file_session):
        session, token_file = file_session
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text('[{"token": "abc"')

        assert session.load_session() is None

    def test_genuine_legacy_bare_token_still_loads(self, file_session):
        """Very old installs stored the raw token string; keep reading those."""
        session, token_file = file_session
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text("legacy-bare-token-value")

        assert session.load_session() == {
            "token": "legacy-bare-token-value",
            "auth_mode": "token",
        }

    def test_spliced_chunk_debris_is_not_accepted_as_a_token(self, file_session):
        """Debris that does not start with a brace must still be rejected.

        Reassembling chunks from two different saves produces exactly this
        shape. Accepted as a token it yields a client whose every call fails
        with an opaque 401 for the life of the process.
        """
        session, token_file = file_session
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text('xxxxxxxx", "cookies": {"cf_clearance": "ffff"}}')

        assert session.load_session() is None

    def test_absurdly_long_value_is_not_accepted_as_a_token(self, file_session):
        session, token_file = file_session
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text("x" * 5000)

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
