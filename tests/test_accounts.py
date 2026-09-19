"""Tests for account-related MCP tools."""

import json

from monarch_mcp_server.tools.accounts import (
    get_accounts,
    get_account_holdings,
    refresh_accounts,
    update_account,
    get_account_balance_history,
    upload_account_balance_history,
)


class TestGetAccounts:
    async def test_returns_formatted_account_list(self):
        result = json.loads(await get_accounts())
        assert len(result) == 2
        assert result[0]["id"] == "acc-1"
        assert result[0]["name"] == "Checking Account"
        assert result[0]["type"] == "checking"
        assert result[0]["balance"] == 1500.00
        assert result[0]["current_balance"] == 1500.00
        assert result[0]["display_balance"] == 500.00
        assert result[0]["institution"] == "Test Bank"
        assert result[0]["is_active"] is True
        assert result[0]["is_hidden"] is False

    async def test_hidden_account_flagged(self):
        result = json.loads(await get_accounts())
        assert result[1]["is_hidden"] is True

    async def test_handles_null_type(self, mock_monarch_client):
        mock_monarch_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "acc-3",
                    "displayName": "Unknown",
                    "type": None,
                    "currentBalance": 0,
                    "displayBalance": 0,
                    "institution": None,
                    "deactivatedAt": None,
                    "isHidden": False,
                }
            ]
        }
        result = json.loads(await get_accounts())
        assert result[0]["type"] is None
        assert result[0]["institution"] is None
        assert result[0]["balance"] == 0
        assert result[0]["current_balance"] == 0
        assert result[0]["display_balance"] == 0

    async def test_handles_null_owned_by_user(self, mock_monarch_client):
        mock_monarch_client.get_accounts.return_value = {
            "accounts": [{"id": "acc-3", "ownedByUser": None}]
        }
        result = json.loads(await get_accounts())
        assert result[0]["owned_by_user"] is None

    async def test_sync_status_ok_by_default(self):
        result = json.loads(await get_accounts())
        assert result[0]["sync"]["state"] == "ok"
        assert result[0]["sync"]["needs_reauth"] is False
        assert result[0]["sync"]["disconnected_at"] is None
        assert result[0]["is_manual"] is False
        assert result[0]["last_updated_at"] is None

    async def test_sync_status_surfaces_broken_connection(self, mock_monarch_client):
        """A frozen bank link is silent in Monarch; get_accounts must say so."""
        mock_monarch_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "acc-reauth",
                    "displayName": "Needs Login",
                    "displayLastUpdatedAt": "2026-02-08T04:00:00+00:00",
                    "credential": {
                        "updateRequired": True,
                        "dataProvider": "PLAID",
                        "institution": {"status": "RELINK"},
                    },
                },
                {
                    "id": "acc-disc",
                    "displayName": "Dropped",
                    "credential": {
                        "updateRequired": False,
                        "disconnectedFromDataProviderAt": "2026-03-01T00:00:00+00:00",
                        "dataProvider": "FINICITY",
                    },
                },
                {
                    "id": "acc-paused",
                    "displayName": "Paused",
                    "syncDisabled": True,
                    "credential": {"updateRequired": False},
                },
                {
                    "id": "acc-manual",
                    "displayName": "House",
                    "isManual": True,
                    "credential": None,
                },
            ]
        }
        result = {a["id"]: a for a in json.loads(await get_accounts())}

        assert result["acc-reauth"]["sync"]["state"] == "needs_reauth"
        assert result["acc-reauth"]["sync"]["needs_reauth"] is True
        assert result["acc-reauth"]["sync"]["data_provider"] == "PLAID"
        assert result["acc-reauth"]["sync"]["connection_status"] == "RELINK"
        assert result["acc-reauth"]["last_updated_at"] == "2026-02-08T04:00:00+00:00"

        assert result["acc-disc"]["sync"]["state"] == "disconnected"
        assert result["acc-disc"]["sync"]["disconnected_at"] == "2026-03-01T00:00:00+00:00"

        assert result["acc-paused"]["sync"]["state"] == "sync_disabled"
        assert result["acc-paused"]["sync"]["sync_disabled"] is True

        assert result["acc-manual"]["sync"]["state"] == "manual"
        assert result["acc-manual"]["sync"]["connection_status"] is None
        assert result["acc-manual"]["is_manual"] is True

    async def test_handles_empty_accounts(self, mock_monarch_client):
        mock_monarch_client.get_accounts.return_value = {"accounts": []}
        result = json.loads(await get_accounts())
        assert result == []

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_accounts.side_effect = Exception("API timeout")
        result = await get_accounts()
        assert "get_accounts" in result
        assert "API timeout" in result


class TestGetAccountHoldings:
    async def test_returns_holdings(self):
        result = json.loads(await get_account_holdings("acc-1"))
        assert result["holdings"][0]["name"] == "VTI"
        assert result["holdings"][0]["value"] == 25000.00

    async def test_passes_account_id(self, mock_monarch_client):
        await get_account_holdings("acc-99")
        mock_monarch_client.get_account_holdings.assert_called_once_with("acc-99")

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_account_holdings.side_effect = Exception("Not found")
        result = await get_account_holdings("bad-id")
        assert "get_account_holdings" in result


