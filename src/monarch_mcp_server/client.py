"""Cached MonarchMoney client factory."""

import logging
from typing import Optional

from monarchmoney import MonarchMoney

from monarch_mcp_server.monarch_auth import configure_monarchmoney
from monarch_mcp_server.secure_session import secure_session

logger = logging.getLogger(__name__)

# Point the upstream package at Monarch's current API host.
configure_monarchmoney()

# Module-level client cache
_cached_client: Optional[MonarchMoney] = None


def clear_client_cache() -> None:
    """Clear the cached client. Call after re-authentication."""
    global _cached_client
    _cached_client = None
    logger.info("Client cache cleared")


async def get_monarch_client() -> MonarchMoney:
    """Get or create a cached MonarchMoney client using secure session storage.

    Authentication is established only via ``login_setup.py`` (or the
    elicitation login tools), which save a session to the system keyring. MCP
    tool calls never initiate a noninteractive password login, so a stray set
    of environment credentials cannot trigger an unattended sign-in.
    """
    global _cached_client

    if _cached_client is not None:
        return _cached_client

    client = secure_session.get_authenticated_client()

    if client is not None:
        logger.info("Using authenticated client from secure keyring storage")
        _cached_client = client
        return client

    raise RuntimeError("Authentication needed! Run: python login_setup.py")
