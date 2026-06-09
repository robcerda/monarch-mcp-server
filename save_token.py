#!/usr/bin/env python3
"""Quick token-based login — pass your token as a command-line argument."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from monarchmoney import MonarchMoney
from monarch_mcp_server.secure_session import secure_session

async def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python save_token.py YOUR_TOKEN_HERE")
        sys.exit(1)
    token = sys.argv[1].strip()
    mm = MonarchMoney(token=token)
    print("Testing connection...")
    accounts = await mm.get_accounts()
    count = len(accounts.get("accounts", []))
    print(f"✅ Connected! Found {count} accounts.")
    secure_session.save_authenticated_session(mm)
    print("✅ Session saved to keyring. You're all set!")

asyncio.run(main())
