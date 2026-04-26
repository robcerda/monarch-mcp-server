"""Shared test fixtures for Monarch MCP Server tests."""

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Mock the monarchmoney module before any monarch_mcp_server imports
mm_mock = MagicMock()
mm_mock.MonarchMoney = MagicMock
mm_mock.RequireMFAException = Exception
sys.modules.setdefault("monarchmoney", mm_mock)
sys.modules.setdefault("monarchmoney.monarchmoney", MagicMock())

import pytest


@pytest.fixture
def mock_monarch_client():
    """Create a mock MonarchMoney client with default responses."""
    client = AsyncMock()

    client.get_accounts.return_value = {
        "accounts": [
            {
                "id": "acc-1",
                "displayName": "Checking Account",
                "name": "Checking",
                "type": {"name": "checking"},
                "currentBalance": 1500.00,
                "institution": {"name": "Test Bank"},
                "deactivatedAt": None,
                "isHidden": False,
            },
            {
                "id": "acc-2",
                "displayName": "Savings Account",
                "name": "Savings",
                "type": {"name": "savings"},
                "currentBalance": 10000.00,
                "institution": {"name": "Test Bank"},
                "deactivatedAt": None,
                "isHidden": True,
            },
        ]
    }

    client.get_transactions.return_value = {
        "allTransactions": {
            "results": [
                {
                    "id": "txn-1",
                    "date": "2026-03-01",
                    "amount": -42.50,
                    "description": "Grocery Store",
                    "category": {"id": "cat-1", "name": "Groceries"},
                    "account": {"id": "acc-1", "displayName": "Checking Account"},
                    "merchant": {"name": "Whole Foods"},
                    "isPending": False,
                    "needsReview": True,
                    "notes": "weekly groceries",
                    "isRecurring": False,
                    "reviewStatus": "needs_review",
                    "isSplitTransaction": False,
                    "hideFromReports": False,
                    "tags": [{"id": "tag-1", "name": "business"}],
                },
                {
                    "id": "txn-2",
                    "date": "2026-03-02",
                    "amount": 3000.00,
                    "description": "Paycheck",
                    "category": {"id": "cat-3", "name": "Income"},
                    "account": {"id": "acc-1", "displayName": "Checking Account"},
                    "merchant": None,
                    "isPending": False,
                    "needsReview": False,
                    "notes": None,
                    "isRecurring": True,
                    "reviewStatus": "reviewed",
                    "isSplitTransaction": False,
                    "hideFromReports": False,
                    "tags": [],
                },
            ]
        }
    }

    client.get_budgets.return_value = {
        "budgetData": {
            "monthlyAmountsByCategory": [
                {
                    "category": {"id": "cat-1", "name": "Groceries"},
                    "monthlyAmounts": [
                        {
                            "month": "2026-03-01",
                            "plannedCashFlowAmount": 500.00,
                            "actualCashFlowAmount": 320.00,
                        }
                    ],
                },
                {
                    "category": {"id": "cat-2", "name": "Dining Out"},
                    "monthlyAmounts": [
                        {
                            "month": "2026-03-01",
                            "plannedCashFlowAmount": 200.00,
                            "actualCashFlowAmount": 185.00,
                        }
                    ],
                },
            ]
        }
    }

    client.get_cashflow.return_value = {
        "cashflow": {
            "income": 5000.00,
            "expenses": -3200.00,
            "savings": 1800.00,
        }
    }

    client.get_account_holdings.return_value = {
        "holdings": [
            {
                "id": "hold-1",
                "name": "VTI",
                "quantity": 100,
                "value": 25000.00,
            }
        ]
    }

    client.create_transaction.return_value = {
        "createTransaction": {"transaction": {"id": "txn-new"}}
    }

    client.update_transaction.return_value = {
        "updateTransaction": {"transaction": {"id": "txn-1"}}
    }

    client.request_accounts_refresh.return_value = {
        "requestAccountsRefresh": {"success": True}
    }

    client.get_transaction_categories.return_value = {
        "categories": [
            {
                "id": "cat-1",
                "name": "Groceries",
                "icon": "🛒",
                "group": {"id": "grp-1", "name": "Food"},
            },
            {
                "id": "cat-2",
                "name": "Dining Out",
                "icon": "🍽️",
                "group": {"id": "grp-1", "name": "Food"},
            },
        ]
    }

    client.get_transaction_tags.return_value = {
        "householdTransactionTags": [
            {"id": "tag-1", "name": "business", "color": "#ff0000"},
            {"id": "tag-2", "name": "vacation", "color": "#00ff00"},
        ]
    }

    client.get_transaction_details.return_value = {
        "getTransaction": {
            "id": "txn-1",
            "tags": [{"id": "tag-1", "name": "business"}],
        }
    }

    client.set_transaction_tags.return_value = {
        "setTransactionTags": {"transaction": {"id": "txn-1"}}
    }

    client.get_transaction_category_groups.return_value = {
        "categoryGroups": [
            {"id": "grp-1", "name": "Food", "type": "expense"},
            {"id": "grp-2", "name": "Income", "type": "income"},
        ]
    }

    client.create_transaction_category.return_value = {
        "createCategory": {"category": {"id": "cat-new", "name": "Coffee"}}
    }

    client.create_transaction_tag.return_value = {
        "createTransactionTag": {"tag": {"id": "tag-new", "name": "new", "color": "#0000ff"}}
    }

    return client


_TOOL_MODULES = [
    "monarch_mcp_server.client",
    "monarch_mcp_server.tools.auth",
    "monarch_mcp_server.tools.accounts",
    "monarch_mcp_server.tools.transactions",
    "monarch_mcp_server.tools.summaries",
    "monarch_mcp_server.tools.splits",
    "monarch_mcp_server.tools.tags",
    "monarch_mcp_server.tools.rules",
    "monarch_mcp_server.tools.categories",
    "monarch_mcp_server.tools.budgets",
    "monarch_mcp_server.tools.financial",
]


@pytest.fixture(autouse=True)
def patch_monarch_client(mock_monarch_client):
    """Automatically patch get_monarch_client wherever it's imported."""
    patchers = []
    for module_path in _TOOL_MODULES:
        try:
            p = patch(
                f"{module_path}.get_monarch_client",
                new_callable=AsyncMock,
                return_value=mock_monarch_client,
            )
            p.start()
            patchers.append(p)
        except (AttributeError, ModuleNotFoundError):
            pass
    try:
        yield mock_monarch_client
    finally:
        for p in patchers:
            p.stop()
