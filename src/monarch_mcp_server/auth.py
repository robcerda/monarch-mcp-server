"""Interactive authentication for the Monarch Money MCP server.

Uses MCP elicitation so credentials flow client-UI → server directly over
the protocol — they never appear in tool arguments or the model's context.
"""

from __future__ import annotations

try:  # mcp >= 2.0
    from mcp.server.mcpserver import Context
except ImportError:  # mcp < 2.0
    from mcp.server.fastmcp import Context
from monarchmoney import MonarchMoney, RequireMFAException
from pydantic import BaseModel, Field

from monarch_mcp_server.client import clear_client_cache
from monarch_mcp_server.secure_session import secure_session


_UPGRADE_HINT = (
    "Elicitation requires the MCP Python SDK >= 1.10.0 (added in June 2025). "
    "Your MCP server install appears to be running an older version that does "
    "not expose Context.elicit. Upgrade the `mcp` package, then restart your "
    "MCP client. If you launch via `uv run --with mcp[cli]`, run `uv cache "
    "clean mcp` first so a fresh version is resolved. As a fallback, run "
    "`python login_setup.py` from the repo to authenticate via terminal."
)

_CLIENT_NO_ELICITATION = (
    "Your MCP client does not support the elicitation protocol "
    "(it returned -32601 Method not found). "
    "Use 'monarch_login_with_token' instead: open monarch.com in your browser, "
    "go to DevTools → Application → Local Storage → https://app.monarch.com, "
    "copy the 'token' value, and paste it when prompted."
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
            "Application → Local Storage for app.monarch.com, key 'token'."
        ),
    )


async def login_interactive(ctx: Context) -> str:
    if not _elicit_supported(ctx):
        return _UPGRADE_HINT
    try:
        form_result = await ctx.elicit(message="Sign in to Monarch Money.", schema=LoginForm)
    except Exception as e:
        if "Method not found" in str(e) or "-32601" in str(e):
            return _CLIENT_NO_ELICITATION
        raise
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
        try:
            mfa_result = await ctx.elicit(
                message="Enter your Monarch Money MFA code.", schema=MFAForm
            )
        except Exception as e:
            if "Method not found" in str(e) or "-32601" in str(e):
                return _CLIENT_NO_ELICITATION
            raise
        if mfa_result.action != "accept":
            return "Login cancelled."
        await mm.multi_factor_authenticate(
            form.email, form.password, mfa_result.data.mfa_code
        )

    secure_session.save_authenticated_session(mm)
    # The module level client cache holds its own Authorization header and is
    # unaffected by what storage now contains. Without this, a re-login after a
    # session expires reports success while every subsequent call keeps using
    # the dead client, and the only fix is restarting the host process.
    clear_client_cache()
    return "Logged in. Session saved to system keyring."


async def login_with_token_interactive(ctx: Context) -> str:
    if not _elicit_supported(ctx):
        return _UPGRADE_HINT
    try:
        form_result = await ctx.elicit(
            message="Paste your Monarch Money session token.", schema=TokenForm
        )
    except Exception as e:
        if "Method not found" in str(e) or "-32601" in str(e):
            return _CLIENT_NO_ELICITATION
        raise
    if form_result.action != "accept":
        return "Login cancelled."

    token = form_result.data.token.strip()
    if not token:
        return "Empty token — aborting."

    mm = MonarchMoney(token=token)
    await mm.get_subscription_details()
    secure_session.save_token(token)
    clear_client_cache()
    return "Session token saved to system keyring."


async def logout() -> str:
    secure_session.delete_token()
    # Deleting the stored session is not enough. A cached client keeps its own
    # Authorization header, so without dropping the cache every tool call after
    # a logout still returns live financial data for the life of the process.
    clear_client_cache()
    return "Cleared stored Monarch session."
