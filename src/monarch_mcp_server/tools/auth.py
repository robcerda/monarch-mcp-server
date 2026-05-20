"""Authentication tools.

The MCP server does not accept credentials. Login, token paste, and logout
flows are intentionally disabled here — they must be performed out-of-band
via ``python login_setup.py``. The remaining tools are strictly read-only
checks against the locally stored session.
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

The terminal flow will prompt for email/password (or a session token from
the browser), perform MFA if required, and store the resulting session
token in the system keyring. The MCP server will pick it up on next call.

Once authenticated:
   ✅ Session persists across restarts
   ✅ Token stored securely in system keyring

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
    a terminal and choose the token-paste option.
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
        token = secure_session.load_token()
        if token:
            status = "✅ Authentication token found in secure keyring storage\n"
        else:
            status = "❌ No authentication token found in keyring\n"

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
        token = secure_session.load_token()
        if token:
            return "✅ Token found in keyring."
        return "❌ No token found in keyring. Run login_setup.py to authenticate."
    except Exception as e:
        logger.exception("Keyring access failed")
        return f"❌ Keyring access failed: {type(e).__name__}: {e}"
