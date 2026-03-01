"""
Secure session management for Monarch Money MCP Server using keyring.
"""

import keyring
import logging
import os
from typing import Optional
from monarch_mcp_server.monarchmoney import MonarchMoney

logger = logging.getLogger(__name__)

# Keyring service identifiers
KEYRING_SERVICE = "com.mcp.monarch-mcp-server"
KEYRING_USERNAME = "monarch-token"


class SecureMonarchSession:
    """Manages Monarch Money sessions securely using the system keyring."""

    def save_token(self, token: str) -> None:
        """Save the authentication token to the system keyring."""
        try:
            keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, token)
            logger.info("✅ Token saved securely to keyring")

            # Clean up any old insecure files
            self._cleanup_old_session_files()

        except Exception as e:
            logger.error(f"❌ Failed to save token to keyring: {e}")
            raise

    def load_token(self) -> Optional[str]:
        """Load the authentication token from the system keyring."""
        try:
            token = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
            if token:
                logger.info("✅ Token loaded from keyring")
                return token
            else:
                logger.info("🔍 No token found in keyring")
                return None
        except Exception as e:
            logger.error(f"❌ Failed to load token from keyring: {e}")
            return None

    def delete_token(self) -> None:
        """Delete the authentication token from the system keyring."""
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
            logger.info("🗑️ Token deleted from keyring")

            # Also clean up any old insecure files
            self._cleanup_old_session_files()

        except keyring.errors.PasswordDeleteError:
            logger.info("🔍 No token found in keyring to delete")
        except Exception as e:
            logger.error(f"❌ Failed to delete token from keyring: {e}")

    def get_authenticated_client(self) -> Optional[MonarchMoney]:
        """Get an authenticated MonarchMoney client."""
        token = self.load_token()
        if not token:
            return None

        try:
            client = MonarchMoney(token=token)
            logger.info("✅ MonarchMoney client created with stored token")
            return client
        except Exception as e:
            logger.error(f"❌ Failed to create MonarchMoney client: {e}")
            return None

    def save_authenticated_session(self, mm: MonarchMoney) -> None:
        """Save the session from an authenticated MonarchMoney instance."""
        if mm.token:
            self.save_token(mm.token)
        else:
            logger.warning("⚠️  MonarchMoney instance has no token to save")

    def _cleanup_old_session_files(self) -> None:
        """Clean up old insecure session files."""
        cleanup_paths = [
            ".mm/mm_session.pickle",
            "monarch_session.json",
            ".mm",  # Remove the entire directory if empty
        ]

        for path in cleanup_paths:
            try:
                if os.path.exists(path):
                    if os.path.isfile(path):
                        os.remove(path)
                        logger.info(f"🗑️ Cleaned up old insecure session file: {path}")
                    elif os.path.isdir(path) and not os.listdir(path):
                        os.rmdir(path)
                        logger.info(f"🗑️ Cleaned up empty session directory: {path}")
            except Exception as e:
                logger.warning(f"⚠️  Could not clean up {path}: {e}")


# Global session manager instance
secure_session = SecureMonarchSession()
