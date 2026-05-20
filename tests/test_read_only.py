"""Tests proving every mutation tool refuses to run in read-only mode.

The server defaults to read-only — these tests assert that the refusal
extends to every Monarch SDK mutation we expose, that read-only tools keep
working, and that the upstream client is never called when a refusal fires.
"""

import asyncio
import json
import os

import pytest

from monarch_mcp_server.read_only import (
    ENV_VAR,
    auth_mutation_disabled,
    is_read_only,
    read_only_refusal,
)
from monarch_mcp_server.tools.accounts import (
    get_accounts,
    refresh_accounts,
    upload_account_balance_history,
)
from monarch_mcp_server.tools.transactions import (
    bulk_categorize_transactions,
    categorize_transaction,
    create_transaction,
    delete_transaction,
    get_transactions,
    mark_transaction_reviewed,
    update_transaction,
    update_transaction_notes,
)
from monarch_mcp_server.tools.tags import (
    add_transaction_tag,
    create_transaction_tag,
    set_transaction_tags,
)
from monarch_mcp_server.tools.categories import create_transaction_category
from monarch_mcp_server.tools.splits import split_transaction
from monarch_mcp_server.tools.rules import (
    create_transaction_rule,
    delete_transaction_rule,
    update_transaction_rule,
)
from monarch_mcp_server.tools.budgets import set_budget_amount


@pytest.fixture
def read_only_env(monkeypatch):
    """Force read-only mode ON, overriding the conftest opt-out."""
    monkeypatch.setenv(ENV_VAR, "true")
    yield


class TestIsReadOnly:
    """The is_read_only() helper drives every refusal."""

    @pytest.mark.parametrize("value", ["true", "1", "yes", "on", "TRUE", "YES"])
    def test_truthy_values(self, monkeypatch, value):
        monkeypatch.setenv(ENV_VAR, value)
        assert is_read_only() is True

    @pytest.mark.parametrize(
        "value", ["false", "0", "no", "off", "FALSE", "NO", "Disabled"]
    )
    def test_falsey_values(self, monkeypatch, value):
        monkeypatch.setenv(ENV_VAR, value)
        assert is_read_only() is False

    def test_default_is_read_only_when_unset(self, monkeypatch):
        monkeypatch.delenv(ENV_VAR, raising=False)
        assert is_read_only() is True

    def test_default_is_read_only_when_empty_or_garbage(self, monkeypatch):
        # Empty / unknown strings should NOT silently turn off the guard.
        for value in ("", "maybe", "readonly"):
            monkeypatch.setenv(ENV_VAR, value)
            assert is_read_only() is True


def _assert_refused(payload_text, tool_name):
    payload = json.loads(payload_text)
    assert payload["read_only"] is True
    assert payload["tool"] == tool_name
    assert payload["success"] is False
    assert "MONARCH_MCP_READ_ONLY" in payload["error"]


class TestTransactionMutationsRefused:
    def test_create_transaction(self, read_only_env, mock_monarch_client):
        result = asyncio.run(
            create_transaction(
                date="2026-04-01",
                account_id="acc-1",
                amount=-10.0,
                merchant_name="Test",
                category_id="cat-1",
            )
        )
        _assert_refused(result, "create_transaction")
        mock_monarch_client.create_transaction.assert_not_called()

    def test_update_transaction(self, read_only_env, mock_monarch_client):
        result = asyncio.run(
            update_transaction(transaction_id="txn-1", notes="x")
        )
        _assert_refused(result, "update_transaction")
        mock_monarch_client.update_transaction.assert_not_called()

    def test_categorize_transaction(self, read_only_env, mock_monarch_client):
        result = asyncio.run(
            categorize_transaction(transaction_id="txn-1", category_id="cat-1")
        )
        _assert_refused(result, "categorize_transaction")
        mock_monarch_client.update_transaction.assert_not_called()

    def test_update_transaction_notes(self, read_only_env, mock_monarch_client):
        result = asyncio.run(
            update_transaction_notes(transaction_id="txn-1", notes="hi")
        )
        _assert_refused(result, "update_transaction_notes")
        mock_monarch_client.update_transaction.assert_not_called()

    def test_mark_transaction_reviewed(self, read_only_env, mock_monarch_client):
        result = asyncio.run(mark_transaction_reviewed(transaction_id="txn-1"))
        _assert_refused(result, "mark_transaction_reviewed")
        mock_monarch_client.update_transaction.assert_not_called()

    def test_delete_transaction(self, read_only_env, mock_monarch_client):
        result = asyncio.run(delete_transaction(transaction_id="txn-1"))
        _assert_refused(result, "delete_transaction")
        mock_monarch_client.delete_transaction.assert_not_called()

    def test_bulk_categorize_blocks_real_run(self, read_only_env, mock_monarch_client):
        result = asyncio.run(
            bulk_categorize_transactions(
                transaction_ids=["txn-1", "txn-2"],
                category_id="cat-1",
                dry_run=False,
            )
        )
        _assert_refused(result, "bulk_categorize_transactions")
        mock_monarch_client.update_transaction.assert_not_called()

    def test_bulk_categorize_dry_run_still_works(
        self, read_only_env, mock_monarch_client
    ):
        """Dry-run is read-only; it must NOT be blocked."""
        result = asyncio.run(
            bulk_categorize_transactions(
                transaction_ids=["txn-1"],
                category_id="cat-1",
                dry_run=True,
            )
        )
        payload = json.loads(result)
        assert payload["dry_run"] is True
        mock_monarch_client.update_transaction.assert_not_called()


