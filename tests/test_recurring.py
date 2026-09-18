"""Recurring regression coverage using synthetic data, never account credentials."""

import copy
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from graphql import print_ast

from monarch_mcp_server.tools import transactions


@pytest.fixture
def items():
    merchant = {
        "date": "2026-02-12",
        "amount": -15.0,
        "amountDiff": 0,
        "isPast": False,
        "transactionId": None,
        "account": {"id": "payment-account", "displayName": "Example Checking"},
        "category": {"id": "subscription-category", "name": "Subscriptions"},
        "stream": {
            "id": "merchant-stream",
            "name": "Example Subscription",
            "frequency": "monthly",
            "amount": -15.0,
            "isApproximate": False,
            "merchant": {"id": "merchant-id", "name": "Example Subscription"},
            "creditReportLiabilityAccount": None,
        },
    }
    bill = copy.deepcopy(merchant)
    bill.update(date="2026-02-14", amount=-250.0, category=None)
    bill["stream"] = {
        "id": "liability-stream",
        "name": "Example Card",
        "frequency": "monthly",
        "amount": -250.0,
        "isApproximate": False,
        "merchant": None,
        "creditReportLiabilityAccount": {
            "id": "liability-id",
            "account": {"id": "card-account", "displayName": "Example Card"},
            "lastStatement": {
                "id": "statement-id",
                "dueDate": "2026-02-18",
                "billAmount": "-250.00",
                "remainingBalance": -180.5,
                "minimumPaymentAmount": 0.0,
                "paymentStatus": "partially_paid",
            },
        },
    }
    return [merchant, bill]


@pytest.fixture
def client(items):
    client = AsyncMock()
    client.get_recurring_transactions.return_value = {
        "recurringTransactionItems": items[:1]
    }
    client.gql_call.return_value = {"recurringTransactionItems": items}
    with patch.object(transactions, "get_monarch_client", return_value=client):
        yield client


async def test_default_includes_synced_bills_with_statement_identity(client):
    rows = json.loads(await transactions.get_recurring_transactions())
    assert len(rows) == 2
    assert rows[0]["stream"]["merchant"] == "Example Subscription"
    assert rows[0]["account_id"] == "payment-account"
    assert rows[0]["category_id"] == "subscription-category"
    assert rows[0]["stream"]["merchant_id"] == "merchant-id"
    assert rows[1]["stream"]["merchant"] is None
    liability = rows[1]["stream"]["credit_report_liability_account"]
    assert liability["account_id"] == "card-account"
    assert liability["last_statement"] == {
        "id": "statement-id",
        "due_date": "2026-02-18",
        "bill_amount": "-250.00",
        "minimum_payment_amount": 0.0,
        "payment_status": "partially_paid",
        "remaining_balance": -180.5,
    }
    assert rows[1]["date"] == "2026-02-14"
    assert rows[1]["amount"] == -250.0
    kwargs = client.gql_call.call_args.kwargs
    assert kwargs["variables"]["includeLiabilities"] is True
    request = kwargs["graphql_query"]
    query = print_ast(getattr(request, "document", request))
    for field in ["includeLiabilities", "lastStatement", "remainingBalance", "dueDate"]:
        assert field in query


@pytest.mark.parametrize("balance", [None, 0.0, -7.25])
async def test_remaining_balance_is_not_replaced_by_forecast(client, items, balance):
    statement = items[1]["stream"]["creditReportLiabilityAccount"]["lastStatement"]
    statement["remainingBalance"] = balance
    rows = json.loads(await transactions.get_recurring_transactions())
    actual = rows[1]["stream"]["credit_report_liability_account"]["last_statement"]
    assert actual["remaining_balance"] == balance
    assert actual["bill_amount"] == "-250.00"


async def test_missing_statement_and_unmapped_account_remain_null(client, items):
    liability = items[1]["stream"]["creditReportLiabilityAccount"]
    liability.update(lastStatement=None, account=None)
    rows = json.loads(await transactions.get_recurring_transactions())
    actual = rows[1]["stream"]["credit_report_liability_account"]
    assert actual == {
        "id": "liability-id",
        "account_id": None,
        "account": None,
        "last_statement": None,
    }


async def test_opt_out_and_pagination_metadata(client, items):
    client.gql_call.return_value = {"recurringTransactionItems": items[:1]}
    result = json.loads(
        await transactions.get_recurring_transactions(
            "2026-02-01",
            "2026-02-28",
            include_liabilities=False,
            limit=1,
            offset=2,
            include_metadata=True,
        )
    )
    assert result["count"] == 1
    assert result["total_count"] is None
    assert result["truncated"] is True
    assert result["data"][0]["stream"]["merchant"] == "Example Subscription"
    assert client.gql_call.call_args.kwargs["variables"] == {
        "startDate": "2026-02-01",
        "endDate": "2026-02-28",
        "includeLiabilities": False,
        "limit": 1,
        "offset": 2,
    }


@pytest.mark.parametrize("count", [0, 1])
async def test_short_page_is_not_truncated(client, items, count):
    client.gql_call.return_value = {"recurringTransactionItems": items[:count]}
    result = json.loads(
        await transactions.get_recurring_transactions(
            "2026-02-01",
            "2026-02-28",
            limit=2,
            include_metadata=True,
        )
    )
    assert result["count"] == count
    assert result["truncated"] is False
    assert result["total_count"] is None


async def test_default_dates_are_current_calendar_month(client):
    with patch.object(transactions, "datetime", wraps=datetime) as clock:
        clock.now.return_value = datetime(2024, 2, 20, 12)
        await transactions.get_recurring_transactions()
    variables = client.gql_call.call_args.kwargs["variables"]
    assert variables["startDate"] == "2024-02-01"
    assert variables["endDate"] == "2024-02-29"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start_date": "2026-02-01"},
        {"end_date": "2026-02-28"},
        {"start_date": "2026-02-30", "end_date": "2026-03-01"},
        {"start_date": "2026-2-01", "end_date": "2026-02-28"},
        {"start_date": "", "end_date": ""},
        {"start_date": "2026-03-01", "end_date": "2026-02-28"},
        {"limit": 0},
        {"limit": -1},
        {"limit": True},
        {"limit": 1.5},
        {"offset": -1},
        {"offset": True},
        {"offset": 1.5},
    ],
)
async def test_invalid_arguments_return_error_without_request(client, kwargs):
    result = json.loads(await transactions.get_recurring_transactions(**kwargs))
    assert "error" in result
    client.gql_call.assert_not_called()


async def test_api_error_is_not_reported_as_empty_success(client):
    client.gql_call.side_effect = RuntimeError("Example API failure")
    result = json.loads(await transactions.get_recurring_transactions())
    assert "error" in result


async def test_null_optional_item_fields(client):
    client.gql_call.return_value = {
        "recurringTransactionItems": [
            {
                "date": "2026-02-12",
                "amount": -3,
                "stream": None,
                "category": None,
                "account": None,
            },
        ]
    }
    result = json.loads(await transactions.get_recurring_transactions())
    assert len(result) == 1
    assert result[0]["stream"] is None
    assert result[0]["account_id"] is None
    assert result[0]["category_id"] is None
