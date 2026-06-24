import asyncio

import pytest

from monarch_mcp_server import client as client_module

# Bind the real implementation at import time, before the autouse
# patch_monarch_client fixture replaces the module attribute with a mock.
from monarch_mcp_server.client import get_monarch_client as _real_get_monarch_client


def test_get_monarch_client_requires_saved_session(monkeypatch):
    """Without a saved keyring session, MCP calls must not attempt a login;
    they raise and point the user at login_setup.py."""
    client_module.clear_client_cache()
    monkeypatch.setattr(
        client_module.secure_session, "get_authenticated_client", lambda: None
    )

    with pytest.raises(RuntimeError, match="login_setup.py"):
        asyncio.run(_real_get_monarch_client())
