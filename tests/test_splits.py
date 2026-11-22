"""Tests for transaction split tools."""

import json

from monarch_mcp_server.tools.splits import split_transaction


class TestSplitTransactionReportsRejection:
    async def test_rejected_split_is_not_reported_as_success(
        self, mock_monarch_client
    ):
        """The outcome used to be hardcoded to success.

        Monarch rejects a split that does not sum to the original amount by
        returning errors in the payload of an HTTP 200.
        """
        mock_monarch_client.update_transaction_splits.return_value = {
            "updateTransactionSplit": {
                "errors": {
                    "message": "Splits must sum to the transaction amount",
                    "code": "INVALID",
                }
            }
        }
        result = json.loads(
            await split_transaction("txn-1", [{"amount": -5.0}])
        )
        assert result["success"] is False
        assert "sum to the transaction amount" in json.dumps(result)

    async def test_accepted_split_still_reports_success(self, mock_monarch_client):
        mock_monarch_client.update_transaction_splits.return_value = {
            "updateTransactionSplit": {"errors": None, "transaction": {"id": "1"}}
        }
        result = json.loads(
            await split_transaction("txn-1", [{"amount": -5.0}, {"amount": -5.0}])
        )
        assert result["success"] is True
