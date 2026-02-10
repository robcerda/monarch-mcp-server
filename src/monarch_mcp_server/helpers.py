"""Shared helpers for Monarch MCP Server tools."""

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def format_transaction(txn: Dict[str, Any], extended: bool = False) -> Dict[str, Any]:
    """Format a raw Monarch transaction dict into a consistent output format.

    Args:
        txn: Raw transaction dict from the Monarch API.
        extended: If True, include extra fields like is_split, is_recurring,
                  has_attachments.
    """
    info: Dict[str, Any] = {
        "id": txn.get("id"),
        "date": txn.get("date"),
        "amount": txn.get("amount"),
        "merchant": txn.get("merchant", {}).get("name") if txn.get("merchant") else None,
        "original_name": txn.get("plaidName") or txn.get("originalName"),
        "category": txn.get("category", {}).get("name") if txn.get("category") else None,
        "category_id": txn.get("category", {}).get("id") if txn.get("category") else None,
        "account": txn.get("account", {}).get("displayName") if txn.get("account") else None,
        "account_id": txn.get("account", {}).get("id") if txn.get("account") else None,
        "notes": txn.get("notes"),
        "needs_review": txn.get("needsReview", False),
        "is_pending": txn.get("pending", False),
        "hide_from_reports": txn.get("hideFromReports", False),
        "tags": [
            {"id": tag.get("id"), "name": tag.get("name")}
            for tag in txn.get("tags", [])
        ] if txn.get("tags") else [],
    }

    if extended:
        info["is_split"] = txn.get("isSplitTransaction", False)
        info["is_recurring"] = txn.get("isRecurring", False)
        info["has_attachments"] = bool(txn.get("attachments"))

    return info


def json_success(data: Any) -> str:
    """Serialize *data* to a JSON string for tool responses."""
    return json.dumps(data, indent=2, default=str)


def json_error(tool_name: str, exc: Exception) -> str:
    """Return a consistent JSON error string and log the failure."""
    logger.error(f"Failed in {tool_name}: {exc}")
    return json.dumps(
        {"error": True, "tool": tool_name, "message": str(exc)},
        indent=2,
        default=str,
    )
