#!/usr/bin/env python3
"""
Google OAuth Login for Monarch Money MCP Server

This script opens a browser window where you can sign in to Monarch Money
using your Google account. After successful login, it automatically
captures and saves the auth token.

Usage:
    python google_login.py
"""

import asyncio
import sys
import keyring
from playwright.async_api import async_playwright

# Keyring settings (same as secure_session.py)
KEYRING_SERVICE = "com.mcp.monarch-mcp-server"
KEYRING_USERNAME = "monarch-token"

# Monarch URLs
MONARCH_LOGIN_URL = "https://app.monarch.com/login"
MONARCH_APP_URL = "https://app.monarch.com"


async def capture_auth_token():
    """Open browser for Google login and capture the auth token."""

    print("🔐 Monarch Money - Google OAuth Login")
    print("=" * 50)
    print()
    print("A browser window will open. Please:")
    print("1. Click 'Sign in with Google'")
    print("2. Complete the Google authentication")
    print("3. Wait for the app to load")
    print()
    print("The token will be captured automatically.")
    print("=" * 50)
    print()

    captured_token = None

    async with async_playwright() as p:
        # Launch browser in non-headless mode so user can interact
        browser = await p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )

        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        page = await context.new_page()

        # Set up request interception to capture auth token
        async def handle_request(request):
            nonlocal captured_token
            auth_header = request.headers.get('authorization', '')
            if auth_header.startswith('Token ') and not captured_token:
                captured_token = auth_header.replace('Token ', '')
                print(f"✅ Auth token captured!")

        page.on('request', handle_request)

        # Navigate to Monarch login
        print("Opening Monarch login page...")
        await page.goto(MONARCH_LOGIN_URL)

        # Wait for user to complete login
        print("Waiting for login... (complete the Google OAuth in the browser)")
        print()

        try:
            # Wait for navigation to the main app (indicates successful login)
            # or wait for a GraphQL request with auth token
            max_wait = 300  # 5 minutes max
            wait_interval = 1
            waited = 0

            while not captured_token and waited < max_wait:
                await asyncio.sleep(wait_interval)
                waited += wait_interval

                # Check if we're on the main app page
                current_url = page.url
                if 'login' not in current_url and captured_token:
                    break

                # Show progress every 10 seconds
                if waited % 10 == 0 and waited > 0:
                    print(f"  Still waiting... ({waited}s)")

            if captured_token:
                print()
                print("=" * 50)
                print("✅ Login successful!")
                print(f"   Token: {captured_token[:20]}...{captured_token[-10:]}")
                print()

                # Save to keyring
                keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, captured_token)
                print("✅ Token saved to secure keyring storage")
                print()
                print("You can now close this browser window.")
                print("The MCP server will use this token automatically.")
                print("=" * 50)

                # Keep browser open briefly so user can see success
                await asyncio.sleep(3)
            else:
                print()
                print("❌ Timeout: No auth token captured")
                print("   Please try again or check your login.")

        except Exception as e:
            print(f"❌ Error during login: {e}")

        finally:
            await browser.close()

    return captured_token


def main():
    """Main entry point."""
    try:
        token = asyncio.run(capture_auth_token())
        if token:
            print()
            print("🎉 Setup complete! You can now use the Monarch MCP server.")
            sys.exit(0)
        else:
            print()
            print("❌ Setup failed. Please try again.")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(1)


if __name__ == "__main__":
    main()