class TestAccountMutationsRefused:
    def test_refresh_accounts(self, read_only_env, mock_monarch_client):
        result = asyncio.run(refresh_accounts())
        _assert_refused(result, "refresh_accounts")
        mock_monarch_client.request_accounts_refresh.assert_not_called()

    def test_upload_balance_history_blocks_real_run(
        self, read_only_env, mock_monarch_client
    ):
        result = asyncio.run(
            upload_account_balance_history(
                "12345", '{"2026-04-21": 500.0}', dry_run=False
            )
        )
        _assert_refused(result, "upload_account_balance_history")
        mock_monarch_client.upload_account_balance_history.assert_not_called()

    def test_upload_balance_history_dry_run_allowed(
        self, read_only_env, mock_monarch_client
    ):
        """Dry-run does not mutate remote state and remains usable."""
        result = asyncio.run(
            upload_account_balance_history(
                "12345", '{"2026-04-21": 500.0}', dry_run=True
            )
        )
        payload = json.loads(result)
        # The dry-run path either returns ``dry_run: True`` (when corrections
        # match snapshots) or a structured 'no matching dates' message; in
        # either case the underlying upload must NOT have been called.
        assert "dry_run" in payload or "unmatched_dates" in payload
        mock_monarch_client.upload_account_balance_history.assert_not_called()


class TestTagMutationsRefused:
    def test_set_transaction_tags(self, read_only_env, mock_monarch_client):
        result = asyncio.run(set_transaction_tags("txn-1", ["tag-1"]))
        _assert_refused(result, "set_transaction_tags")
        mock_monarch_client.set_transaction_tags.assert_not_called()

    def test_create_transaction_tag(self, read_only_env, mock_monarch_client):
        result = asyncio.run(create_transaction_tag("new", "#ff0000"))
        _assert_refused(result, "create_transaction_tag")
        mock_monarch_client.create_transaction_tag.assert_not_called()

    def test_add_transaction_tag(self, read_only_env, mock_monarch_client):
        result = asyncio.run(add_transaction_tag("txn-1", "tag-1"))
        _assert_refused(result, "add_transaction_tag")
        mock_monarch_client.set_transaction_tags.assert_not_called()


class TestCategoryMutationsRefused:
    def test_create_transaction_category(self, read_only_env, mock_monarch_client):
        result = asyncio.run(create_transaction_category("grp-1", "Coffee"))
        _assert_refused(result, "create_transaction_category")
        mock_monarch_client.create_transaction_category.assert_not_called()


class TestSplitsMutationsRefused:
    def test_split_transaction(self, read_only_env, mock_monarch_client):
        result = asyncio.run(split_transaction("txn-1", []))
        _assert_refused(result, "split_transaction")
        mock_monarch_client.update_transaction_splits.assert_not_called()


class TestRuleMutationsRefused:
    def test_create_transaction_rule(self, read_only_env, mock_monarch_client):
        result = asyncio.run(
            create_transaction_rule(
                merchant_criteria_operator="contains",
                merchant_criteria_value="amazon",
                set_category_id="cat-1",
            )
        )
        _assert_refused(result, "create_transaction_rule")
        mock_monarch_client.gql_call.assert_not_called()

    def test_update_transaction_rule(self, read_only_env, mock_monarch_client):
        result = asyncio.run(
            update_transaction_rule(rule_id="rule-1", set_category_id="cat-1")
        )
        _assert_refused(result, "update_transaction_rule")
        mock_monarch_client.gql_call.assert_not_called()

    def test_delete_transaction_rule(self, read_only_env, mock_monarch_client):
        result = asyncio.run(delete_transaction_rule(rule_id="rule-1"))
        _assert_refused(result, "delete_transaction_rule")
        mock_monarch_client.gql_call.assert_not_called()


class TestBudgetMutationsRefused:
    def test_set_budget_amount(self, read_only_env, mock_monarch_client):
        result = asyncio.run(
            set_budget_amount(amount=100.0, category_id="cat-1")
        )
        _assert_refused(result, "set_budget_amount")
        mock_monarch_client.set_budget_amount.assert_not_called()


class TestReadOnlyToolsStillWork:
    """Sanity check: read-only tools must continue to work in read-only mode."""

    def test_get_accounts_still_works(self, read_only_env, mock_monarch_client):
        result = asyncio.run(get_accounts())
        payload = json.loads(result)
        assert isinstance(payload, list)
        assert payload[0]["id"] == "acc-1"
        mock_monarch_client.get_accounts.assert_called_once()

    def test_get_transactions_still_works(self, read_only_env, mock_monarch_client):
        result = asyncio.run(get_transactions(limit=5))
        payload = json.loads(result)
        assert payload["tool"] == "get_transactions"
        mock_monarch_client.get_transactions.assert_called()


class TestRefusalHelpers:
    """Direct unit-tests of the helpers, independent of any tool."""

    def test_read_only_refusal_shape(self):
        payload = json.loads(read_only_refusal("some_tool"))
        assert payload["read_only"] is True
        assert payload["tool"] == "some_tool"
        assert payload["success"] is False

    def test_auth_mutation_disabled_shape(self):
        payload = json.loads(auth_mutation_disabled("monarch_login"))
        assert payload["disabled"] is True
        assert payload["tool"] == "monarch_login"
        assert "login_setup.py" in payload["error"]