class TestRefreshAccounts:
    async def test_auto_discovers_active_visible_accounts(self, mock_monarch_client):
        """No args → fetch accounts, refresh only active+non-hidden ones."""
        result = json.loads(await refresh_accounts())
        assert result["requestAccountsRefresh"]["success"] is True
        # Default fixture: acc-1 active+visible, acc-2 hidden. Only acc-1 refreshes.
        mock_monarch_client.request_accounts_refresh.assert_awaited_once_with(["acc-1"])

    async def test_passes_explicit_account_ids(self, mock_monarch_client):
        """Explicit account_ids must be passed through unchanged."""
        result = json.loads(await refresh_accounts(account_ids=["acc-9", "acc-42"]))
        assert result["requestAccountsRefresh"]["success"] is True
        mock_monarch_client.request_accounts_refresh.assert_awaited_once_with(
            ["acc-9", "acc-42"]
        )
        # Must not have looked up accounts when caller specified the list.
        mock_monarch_client.get_accounts.assert_not_called()

    async def test_empty_list_falls_back_to_auto_discover(self, mock_monarch_client):
        """An empty list is treated as 'refresh all visible', matching no-arg."""
        await refresh_accounts(account_ids=[])
        mock_monarch_client.request_accounts_refresh.assert_awaited_once_with(["acc-1"])

    async def test_no_visible_accounts_returns_graceful_message(
        self, mock_monarch_client
    ):
        """If every account is hidden or inactive, do not call the upstream API."""
        mock_monarch_client.get_accounts.return_value = {
            "accounts": [
                {"id": "acc-h", "isHidden": True, "deactivatedAt": None},
                {"id": "acc-d", "isHidden": False, "deactivatedAt": "2025-01-01"},
            ]
        }
        result = json.loads(await refresh_accounts())
        assert result["refreshed"] == []
        assert "No active" in result["message"]
        mock_monarch_client.request_accounts_refresh.assert_not_called()

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.request_accounts_refresh.side_effect = Exception("Timeout")
        result = await refresh_accounts(account_ids=["acc-1"])
        assert "refresh_accounts" in result


class TestGetAccountBalanceHistory:
    async def test_returns_formatted_snapshots(self):
        result = json.loads(await get_account_balance_history("12345"))
        assert result["account_id"] == "12345"
        assert result["snapshot_count"] == 3
        assert result["current_balance"] == 1100.0
        assert result["earliest_balance"] == 1000.0
        assert result["highest"] == 1200.0
        assert result["lowest"] == 1000.0
        assert result["snapshots"][0] == {"date": "2026-04-20", "balance": 1000.0}

    async def test_handles_empty_history(self, mock_monarch_client):
        mock_monarch_client.get_account_history.return_value = []
        result = json.loads(await get_account_balance_history("12345"))
        assert result["snapshot_count"] == 0
        assert result["snapshots"] == []

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_account_history.side_effect = Exception("Not found")
        result = await get_account_balance_history("12345")
        assert "get_account_balance_history" in result


class TestUploadAccountBalanceHistory:
    async def test_applies_corrections(self, mock_monarch_client):
        corrections = json.dumps({"2026-04-21": 900.0})
        result = json.loads(await upload_account_balance_history("12345", corrections))
        assert result["updated"] is True
        assert result["dates_corrected"] == ["2026-04-21"]
        assert result["unmatched_dates"] == []
        assert result["total_snapshots"] == 3

        call_args = mock_monarch_client.upload_account_balance_history.call_args
        assert call_args.kwargs["account_id"] == "12345"
        assert len(call_args.kwargs["csv_content"]) == 3

    async def test_no_matching_dates(self, mock_monarch_client):
        corrections = json.dumps({"2026-01-01": 500.0})
        result = json.loads(await upload_account_balance_history("12345", corrections))
        assert result["updated"] is False
        assert result["unmatched_dates"] == ["2026-01-01"]
        mock_monarch_client.upload_account_balance_history.assert_not_called()

    async def test_surfaces_unmatched_alongside_applied(self, mock_monarch_client):
        corrections = json.dumps({"2026-04-21": 900.0, "2099-12-31": 1.0})
        result = json.loads(await upload_account_balance_history("12345", corrections))
        assert result["updated"] is True
        assert result["dates_corrected"] == ["2026-04-21"]
        assert result["unmatched_dates"] == ["2099-12-31"]

    async def test_dry_run_skips_upload(self, mock_monarch_client):
        corrections = json.dumps({"2026-04-21": 900.0})
        result = json.loads(
            await upload_account_balance_history("12345", corrections, dry_run=True)
        )
        assert result["dry_run"] is True
        assert result["dates_to_correct"] == ["2026-04-21"]
        assert result["total_snapshots"] == 3
        mock_monarch_client.upload_account_balance_history.assert_not_called()

    async def test_rejects_invalid_json(self, mock_monarch_client):
        result = json.loads(
            await upload_account_balance_history("12345", "not json")
        )
        assert result["error"] is True
        assert "valid JSON" in result["message"]
        mock_monarch_client.get_account_history.assert_not_called()

    async def test_rejects_non_object(self, mock_monarch_client):
        result = json.loads(
            await upload_account_balance_history("12345", "[1, 2, 3]")
        )
        assert result["error"] is True
        assert "JSON object" in result["message"]
        mock_monarch_client.get_account_history.assert_not_called()

    async def test_rejects_invalid_date_key(self, mock_monarch_client):
        result = json.loads(
            await upload_account_balance_history("12345", '{"yesterday": 100}')
        )
        assert result["error"] is True
        mock_monarch_client.get_account_history.assert_not_called()

    async def test_rejects_non_numeric_value(self, mock_monarch_client):
        result = json.loads(
            await upload_account_balance_history(
                "12345", '{"2026-04-21": "not-a-number"}'
            )
        )
        assert result["error"] is True
        mock_monarch_client.get_account_history.assert_not_called()

    async def test_handles_api_error(self, mock_monarch_client):
        mock_monarch_client.get_account_history.side_effect = Exception("Timeout")
        result = await upload_account_balance_history("12345", '{"2026-04-21": 0}')
        assert "upload_account_balance_history" in result


