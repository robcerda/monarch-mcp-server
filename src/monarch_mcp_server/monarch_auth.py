"""Authentication compatibility for Monarch's current web API.

Monarch changed its auth flow in May 2026:
- API calls go to ``https://api.monarch.com`` (not ``api.monarchmoney.com``).
- New/unrecognized sessions may require an email one-time code even when
  account MFA is disabled, returned distinctly from a TOTP MFA challenge.
- Reloading a saved token needs the same ``device-uuid`` used at login.

This module wraps the upstream ``monarchmoney`` package with those changes
instead of rewriting the MCP tools.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from uuid import uuid4

from aiohttp import ClientSession
from monarchmoney import MonarchMoney, MonarchMoneyEndpoints, RequireMFAException
from monarchmoney.monarchmoney import LoginFailedException


CURRENT_API_BASE_URL = "https://api.monarch.com"

# Captured from the monarch-core-web-app login request on 2026-06-23. Monarch
# validates this against a server-side minimum; if logins begin failing with an
# "app update required" / 403 error, recapture it from the web app (DevTools →
# Network → any api.monarch.com request → request header
# "monarch-client-version") and bump the value here.
MONARCH_CLIENT_VERSION = "v1.0.1668"

EMAIL_OTP_REQUIRED_MESSAGE = (
    "Monarch sent a one-time code to your email. Run `python login_setup.py` "
    "to complete email verification and save a reusable session token."
)
_EMAIL_OTP_RE = re.compile(r"email.*(?:code|otp)|(?:code|otp).*email", re.I)
_MFA_RE = re.compile(r"mfa|multi.?factor|two.?factor|2fa|totp", re.I)


class EmailOtpRequiredException(Exception):
    """Raised when Monarch requires an email one-time code to continue login."""


def configure_monarchmoney() -> None:
    """Point the upstream monarchmoney package at Monarch's current API host."""
    MonarchMoneyEndpoints.BASE_URL = CURRENT_API_BASE_URL


def create_monarch_client(
    token: Optional[str] = None, *, device_uuid: Optional[str] = None
) -> MonarchMoney:
    """Create a MonarchMoney client with current endpoint and web headers."""
    configure_monarchmoney()
    client = MonarchMoney(token=token)
    client._headers.update(
        {
            "Origin": "https://app.monarch.com",
            "device-uuid": device_uuid or str(uuid4()),
            "monarch-client": "monarch-core-web-app-graphql",
            "monarch-client-version": MONARCH_CLIENT_VERSION,
        }
    )
    if token:
        client._headers["Authorization"] = f"Token {token}"
    return client


def build_login_payload(
    email: str,
    password: str,
    *,
    email_otp: Optional[str] = None,
    mfa_code: Optional[str] = None,
) -> dict[str, Any]:
    """Build a login payload compatible with current Monarch auth."""
    payload: dict[str, Any] = {
        "username": email,
        "password": password,
        "supports_mfa": True,
        "supports_email_otp": True,
        "supports_recaptcha": True,
        "trusted_device": False,
    }
    if email_otp:
        payload["email_otp"] = email_otp
    if mfa_code:
        payload["totp"] = mfa_code
    return payload


def is_email_otp_required(status: int, payload: dict[str, Any]) -> bool:
    """Return whether a Monarch auth response is requesting email OTP."""
    detail = str(payload.get("detail") or "")
    error_code = str(payload.get("error_code") or "")
    combined = f"{detail} {error_code}"
    return error_code == "EMAIL_OTP_REQUIRED" or (
        status == 403 and bool(_EMAIL_OTP_RE.search(combined))
    )


def _is_mfa_required(status: int, payload: dict[str, Any]) -> bool:
    detail = str(payload.get("detail") or "")
    error_code = str(payload.get("error_code") or "")
    combined = f"{detail} {error_code}"
    return error_code == "MFA_REQUIRED" or (
        status == 403 and bool(_MFA_RE.search(combined))
    )


async def login_with_current_auth(
    email: str,
    password: str,
    *,
    email_otp: Optional[str] = None,
    mfa_code: Optional[str] = None,
) -> MonarchMoney:
    """Log in using Monarch's current host and email-OTP-aware payload."""
    client = create_monarch_client()
    payload = build_login_payload(
        email,
        password,
        email_otp=email_otp,
        mfa_code=mfa_code,
    )

    async with ClientSession(headers=client._headers) as session:
        async with session.post(
            MonarchMoneyEndpoints.getLoginEndpoint(), json=payload
        ) as response:
            body_text = await response.text()
            try:
                body = json.loads(body_text) if body_text else {}
            except json.JSONDecodeError:
                body = {"detail": body_text}

            if response.status != 200:
                if is_email_otp_required(response.status, body):
                    raise EmailOtpRequiredException(EMAIL_OTP_REQUIRED_MESSAGE)
                if _is_mfa_required(response.status, body):
                    raise RequireMFAException("Multi-Factor Auth Required")
                message = (
                    body.get("detail")
                    or body.get("error_code")
                    or f"HTTP Code {response.status}: {response.reason}"
                )
                raise LoginFailedException(str(message))

            token = body.get("token")
            if not token:
                raise LoginFailedException("Login response did not include a token")

            client.set_token(token)
            client._headers["Authorization"] = f"Token {token}"
            return client
