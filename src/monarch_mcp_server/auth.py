"""Interactive authentication for the Monarch Money MCP server.

Uses MCP elicitation so credentials flow client-UI → server directly over
the protocol — they never appear in tool arguments or the model's context.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context
from monarchmoney import MonarchMoney, RequireMFAException
from pydantic import BaseModel, Field

from monarch_mcp_server.cookie_auth import MonarchMoneyCookieAuth
from monarch_mcp_server.secure_session import secure_session


_UPGRADE_HINT = (
    "Elicitation requires the MCP Python SDK >= 1.10.0 (added in June 2025). "
    "Your MCP server install appears to be running an older version that does "
    "not expose Context.elicit. Upgrade the `mcp` package, then restart your "
    "MCP client. If you launch via `uv run --with mcp[cli]`, run `uv cache "
    "clean mcp` first so a fresh version is resolved. As a fallback, run "
    "`python login_setup.py` from the repo to authenticate via terminal."
)


def _elicit_supported(ctx: Context) -> bool:
    return hasattr(ctx, "elicit")


class LoginForm(BaseModel):
    email: str = Field(description="Monarch Money email address")
    password: str = Field(description="Monarch Money password")


class MFAForm(BaseModel):
    mfa_code: str = Field(description="Monarch Money MFA code")


class TokenForm(BaseModel):
    token: str = Field(
        description=(
            "Monarch Money session token. Grab it from browser DevTools → "
            "Application → Local Storage for app.monarchmoney.com, key 'token'."
        ),
    )


class CookiesForm(BaseModel):
    session_id: str = Field(
        description=(
            "Monarch session_id cookie (HttpOnly). DevTools → Application → "
            "Cookies → https://app.monarch.com → row 'session_id', copy Value."
        ),
    )
    csrftoken: str = Field(
        description=(
            "Monarch csrftoken cookie. Same Cookies pane, row 'csrftoken', "
            "copy Value."
        ),
    )


async def login_interactive(ctx: Context) -> str:
    if not _elicit_supported(ctx):
        return _UPGRADE_HINT
    form_result = await ctx.elicit(message="Sign in to Monarch Money.", schema=LoginForm)
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
        mfa_result = await ctx.elicit(
            message="Enter your Monarch Money MFA code.", schema=MFAForm
        )
        if mfa_result.action != "accept":
            return "Login cancelled."
        await mm.multi_factor_authenticate(
            form.email, form.password, mfa_result.data.mfa_code
        )

    secure_session.save_authenticated_session(mm)
    return "Logged in. Session saved to system keyring."


async def login_with_token_interactive(ctx: Context) -> str:
    if not _elicit_supported(ctx):
        return _UPGRADE_HINT
    form_result = await ctx.elicit(
        message="Paste your Monarch Money session token.", schema=TokenForm
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


async def login_with_cookies_interactive(ctx: Context) -> str:
    if not _elicit_supported(ctx):
        return _UPGRADE_HINT
    form_result = await ctx.elicit(
        message=(
            "Paste your Monarch session cookies. From DevTools → Application "
            "→ Cookies → https://app.monarch.com, copy the Value of "
            "'session_id' (HttpOnly) and 'csrftoken'."
        ),
        schema=CookiesForm,
    )
    if form_result.action != "accept":
        return "Login cancelled."

    sid = form_result.data.session_id.strip()
    csrf = form_result.data.csrftoken.strip()
    if not sid or not csrf:
        return "Empty cookie value — aborting."

    mm = MonarchMoneyCookieAuth(session_id=sid, csrftoken=csrf)
    await mm.get_subscription_details()
    secure_session.save_cookies(sid, csrf)
    return "Session cookies saved to system keyring."


async def logout() -> str:
    secure_session.delete_token()
    return "Cleared stored Monarch session."
