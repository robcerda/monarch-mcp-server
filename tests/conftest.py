"""Core fixtures for Monarch Money MCP Server tests.

Two-tier mocking convention:

  Tool-level tests (test_accounts, test_transactions_read, …):
    Only 3rd-party code is mocked via the autouse fixtures below:
      1. keyring           -> patched in secure_session to return fake tokens
      2. MonarchMoney class -> patched in secure_session; constructor returns AsyncMock
      3. trigger_auth_flow  -> patched in server to prevent browser opening

    Tests invoke tools through a ``fastmcp.Client`` connected to the MCP
    server (``mcp_client`` / ``mcp_write_client`` fixtures), exercising the
    full MCP protocol layer.

  Infrastructure tests (test_secure_session, test_auth_handler, test_server_edge_cases):
    Pragmatic internal mocks are allowed where needed — e.g. patching
    _run_sync, _send_json, secure_session, mcp.run, or using tmp_path for
    filesystem cleanup.  These tests manage their own patches and may
    override the autouse fixtures when exercising alternate code paths.
"""

from unittest.mock import patch, AsyncMock  # pylint: disable=unused-import

import pytest
from fastmcp import Client

from monarch_mcp.server import mcp

WRITE_TOOL_NAMES = frozenset({
    "create_transaction", "update_transaction", "delete_transaction",
    "create_transaction_tag", "delete_transaction_tag", "set_transaction_tags",
    "set_budget_amount", "update_transaction_splits",
    "create_transaction_category", "delete_transaction_category",
    "create_manual_account", "update_account", "delete_account",
    "create_transaction_rule",
})


@pytest.fixture
def mock_monarch_client():
    """Patches keyring + MonarchMoney constructor.  Yields AsyncMock client."""
    with (
        patch("monarch_mcp.secure_session.keyring") as mock_kr,
        patch("monarch_mcp.secure_session.MonarchMoney") as mock_cls,
    ):
        mock_kr.get_password.return_value = "fake-token"
        client = AsyncMock()
        client.token = "fake-token"
        mock_cls.return_value = client
        yield client


@pytest.fixture(autouse=True)
def _isolate(mock_monarch_client, monkeypatch):  # pylint: disable=redefined-outer-name,unused-argument
    """Autouse: every test gets mock client, no browser auth, no env leaks."""
    monkeypatch.delenv("MONARCH_EMAIL", raising=False)
    monkeypatch.delenv("MONARCH_PASSWORD", raising=False)
    with patch("monarch_mcp.server.trigger_auth_flow"):
        yield


@pytest.fixture
async def mcp_client():
    """Client connected to the MCP server for read-only tool tests."""
    async with Client(mcp) as client:
        yield client


@pytest.fixture
async def mcp_write_client():
    """Client with write tools temporarily enabled."""
    tools = await mcp.get_tools()
    disabled = []
    for name in WRITE_TOOL_NAMES:
        tool = tools.get(name)
        if tool and not tool.enabled:
            tool.enabled = True
            disabled.append(tool)
    try:
        async with Client(mcp) as client:
            yield client
    finally:
        for tool in disabled:
            tool.enabled = False
