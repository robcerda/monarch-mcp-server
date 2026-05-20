#!/usr/bin/env python3
"""
Standalone script to perform interactive Monarch Money login.

As of May 2026 Monarch's API requires session-cookie auth
(``session_id`` HttpOnly + ``csrftoken`` cookies, plus an ``x-csrftoken``
header). The cookie path is the only one that currently works. The legacy
email/password and session-token paths are kept for forward compatibility
but are clearly labeled as broken.

This script reads input directly from the terminal — no dotenv, no
environment-variable credentials, no MCP transport. It stores the
resulting cookies (or legacy token) in the system keyring; the MCP server
reads them on subsequent calls but never modifies them.
"""

import asyncio
import os
import getpass
import shutil
import sys
from pathlib import Path

# Add the src directory to the Python path for imports
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from monarchmoney import MonarchMoney, RequireMFAException

from monarch_mcp_server.cookie_auth import MonarchMoneyCookieAuth
from monarch_mcp_server.secure_session import secure_session


async def main():
    print("\n🏦 Monarch Money - Claude Desktop Setup")
    print("=" * 45)
    print("This will authenticate you once and save a session")
    print("for seamless access through Claude Desktop.\n")

    # Check the version first
    try:
        import monarchmoney
        print(
            f"📦 MonarchMoney version: "
            f"{getattr(monarchmoney, '__version__', 'unknown')}"
        )
    except Exception as e:
        print(f"⚠️  Could not check version: {e}")

    mm = MonarchMoney()

    try:
        # Clear any existing sessions (both old pickle files and keyring)
        secure_session.delete_token()
        print("🗑️ Cleared existing secure sessions")

        print("\nHow do you sign in to Monarch Money?")
        print(
            "  1) Session cookies from browser  "
            "(recommended — required since May 2026)"
        )
        print(
            "  2) Email and password            "
            "(currently broken — Monarch dropped Token auth)"
        )
        print(
            "  3) Legacy session token paste    "
            "(currently broken — see above)"
        )
        login_method = input("Choice [1]: ").strip() or "1"

        if login_method == "1":
            print("\n📋 To get your session cookies from the browser:")
            print("  1. Log in to https://app.monarch.com in Chrome/Firefox")
            print("  2. Open DevTools (F12) → Application tab → Cookies")
            print("     → https://app.monarch.com")
            print(
                "  3. Copy the Value of 'session_id' (HttpOnly) and "
                "'csrftoken'"
            )
            print(
                "\n⚠️  Do NOT paste these values into a Claude chat. The MCP "
                "server's monarch_login_with_token tool is disabled. Cookies "
                "are read here in your terminal only and stored in the local "
                "keyring."
            )
            session_id = getpass.getpass("\nPaste session_id value: ").strip()
            if not session_id:
                print("❌ No session_id provided. Exiting.")
                return
            csrftoken = getpass.getpass("Paste csrftoken value: ").strip()
            if not csrftoken:
                print("❌ No csrftoken provided. Exiting.")
                return
            mm = MonarchMoneyCookieAuth(
                session_id=session_id, csrftoken=csrftoken
            )
            print("✅ Cookies set")
        elif login_method == "3":
            print(
                "\n⚠️  WARNING: Monarch's API currently rejects "
                "Authorization: Token auth. This path is unlikely to work "
                "until upstream restores it. Use option 1 instead."
            )
            proceed = input("Continue anyway? (y/n): ").strip().lower()
            if proceed not in ("y", "yes"):
                print("Cancelled.")
                return
            print("\n📋 To get your session token from the browser:")
            print("  1. Log in to https://app.monarch.com in Chrome/Firefox")
            print("  2. Open DevTools (F12) → Application tab → Local Storage")
            print("     → https://app.monarch.com")
            print("  3. Copy the value for the key 'token'")
            token = getpass.getpass("\nPaste your session token: ").strip()
            if not token:
                print("❌ No token provided. Exiting.")
                return
            mm = MonarchMoney(token=token)
            print("✅ Token set (note: upstream API likely to reject it)")
        else:
            print(
                "\n⚠️  WARNING: Monarch's API currently rejects "
                "Authorization: Token auth, which is what email/password "
                "login produces. This path is unlikely to authenticate "
                "successfully until upstream restores Token support. Use "
                "option 1 (session cookies) instead."
            )
            proceed = input("Continue anyway? (y/n): ").strip().lower()
            if proceed not in ("y", "yes"):
                print("Cancelled.")
                return

            print("\n🔐 Security Check:")
            has_mfa = input(
                "Do you have MFA (Multi-Factor Authentication) enabled on "
                "your Monarch Money account? (y/n): "
            ).strip().lower()
            if has_mfa not in ("y", "yes"):
                print("\n⚠️  SECURITY RECOMMENDATION:")
                print("=" * 50)
                print(
                    "You should enable MFA for your Monarch Money account."
                )
                print(
                    "MFA adds an extra layer of security to protect your "
                    "financial data."
                )
                print("\nTo enable MFA:")
                print("1. Log into Monarch Money at https://monarchmoney.com")
                print("2. Go to Settings → Security")
                print("3. Enable Two-Factor Authentication")
                print("4. Follow the setup instructions\n")
                cont = input(
                    "Continue with login anyway? (y/n): "
                ).strip().lower()
                if cont not in ("y", "yes"):
                    print(
                        "Login cancelled. Please set up MFA and try again."
                    )
                    return

            email = input("Email: ")
            password = getpass.getpass("Password: ")

            try:
                await mm.login(
                    email,
                    password,
                    use_saved_session=False,
                    save_session=True,
                )
                print("✅ Login successful!")
            except RequireMFAException:
                print("🔐 MFA code required")
                mfa_code = input("Two Factor Code: ")
                await mm.multi_factor_authenticate(email, password, mfa_code)
                print("✅ MFA authentication successful")
                mm.save_session()  # Manually save the session

        # Test the connection
        print("\nTesting connection...")
        try:
            print("Calling get_accounts()...")
            accounts = await mm.get_accounts()
            print(f"Response received: {type(accounts)}")
            if accounts and isinstance(accounts, dict):
                account_count = len(accounts.get("accounts", []))
                print(f"✅ Found {account_count} accounts")
            else:
                print("❌ No accounts data returned or unexpected format")
                print(f"Response type: {type(accounts)}")
                print(f"Response content: {accounts}")
                return
        except Exception as test_error:
            print(f"❌ Connection test failed: {test_error}")
            print(f"Error type: {type(test_error)}")
            if (
                "session" in str(test_error).lower()
                or "expired" in str(test_error).lower()
                or "401" in str(test_error)
            ):
                print(
                    "\nThis usually means the session is expired or the "
                    "API rejected the auth method. If you used option 2 or "
                    "3, that is expected — Monarch's API currently requires "
                    "session-cookie auth. Re-run this script and choose "
                    "option 1 (session cookies)."
                )
            else:
                print(
                    "\nThis appears to be an API compatibility issue. The "
                    "MonarchMoney library API may have changed. Try "
                    "updating the library: "
                    "pip install --upgrade monarchmoneycommunity"
                )
            return

        # Save session securely to keyring
        try:
            print("\n🔐 Saving session securely to system keyring...")
            secure_session.save_authenticated_session(mm)
            print("✅ Session saved securely to keyring!")
        except Exception as save_error:
            print(f"❌ Could not save session to keyring: {save_error}")
            print("You may need to run the login again.")

        print(
            "\n🎉 Setup complete! You can now use these tools in Claude "
            "Desktop:"
        )
        print("   • get_accounts - View all your accounts")
        print("   • get_transactions - Recent transactions")
        print("   • get_budgets - Budget information")
        print("   • get_cashflow - Income/expense analysis")
        print("\n💡 Session will persist across Claude restarts!")

    except Exception as e:
        print(f"\n❌ Login failed: {e}")
        print("\nPlease check your credentials and try again.")
        print(f"Error type: {type(e)}")


if __name__ == "__main__":
    asyncio.run(main())