class TestUpdateAccount:
    """A generic aggregator name or a wrongly counted balance previously forced
    a trip to the web UI; these cover the tool that closes that gap."""

    async def test_renames_an_account(self, mock_monarch_client):
        mock_monarch_client.update_account.return_value = {
            "updateAccount": {
                "account": {
                    "displayName": "Issuer Card Product (...0000)",
                    "currentBalance": -816.78,
                    "includeInNetWorth": True,
                    "hideFromList": False,
                    "hideTransactionsFromReports": False,
                },
                "errors": None,
            }
        }
        result = json.loads(
            await update_account(
                account_id="acc-1", name="Issuer Card Product (...0000)"
            )
        )
        assert result["updated"] is True
        assert result["applied"] == {"account_name": "Issuer Card Product (...0000)"}
        mock_monarch_client.update_account.assert_awaited_once_with(
            account_id="acc-1", account_name="Issuer Card Product (...0000)"
        )

    async def test_omitted_fields_are_not_sent(self, mock_monarch_client):
        """Only what the caller passed may reach Monarch, so an unrelated
        setting cannot be reset to a default as a side effect."""
        mock_monarch_client.update_account.return_value = {
            "updateAccount": {"account": {}, "errors": None}
        }
        await update_account(account_id="acc-1", include_in_net_worth=False)
        mock_monarch_client.update_account.assert_awaited_once_with(
            account_id="acc-1", include_in_net_worth=False
        )

    async def test_false_is_a_real_value_not_an_omission(self, mock_monarch_client):
        """include_in_net_worth=False is the whole point of the flag; a falsy
        check rather than an `is not None` check would silently drop it."""
        mock_monarch_client.update_account.return_value = {
            "updateAccount": {"account": {}, "errors": None}
        }
        await update_account(
            account_id="acc-1",
            hide_from_summary_list=False,
            hide_transactions_from_reports=False,
        )
        _, kwargs = mock_monarch_client.update_account.await_args
        assert kwargs["hide_from_summary_list"] is False
        assert kwargs["hide_transactions_from_reports"] is False

    async def test_zero_balance_is_not_treated_as_omitted(self, mock_monarch_client):
        """Setting a paid-off account to 0.00 is a legitimate correction."""
        mock_monarch_client.update_account.return_value = {
            "updateAccount": {"account": {}, "errors": None}
        }
        await update_account(account_id="acc-1", balance=0.0)
        _, kwargs = mock_monarch_client.update_account.await_args
        assert kwargs["account_balance"] == 0.0

    async def test_no_fields_is_an_error_not_a_silent_noop(self, mock_monarch_client):
        result = json.loads(await update_account(account_id="acc-1"))
        assert result["error"] is True
        mock_monarch_client.update_account.assert_not_awaited()

    async def test_dry_run_reports_current_and_proposed_without_writing(
        self, mock_monarch_client
    ):
        result = json.loads(
            await update_account(account_id="acc-1", name="Renamed", dry_run=True)
        )
        assert result["dry_run"] is True
        assert result["current"]["name"] == "Checking Account"
        assert result["proposed"] == {"account_name": "Renamed"}
        mock_monarch_client.update_account.assert_not_awaited()

    async def test_dry_run_on_unknown_account_errors(self, mock_monarch_client):
        result = json.loads(
            await update_account(account_id="nope", name="X", dry_run=True)
        )
        assert result["error"] is True
        assert "not found" in result["message"]

    async def test_monarch_payload_errors_are_surfaced(self, mock_monarch_client):
        mock_monarch_client.update_account.return_value = {
            "updateAccount": {
                "account": None,
                "errors": [{"message": "invalid account type"}],
            }
        }
        result = json.loads(await update_account(account_id="acc-1", name="X"))
        # Rejections use the json_rejected shape shared by the other mutators
        # (see #125), rather than the json_error shape used for exceptions.
        assert result["success"] is False
        assert "invalid account type" in json.dumps(result)
