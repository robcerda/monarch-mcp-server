from unittest.mock import patch

from monarch_mcp_server.monarch_auth import (
    EMAIL_OTP_REQUIRED_MESSAGE,
    _is_captcha_required,
    _looks_like_jwt,
    build_login_payload,
    configure_monarchmoney,
    cookies_from_client,
    create_monarch_client,
    is_email_otp_required,
)


class _FakeMonarchMoney:
    """Stand-in for MonarchMoney with a real headers dict (the test harness
    mocks the real monarchmoney package, whose MagicMock _headers can't be
    asserted on)."""

    def __init__(self, token=None):
        self.token = token
        self._headers = {}

    def set_token(self, token):
        self.token = token


def test_configure_monarchmoney_uses_current_api_host():
    from monarchmoney import MonarchMoneyEndpoints

    original_base_url = MonarchMoneyEndpoints.BASE_URL
    try:
        MonarchMoneyEndpoints.BASE_URL = "https://api.monarchmoney.com"

        configure_monarchmoney()

        assert MonarchMoneyEndpoints.BASE_URL == "https://api.monarch.com"
    finally:
        MonarchMoneyEndpoints.BASE_URL = original_base_url


def test_login_payload_advertises_current_auth_capabilities():
    payload = build_login_payload("user@example.com", "secret")

    assert payload == {
        "username": "user@example.com",
        "password": "secret",
        "supports_mfa": True,
        "supports_email_otp": True,
        "supports_recaptcha": True,
        # trusted_device=True is required for Monarch to return a long-lived
        # token (tokenExpiration=null). False yields a 1-hour token that
        # expires mid-session per hammem/monarchmoney#139.
        "trusted_device": True,
    }


def test_email_otp_payload_uses_email_otp_field_not_totp():
    payload = build_login_payload("user@example.com", "secret", email_otp="123456")

    assert payload["email_otp"] == "123456"
    assert "totp" not in payload


def test_email_otp_required_detects_monarch_email_code_response():
    assert is_email_otp_required(
        403,
        {"detail": "Retrieve the code from your email to continue login."},
    )


def test_email_otp_message_is_actionable_for_mcp_users():
    assert "email" in EMAIL_OTP_REQUIRED_MESSAGE.lower()
    assert "login_setup.py" in EMAIL_OTP_REQUIRED_MESSAGE


def test_create_client_restores_device_uuid_with_token():
    with patch(
        "monarch_mcp_server.monarch_auth.MonarchMoney", _FakeMonarchMoney
    ):
        client = create_monarch_client(
            token="token-value", device_uuid="device-value"
        )

    assert client._headers["Authorization"] == "Token token-value"
    assert client._headers["device-uuid"] == "device-value"


def test_looks_like_jwt_detects_three_part_tokens():
    assert _looks_like_jwt("eyJhbGciOi.eyJzdWIiOi.abc123") is True
    assert _looks_like_jwt("opaque-long-token-with-no-dots") is False
    # Two dots in a row should be rejected too (still matches header.payload.sig shape)
    assert _looks_like_jwt("a.b.c") is True
    # Edge: must be a string
    assert _looks_like_jwt(None) is False  # type: ignore[arg-type]


def test_captcha_required_detection():
    assert _is_captcha_required(403, {"error_code": "CAPTCHA_REQUIRED"}) is True
    # Same error_code at a different status should not be classified as captcha
    assert _is_captcha_required(429, {"error_code": "CAPTCHA_REQUIRED"}) is False
    # 403 alone is not enough — could be MFA or generic
    assert _is_captcha_required(403, {"detail": "something else"}) is False


def test_cookies_from_client_returns_none_for_token_mode():
    client = _FakeMonarchMoney()
    client._auth_mode = "token"
    client._cookies = None
    assert cookies_from_client(client) is None


def test_cookies_from_client_returns_dict_for_cookie_mode():
    client = _FakeMonarchMoney()
    client._auth_mode = "cookie"
    client._cookies = {"session_id": "s", "csrftoken": "c"}
    result = cookies_from_client(client)
    assert result == {"session_id": "s", "csrftoken": "c"}
    # Must return a copy so callers cannot mutate the client's internal state
    result["session_id"] = "mutated"
    assert client._cookies["session_id"] == "s"


def test_cookies_from_client_handles_missing_attributes():
    """A bare MonarchMoney without auth_mode set should look token-like."""
    client = _FakeMonarchMoney()
    # _auth_mode not set at all
    assert cookies_from_client(client) is None
