#!/usr/bin/env python3
"""
Standalone script to perform interactive Monarch Money login.

Supports three auth paths in order of recommendation:

1. Session cookies pasted from a logged-in browser. Long-lived, works
   for all account types including SSO, sidesteps Cloudflare CAPTCHA.
2. Email and password (with optional email OTP and MFA prompts). Now
   requests a long-lived session token from Monarch.
3. Legacy session token paste. Kept for users with a working token
   captured under the old auth model.
"""

import asyncio
import getpass
import os
import sys
from pathlib import Path

src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))


def _use_utf8_console() -> None:
    """Stop the script dying on its own output.

    Every prompt and status line here contains emoji. On Windows the console
    defaults to the locale code page (cp1252 on most installs), which cannot
    encode them, so the first print() raises UnicodeEncodeError and the script
    exits before the user reaches the menu -- with an encoding traceback that
    says nothing about logging in. errors="replace" keeps that from ever being
    fatal again on a terminal that still cannot render a character.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


_use_utf8_console()

from monarchmoney import CaptchaRequiredException, RequireMFAException
from monarch_mcp_server.monarch_auth import (
    EmailOtpRequiredException,
    create_monarch_client,
    login_with_browser_cookies,
    login_with_current_auth,
)
from monarch_mcp_server.secure_session import secure_session


def _default_cookie_file() -> Path:
    """Resolve the cookie file path for the current platform.

    Override with the MONARCH_MCP_COOKIE_FILE environment variable.
    Defaults: %APPDATA%\\monarch-mcp\\cookie.txt on Windows,
    $XDG_CONFIG_HOME/monarch-mcp/cookie.txt (or ~/.config/...) elsewhere.
    """
    override = os.environ.get("MONARCH_MCP_COOKIE_FILE")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        base_path = Path(base) if base else Path.home() / "AppData" / "Roaming"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base_path = Path(xdg) if xdg else Path.home() / ".config"
    return base_path / "monarch-mcp" / "cookie.txt"


COOKIE_FILE = _default_cookie_file()


def _read_cookie_string() -> str:
    """Return the browser cookie string for login.

    Preferred source is COOKIE_FILE. On POSIX terminals, interactive
    pastes via getpass()/input() are silently truncated at the tty's
    canonical-mode input buffer (MAX_CANON, 1024 bytes on macOS/Linux),
    and real Monarch cookie headers routinely exceed that, so pasting at
    a prompt fails in a confusing way. The file path works identically on
    Windows, macOS, and Linux and has no length limit.
    """
    if COOKIE_FILE.is_file():
        cookie = COOKIE_FILE.read_text(encoding="utf-8").strip()
        if cookie:
            print(f"🔑 Using cookie from {COOKIE_FILE}")
            return cookie
    print(f"(No cookie file found at {COOKIE_FILE})")
    print("⚠️  On macOS/Linux, terminal pastes longer than ~1024 chars are")
    print("    silently truncated. If login fails below, save the cookie to")
    print("    the file above and re-run this script (restrict permissions:")
    print("    chmod 600 on macOS/Linux; on Windows the file inherits your")
    print("    user-profile ACLs).")
    return getpass.getpass("Paste the Cookie header value: ").strip()


async def _login_with_cookies():
    print("\n📋 To copy the right cookie string:")
    print("  1. Log in to https://app.monarch.com in Chrome or Firefox")
    print("  2. Open DevTools (F12) → Network tab")
    print("  3. Click any request whose Name starts with 'graphql'")
    print("     (or any request to api.monarch.com)")
    print("  4. Scroll to 'Request Headers' and find the 'cookie:' header")
    print("  5. Copy the full value (a long string of key=value; pairs)")
    print(f"  6. Save it to {COOKIE_FILE} (recommended),")
    print("     or paste it at the prompt below")
    print()
    cookie_string = _read_cookie_string()
    if not cookie_string:
        print("❌ No cookie string provided. Exiting.")
        return None
    try:
        mm = await login_with_browser_cookies(cookie_string)
        print("✅ Cookie login successful")
        return mm
    except Exception as e:
        print(f"❌ Cookie login failed: {e}")
        return None


async def _login_with_password():
    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    try:
        mm = await login_with_current_auth(email, password)
        print("✅ Login successful")
        return mm
    except CaptchaRequiredException as e:
        print(f"❌ {e}")
        print("Re-run this script and choose option 1 (session cookies).")
        return None
    except EmailOtpRequiredException:
        print("📧 Monarch sent a verification code to your email.")
        code = input("Email verification code: ").strip()
        if not code:
            print("❌ No code provided. Exiting.")
            return None
        try:
            mm = await login_with_current_auth(email, password, email_otp=code)
        except RequireMFAException:
            mfa_code = input("Two Factor Code: ").strip()
            mm = await login_with_current_auth(
                email, password, email_otp=code, mfa_code=mfa_code
            )
        print("✅ Email verification successful")
        return mm
    except RequireMFAException:
        mfa_code = input("Two Factor Code: ").strip()
        if not mfa_code:
            print("❌ No MFA code provided. Exiting.")
            return None
        mm = await login_with_current_auth(email, password, mfa_code=mfa_code)
        print("✅ MFA authentication successful")
        return mm


def _login_with_legacy_token():
    print("\n📋 To get a legacy session token:")
    print("  1. Log in to https://app.monarch.com in Chrome or Firefox")
    print("  2. DevTools (F12) → Application tab → Local Storage")
    print("     → https://app.monarch.com → key 'token'")
    print("  3. Copy the value")
    print()
    print(
        "⚠️  Monarch may no longer accept Authorization: Token auth on the "
        "GraphQL endpoint. If the test call below fails with 401, re-run "
        "this script and choose option 1 (cookies) instead."
    )
    token = getpass.getpass("Paste your session token: ").strip()
    if not token:
        print("❌ No token provided. Exiting.")
        return None
    mm = create_monarch_client(token=token)
    print("✅ Token configured")
    return mm


async def main():
    print("\n🏦 Monarch Money - Claude Desktop Setup")
    print("=" * 45)
    print("This will authenticate you once and save a session")
    print("for seamless access through Claude Desktop.\n")

    try:
        import monarchmoney
        print(
            f"📦 MonarchMoney version: "
            f"{getattr(monarchmoney, '__version__', 'unknown')}"
        )
    except Exception as e:
        print(f"⚠️  Could not check version: {e}")

    try:
        # The previous session is deliberately left in place until the new one
        # is verified and saved. Deleting it up front meant that a bad cookie
        # paste, a Cloudflare captcha, or a 401 on the connection test left the
        # user with no working session at all, worse off than before running
        # this script. save_authenticated_session already overwrites whatever
        # is stored, so nothing needs clearing first.
        print("\nHow do you sign in to Monarch Money?")
        print(
            "  1) Session cookies from browser   "
            "(recommended: long-lived, supports SSO)"
        )
        print("  2) Email and password")
        print("  3) Legacy session token paste")
        choice = input("Choice [1]: ").strip() or "1"

        mm = None
        if choice == "1":
            mm = await _login_with_cookies()
        elif choice == "2":
            mm = await _login_with_password()
        elif choice == "3":
            mm = _login_with_legacy_token()
        else:
            print(f"❌ Unrecognized choice: {choice!r}. Exiting.")
            return

        if mm is None:
            return

        print("\nTesting connection...")
        try:
            accounts = await mm.get_accounts()
            if accounts and isinstance(accounts, dict):
                account_count = len(accounts.get("accounts", []))
                print(f"✅ Found {account_count} accounts")
            else:
                print(f"❌ Unexpected accounts response: {type(accounts)}")
                return
        except Exception as test_error:
            print(f"❌ Connection test failed: {test_error}")
            print(f"Error type: {type(test_error).__name__}")
            print(
                "\nIf this looks like 401 Unauthorized, the cookie or token "
                "is invalid. Re-run this script."
            )
            return

        try:
            print("\n🔐 Saving session securely to system keyring...")
            secure_session.save_authenticated_session(mm)
            print("✅ Session saved")
        except Exception as save_error:
            print(f"❌ Could not save session: {save_error}")
            return

        print("\n🎉 Setup complete. Restart Claude Desktop to pick up the session.")
        print("\n💡 Useful tools in Claude:")
        print("   • get_accounts - View all your accounts")
        print("   • get_transactions - Recent transactions")
        print("   • get_budgets - Budget information")
        print("   • get_cashflow - Income/expense analysis")

    except Exception as e:
        print(f"\n❌ Login failed: {e}")
        print(f"Error type: {type(e).__name__}")


if __name__ == "__main__":
    asyncio.run(main())
