#!/usr/bin/env python3
"""
Standalone script to perform interactive Monarch Money login with MFA support.
Run this script to authenticate and save a session file that the MCP server can use.
"""

import asyncio
import os
import getpass
import shutil
import inspect
import traceback
import sys
from pathlib import Path

# Add the src directory to the Python path for imports
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from monarch_mcp_server.monarchmoney import MonarchMoney, RequireMFAException
from dotenv import load_dotenv
from monarch_mcp_server.secure_session import secure_session

async def main():
    load_dotenv()

    print("\n🏦 Monarch Money - Claude Desktop Setup")
    print("=" * 45)
    print("This will authenticate you once and save a session")
    print("for seamless access through Claude Desktop.\n")
    
    mm = MonarchMoney()
    
    try:
        # Clear any existing sessions (both old pickle files and keyring)
        secure_session.delete_token()
        print("🗑️ Cleared existing secure sessions")
        
        # Ask about MFA setup
        print("\n🔐 Security Check:")
        has_mfa = input("Do you have MFA (Multi-Factor Authentication) enabled on your Monarch Money account? (y/n): ").strip().lower()
        
        if has_mfa not in ['y', 'yes']:
            print("\n⚠️  SECURITY RECOMMENDATION:")
            print("=" * 50)
            print("You should enable MFA for your Monarch Money account.")
            print("MFA adds an extra layer of security to protect your financial data.")
            print("\nTo enable MFA:")
            print("1. Log into Monarch Money at https://monarchmoney.com")
            print("2. Go to Settings → Security")
            print("3. Enable Two-Factor Authentication")
            print("4. Follow the setup instructions\n")
            
            proceed = input("Continue with login anyway? (y/n): ").strip().lower()
            if proceed not in ['y', 'yes']:
                print("Login cancelled. Please set up MFA and try again.")
                return
        
        print("\nStarting login...")
        email = input("Email: ")
        password = getpass.getpass("Password: ")
        
        # Try login without MFA first
        try:
            await mm.login(email, password, use_saved_session=False, save_session=True)
            print("✅ Login successful!")
                
        except RequireMFAException:
            print("🔐 MFA code required")
            mfa_code = input("Two Factor Code: ")
            
            # Use the same instance for MFA
            await mm.multi_factor_authenticate(email, password, mfa_code)
            print("✅ MFA authentication successful")
            mm.save_session()  # Manually save the session
        
        # Test the connection first
        print("\nTesting connection...")
        try:
            # Try a simple test call that should work
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
            
            # Check if it's a session issue
            if "session" in str(test_error).lower() or "expired" in str(test_error).lower():
                print("Session may be expired. Clearing old session and trying fresh login...")
                
                # Clear old session and try fresh login
                if os.path.exists(".mm"):
                    shutil.rmtree(".mm")
                    print("🗑️ Cleared expired session files")
                
                # Try fresh login
                mm_fresh = MonarchMoney()
                try:
                    await mm_fresh.login(email, password)
                    print("✅ Fresh login successful (no MFA required)")
                    mm = mm_fresh
                    
                    # Test connection again
                    accounts = await mm.get_accounts()
                    if accounts and isinstance(accounts, dict):
                        account_count = len(accounts.get("accounts", []))
                        print(f"✅ Found {account_count} accounts")
                    
                except RequireMFAException:
                    print("🔐 MFA required for fresh login")
                    mfa_code = input("Two Factor Code: ")
                    
                    mm_mfa_fresh = MonarchMoney()
                    await mm_mfa_fresh.multi_factor_authenticate(email, password, mfa_code)
                    print("✅ Fresh MFA authentication successful")
                    mm = mm_mfa_fresh
                    
                    # Test connection again
                    accounts = await mm.get_accounts()
                    if accounts and isinstance(accounts, dict):
                        account_count = len(accounts.get("accounts", []))
                        print(f"✅ Found {account_count} accounts")
            else:
                print("This appears to be an API compatibility issue.")
                print("The MonarchMoney library API may have changed.")
                print("Try updating the library: pip install --upgrade monarchmoney")
                return
        
        # Save session securely to keyring
        try:
            print(f"\n🔐 Saving session securely to system keyring...")
            secure_session.save_authenticated_session(mm)
            print(f"✅ Session saved securely to keyring!")
                
        except Exception as save_error:
            print(f"❌ Could not save session to keyring: {save_error}")
            print("You may need to run the login again.")
        
        print("\n🎉 Setup complete! You can now use these tools in Claude Desktop:")
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