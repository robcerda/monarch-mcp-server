"""Interactive authentication for the Monarch Money MCP server.

Uses MCP elicitation to collect credentials from the MCP client so they
never pass through the model's tool-argument context. The credentials
flow client-UI → server directly over the protocol; the model sees only
the returned status string.
"""

from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import Context
from monarchmoney import MonarchMoney, RequireMFAException
from pydantic import BaseModel, Field

from monarch_mcp_server.secure_session import secure_session


class LoginForm(BaseModel):
    email: str = Field(description="Monarch Money email address")
    password: str = Field(
        description="Monarch Money password",
        json_schema_extra={"format": "password"},
    )
    mfa_code: Optional[str] = Field(
        default=None,
        description="Optional MFA code if you have two-factor auth enabled",
    )


class MFAForm(BaseModel):
    mfa_code: str = Field(description="Monarch Money MFA code")


class TokenForm(BaseModel):
    token: str = Field(
        description=(
            "Monarch Money session token. Grab it in browser DevTools → "
            "Application → Local Storage → app.monarchmoney.com, key 'token'."
        ),
        json_schema_extra={"format": "password"},
    )


async def login_interactive(ctx: Context) -> str:
    form_result = await ctx.elicit(
        message="Sign in to Monarch Money.",
        schema=LoginForm,
    )
    if form_result.action != "accept":
        return "Login cancelled."
    form = form_result.data

    mm = MonarchMoney()
    try:
        await mm.login(
            form.email,
            form.password,
            use_saved_session=False,
            save_session=False,
        )
    except RequireMFAException:
        code = form.mfa_code
        if not code:
            mfa_result = await ctx.elicit(
                message="Enter your Monarch Money MFA code.",
                schema=MFAForm,
            )
            if mfa_result.action != "accept":
                return "Login cancelled."
            code = mfa_result.data.mfa_code
        await mm.multi_factor_authenticate(form.email, form.password, code)

    secure_session.save_authenticated_session(mm)
    return "Logged in. Session saved to system keyring."


async def login_with_token_interactive(ctx: Context) -> str:
    form_result = await ctx.elicit(
        message="Paste your Monarch Money session token.",
        schema=TokenForm,
    )
    if form_result.action != "accept":
        return "Login cancelled."

    token = form_result.data.token.strip()
    if not token:
        return "Empty token — aborting."

    mm = MonarchMoney(token=token)
    await mm.get_subscription_details()
    secure_session.save_token(token)
    return "Session token saved to system keyring."


async def logout() -> str:
    secure_session.delete_token()
    return "Cleared stored Monarch session."
