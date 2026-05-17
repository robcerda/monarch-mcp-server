"""Authentication tools."""

import logging
import os

from mcp.server.fastmcp import Context

from monarch_mcp_server import auth
from monarch_mcp_server.app import mcp
from monarch_mcp_server.secure_session import secure_session

logger = logging.getLogger(__name__)


@mcp.tool()
async def setup_authentication() -> str:
    """Get instructions for setting up secure authentication with Monarch Money."""
    return """🔐 Monarch Money - Authentication Options

⚠️ As of May 2026, Monarch's API rejects the legacy Token header. Use the
   cookie flow below. Email/password and token-paste flows are kept for
   when upstream restores Token support but currently won't authenticate.

Option 1: Cookie login (Recommended — works today)
   Call 'monarch_login_with_cookies'. From browser DevTools → Application
   → Cookies → https://app.monarch.com, copy the Value of 'session_id'
   (HttpOnly) and 'csrftoken', then paste into the form.

Option 2: Email/Password (likely broken until upstream patch)
   Call 'monarch_login' or run: python login_setup.py

Call 'monarch_logout' to clear the stored session.

✅ Session persists across restarts
✅ Credentials stored securely in system keyring"""


@mcp.tool()
async def monarch_login(ctx: Context) -> str:
    """Sign in to Monarch Money.

    Opens a secure form in the client UI to collect email, password, and
    (if required) an MFA code. Credentials never pass through the model —
    they flow client-UI → server directly via the MCP protocol.
    """
    return await auth.login_interactive(ctx)


@mcp.tool()
async def monarch_login_with_token(ctx: Context) -> str:
    """Sign in to Monarch Money using a browser-copied session token.

    Note: As of May 2026 Monarch's API rejects Token-header auth, so this
    flow will not currently authenticate. Use `monarch_login_with_cookies`
    instead. This tool stays for forward compatibility once upstream
    restores token support.
    """
    return await auth.login_with_token_interactive(ctx)


@mcp.tool()
async def monarch_login_with_cookies(ctx: Context) -> str:
    """Sign in to Monarch Money using browser session cookies.

    Monarch's web app authenticates via two cookies on app.monarch.com:
    `session_id` (HttpOnly) and `csrftoken`. Open DevTools → Application →
    Cookies → https://app.monarch.com and copy the Value of each, then
    paste them into the form this tool opens.
    """
    return await auth.login_with_cookies_interactive(ctx)


@mcp.tool()
async def monarch_logout() -> str:
    """Clear the stored Monarch Money session from the system keyring."""
    return await auth.logout()


@mcp.tool()
async def check_auth_status() -> str:
    """Check if already authenticated with Monarch Money."""
    try:
        cookies = secure_session.load_cookies()
        token = secure_session.load_token()
        if cookies:
            status = "✅ Session cookies found in secure keyring storage\n"
        elif token:
            status = (
                "⚠️ Only legacy token found — Monarch's API currently rejects "
                "Token-header auth. Call monarch_login_with_cookies to switch.\n"
            )
        else:
            status = "❌ No session credentials found in keyring\n"

        email = os.getenv("MONARCH_EMAIL")
        if email:
            status += f"📧 Environment email: {email}\n"

        status += (
            "\n💡 Try get_accounts to test the connection, or call "
            "monarch_login_with_cookies to authenticate."
        )

        return status
    except Exception as e:
        return f"Error checking auth status: {str(e)}"


@mcp.tool()
async def debug_session_loading() -> str:
    """Debug keyring session loading issues."""
    try:
        token = secure_session.load_token()
        if token:
            return "✅ Token found in keyring."
        return "❌ No token found in keyring. Run login_setup.py to authenticate."
    except Exception as e:
        logger.exception("Keyring access failed")
        return f"❌ Keyring access failed: {type(e).__name__}: {e}"
