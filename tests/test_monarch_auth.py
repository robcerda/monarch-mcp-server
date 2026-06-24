from unittest.mock import patch

from monarch_mcp_server.monarch_auth import (
    EMAIL_OTP_REQUIRED_MESSAGE,
    build_login_payload,
    configure_monarchmoney,
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
        "trusted_device": False,
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
