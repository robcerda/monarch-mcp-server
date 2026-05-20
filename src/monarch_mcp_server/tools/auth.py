"""Authentication tools.

The MCP server does not accept credentials. Login, token paste, and logout
flows are intentionally disabled here — they must be performed out-of-band
via ``python login_setup.py``. The remaining tools are strictly read-only
checks against the locally stored session.

As of May 2026 Monarch's API requires session-cookie auth (``session_id``
HttpOnly + ``csrftoken`` cookies plus an ``x-csrftoken`` header). The
legacy ``Authorization: Token`` flow is no longer accepted upstream, so
``check_auth_status`` warns when only a legacy token is stored.
"""

import logging
import os

from monarch_mcp_server.app import mcp
from monarch_mcp_server.read_only import auth_mutation_disabled
from monarch_mcp_server.secure_session import secure_session

logger = logging.getLogger(__name__)


@mcp.tool()
async def setup_authentication() -> str:
    """Get instructions for setting up secure authentication with Monarch Money."""
    return """🔐 Monarch Money - Authentication Setup

This MCP server does not accept credentials and cannot log you in.

To authenticate:
   Run in a terminal: python login_setup.py

⚠️ As of May 2026, Monarch's API requires session-cookie auth
   (session_id + csrftoken cookies). The terminal flow will prompt you to
   paste those cookies from your browser DevTools and store them in the
   system keyring. The legacy email/password and session-token paths are
   kept for forward compatibility but currently will NOT authenticate
   because upstream still ships the old Token-header flow.

The MCP server picks up the stored cookies (or legacy token) on next call
but never modifies them.

Once authenticated:
   ✅ Session persists across restarts
   ✅ Cookies stored securely in system keyring

Note: MCP-exposed login/logout/token-paste tools are intentionally disabled
to prevent credentials from flowing through MCP transport or being changed
remotely. Run login_setup.py to rotate credentials or clear the session."""


@mcp.tool()
async def monarch_login() -> str:
    """[DISABLED] Sign in to Monarch Money.

    This tool is intentionally disabled — the MCP server does not accept
    credentials. Run ``python login_setup.py`` from a terminal to log in.
    """
    return auth_mutation_disabled("monarch_login")


@mcp.tool()
async def monarch_login_with_token() -> str:
    """[DISABLED] Paste a Monarch Money session token.

    This tool is intentionally disabled. Run ``python login_setup.py`` from
    a terminal and paste session cookies (or, on the rare chance upstream
    restores Token-header auth, a legacy session token).
    """
    return auth_mutation_disabled("monarch_login_with_token")


@mcp.tool()
async def monarch_logout() -> str:
    """[DISABLED] Clear the stored Monarch Money session.

    This tool is intentionally disabled so that an MCP client cannot wipe a
    user's stored session. Clear the session out-of-band by deleting the
    keyring entry or by running ``python login_setup.py`` and replacing it.
    """
    return auth_mutation_disabled("monarch_logout")


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
                "⚠️ Only a legacy session token is stored — Monarch's API "
                "currently rejects Token-header auth (May 2026 change). "
                "Run `python login_setup.py` and choose the cookie option "
                "to switch to session-cookie auth.\n"
            )
        else:
            status = "❌ No authentication session found in keyring\n"

        # MONARCH_EMAIL is no longer used for auto-login, but surface it for
        # diagnostic clarity if an operator left it in their environment.
        email = os.getenv("MONARCH_EMAIL")
        if email:
            status += (
                f"📧 MONARCH_EMAIL is set in env ({email}) but is NOT used "
                "for auto-login. Ignored.\n"
            )

        status += (
            "\n💡 Try get_accounts to test the connection. If not "
            "authenticated, run login_setup.py from a terminal."
        )

        return status
    except Exception as e:
        return f"Error checking auth status: {str(e)}"


@mcp.tool()
async def debug_session_loading() -> str:
    """Debug keyring session loading issues."""
    try:
        cookies = secure_session.load_cookies()
        if cookies:
            return "✅ Session cookies found in keyring."
        token = secure_session.load_token()
        if token:
            return (
                "⚠️ Only a legacy token found in keyring. Monarch's API "
                "rejects Token-header auth as of May 2026. Run "
                "login_setup.py and switch to cookie auth."
            )
        return (
            "❌ No session found in keyring. Run login_setup.py to "
            "authenticate."
        )
    except Exception as e:
        logger.exception("Keyring access failed")
        return f"❌ Keyring access failed: {type(e).__name__}: {e}"
