"""Transaction management tools."""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import format_transaction, json_success, json_error

logger = logging.getLogger(__name__)


@mcp.tool()
async def get_transactions(
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_id: Optional[str] = None,
) -> str:
    """
    Get transactions from Monarch Money.

    Args:
        limit: Number of transactions to retrieve (default: 100)
        offset: Number of transactions to skip (default: 0)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        account_id: Specific account ID to filter by
    """
    try:
        client = await get_monarch_client()

        filters: Dict[str, Any] = {}
        if start_date:
            filters["start_date"] = start_date
        if end_date:
            filters["end_date"] = end_date
        if account_id:
            filters["account_id"] = account_id

        transactions = await client.get_transactions(limit=limit, offset=offset, **filters)

        transaction_list = []
        for txn in transactions.get("allTransactions", {}).get("results", []):
            transaction_info = {
                "id": txn.get("id"),
                "date": txn.get("date"),
                "amount": txn.get("amount"),
                "description": txn.get("description"),
                "category": txn.get("category", {}).get("name")
                if txn.get("category")
                else None,
                "account": txn.get("account", {}).get("displayName"),
                "merchant": txn.get("merchant", {}).get("name")
                if txn.get("merchant")
                else None,
                "is_pending": txn.get("isPending", False),
            }
            transaction_list.append(transaction_info)

        return json_success(transaction_list)
    except Exception as e:
        return json_error("get_transactions", e)


@mcp.tool()
async def search_transactions(
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category_ids: Optional[List[str]] = None,
    account_ids: Optional[List[str]] = None,
    tag_ids: Optional[List[str]] = None,
    has_attachments: Optional[bool] = None,
    has_notes: Optional[bool] = None,
    hidden_from_reports: Optional[bool] = None,
    is_split: Optional[bool] = None,
    is_recurring: Optional[bool] = None,
) -> str:
    """
    Search and filter transactions with comprehensive filtering options.

    This is the most flexible transaction query tool, supporting all available filters.

    Args:
        search: Text to search for in transaction descriptions/merchants
        limit: Maximum number of transactions to return (default: 100)
        offset: Number of transactions to skip for pagination (default: 0)
        start_date: Filter start date in YYYY-MM-DD format
        end_date: Filter end date in YYYY-MM-DD format
        category_ids: List of category IDs to filter by
        account_ids: List of account IDs to filter by
        tag_ids: List of tag IDs to filter by
        has_attachments: Filter for transactions with/without attachments
        has_notes: Filter for transactions with/without notes
        hidden_from_reports: Filter for transactions hidden/shown in reports
        is_split: Filter for split/non-split transactions
        is_recurring: Filter for recurring/non-recurring transactions

    Returns:
        List of matching transactions with full details.
    """
    try:
        client = await get_monarch_client()

        filters: Dict[str, Any] = {"limit": limit, "offset": offset}

        if search:
            filters["search"] = search
        if start_date:
            filters["start_date"] = start_date
        if end_date:
            filters["end_date"] = end_date
        if category_ids:
            filters["category_ids"] = category_ids
        if account_ids:
            filters["account_ids"] = account_ids
        if tag_ids:
            filters["tag_ids"] = tag_ids
        if has_attachments is not None:
            filters["has_attachments"] = has_attachments
        if has_notes is not None:
            filters["has_notes"] = has_notes
        if hidden_from_reports is not None:
            filters["hidden_from_reports"] = hidden_from_reports
        if is_split is not None:
            filters["is_split"] = is_split
        if is_recurring is not None:
            filters["is_recurring"] = is_recurring

        transactions_data = await client.get_transactions(**filters)

        transaction_list = [
            format_transaction(txn, extended=True)
            for txn in transactions_data.get("allTransactions", {}).get("results", [])
        ]

        return json_success(transaction_list)
    except Exception as e:
        return json_error("search_transactions", e)


@mcp.tool()
async def get_transaction_details(transaction_id: str) -> str:
    """
    Get full details for a specific transaction.

    Returns comprehensive information including attachments, splits, tags, and more.

    Args:
        transaction_id: The ID of the transaction to get details for

    Returns:
        Complete transaction details.
    """
    try:
        client = await get_monarch_client()
        result = await client.get_transaction_details(transaction_id=transaction_id)
        return json_success(result)
    except Exception as e:
        return json_error("get_transaction_details", e)


@mcp.tool()
async def create_transaction(
    account_id: str,
    amount: float,
    description: str,
    date: str,
    category_id: Optional[str] = None,
    merchant_name: Optional[str] = None,
) -> str:
    """
    Create a new transaction in Monarch Money.

    Args:
        account_id: The account ID to add the transaction to
        amount: Transaction amount (positive for income, negative for expenses)
        description: Transaction description
        date: Transaction date in YYYY-MM-DD format
        category_id: Optional category ID
        merchant_name: Optional merchant name
    """
    try:
        client = await get_monarch_client()

        transaction_data: Dict[str, Any] = {
            "account_id": account_id,
            "amount": amount,
            "description": description,
            "date": date,
        }

        if category_id:
            transaction_data["category_id"] = category_id
        if merchant_name:
            transaction_data["merchant_name"] = merchant_name

        result = await client.create_transaction(**transaction_data)
        return json_success(result)
    except Exception as e:
        return json_error("create_transaction", e)


@mcp.tool()
async def update_transaction(
    transaction_id: str,
    amount: Optional[float] = None,
    description: Optional[str] = None,
    category_id: Optional[str] = None,
    date: Optional[str] = None,
) -> str:
    """
    Update an existing transaction in Monarch Money.

    Args:
        transaction_id: The ID of the transaction to update
        amount: New transaction amount
        description: New transaction description
        category_id: New category ID
        date: New transaction date in YYYY-MM-DD format
    """
    try:
        client = await get_monarch_client()

        update_data: Dict[str, Any] = {"transaction_id": transaction_id}

        if amount is not None:
            update_data["amount"] = amount
        if description is not None:
            update_data["description"] = description
        if category_id is not None:
            update_data["category_id"] = category_id
        if date is not None:
            update_data["date"] = date

        result = await client.update_transaction(**update_data)
        return json_success(result)
    except Exception as e:
        return json_error("update_transaction", e)


@mcp.tool()
async def set_transaction_category(
    transaction_id: str,
    category_id: str,
    mark_reviewed: bool = True,
) -> str:
    """
    Set the category for a transaction and optionally mark it as reviewed.

    This is the primary tool for categorizing transactions during review.
    Use get_categories() first to see available categories.

    Args:
        transaction_id: The ID of the transaction to categorize
        category_id: The ID of the category to assign (use get_categories to find IDs)
        mark_reviewed: Whether to also mark the transaction as reviewed (default: True)

    Returns:
        Updated transaction details.
    """
    try:
        client = await get_monarch_client()

        update_params: Dict[str, Any] = {
            "transaction_id": transaction_id,
            "category_id": category_id,
        }

        if mark_reviewed:
            update_params["needs_review"] = False

        result = await client.update_transaction(**update_params)
        return json_success(result)
    except Exception as e:
        return json_error("set_transaction_category", e)


@mcp.tool()
async def update_transaction_notes(
    transaction_id: str,
    notes: str,
    receipt_url: Optional[str] = None,
) -> str:
    """
    Update the notes/memo for a transaction.

    Suggested format: [Receipt: URL] Description
    If receipt_url is provided, it will be prepended to the notes.

    Args:
        transaction_id: The ID of the transaction to update
        notes: The note/memo text to add
        receipt_url: Optional URL to a receipt (will be formatted as [Receipt: URL])

    Returns:
        Updated transaction details.
    """
    try:
        client = await get_monarch_client()

        if receipt_url:
            formatted_notes = f"[Receipt: {receipt_url}] {notes}"
        else:
            formatted_notes = notes

        result = await client.update_transaction(
            transaction_id=transaction_id,
            notes=formatted_notes,
        )
        return json_success(result)
    except Exception as e:
        return json_error("update_transaction_notes", e)


@mcp.tool()
async def mark_transaction_reviewed(transaction_id: str) -> str:
    """
    Mark a transaction as reviewed (clears the needs_review flag).

    Use this after reviewing a transaction that doesn't need category changes.

    Args:
        transaction_id: The ID of the transaction to mark as reviewed

    Returns:
        Updated transaction details.
    """
    try:
        client = await get_monarch_client()
        result = await client.update_transaction(
            transaction_id=transaction_id,
            needs_review=False,
        )
        return json_success(result)
    except Exception as e:
        return json_error("mark_transaction_reviewed", e)


@mcp.tool()
async def bulk_categorize_transactions(
    transaction_ids: List[str],
    category_id: str,
    mark_reviewed: bool = True,
) -> str:
    """
    Apply the same category to multiple transactions at once.

    This is useful for categorizing similar transactions in bulk,
    such as all purchases from the same merchant.

    Args:
        transaction_ids: List of transaction IDs to categorize
        category_id: The category ID to apply to all transactions
        mark_reviewed: Whether to also mark transactions as reviewed (default: True)

    Returns:
        Summary of results including success/failure counts.
    """
    try:
        client = await get_monarch_client()

        results: Dict[str, Any] = {
            "total": len(transaction_ids),
            "successful": 0,
            "failed": 0,
            "errors": [],
        }

        async def _update_one(txn_id: str) -> None:
            update_params: Dict[str, Any] = {
                "transaction_id": txn_id,
                "category_id": category_id,
            }
            if mark_reviewed:
                update_params["needs_review"] = False
            await client.update_transaction(**update_params)

        # Use asyncio.gather for concurrent updates
        tasks = [_update_one(txn_id) for txn_id in transaction_ids]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        for txn_id, outcome in zip(transaction_ids, outcomes):
            if isinstance(outcome, Exception):
                results["failed"] += 1
                results["errors"].append({
                    "transaction_id": txn_id,
                    "error": str(outcome),
                })
            else:
                results["successful"] += 1

        return json_success(results)
    except Exception as e:
        return json_error("bulk_categorize_transactions", e)


@mcp.tool()
async def delete_transaction(transaction_id: str) -> str:
    """
    Delete a transaction from Monarch Money.

    Warning: This action cannot be undone.

    Args:
        transaction_id: The ID of the transaction to delete

    Returns:
        Confirmation of deletion.
    """
    try:
        client = await get_monarch_client()
        result = await client.delete_transaction(transaction_id=transaction_id)
        return json_success(result)
    except Exception as e:
        return json_error("delete_transaction", e)


@mcp.tool()
async def get_recurring_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """
    Get upcoming recurring transactions.

    Returns scheduled recurring transactions with their merchants, amounts, and accounts.

    Args:
        start_date: Start date in YYYY-MM-DD format (defaults to start of current month)
        end_date: End date in YYYY-MM-DD format (defaults to end of current month)

    Returns:
        List of upcoming recurring transactions.
    """
    try:
        client = await get_monarch_client()

        filters: Dict[str, Any] = {}
        if start_date:
            filters["start_date"] = start_date
        if end_date:
            filters["end_date"] = end_date

        result = await client.get_recurring_transactions(**filters)

        recurring_list = []
        for item in result.get("recurringTransactionItems", []):
            recurring_info = {
                "date": item.get("date"),
                "amount": item.get("amount"),
                "is_past": item.get("isPast", False),
                "transaction_id": item.get("transactionId"),
                "stream": {
                    "id": item.get("stream", {}).get("id"),
                    "frequency": item.get("stream", {}).get("frequency"),
                    "amount": item.get("stream", {}).get("amount"),
                    "is_approximate": item.get("stream", {}).get("isApproximate", False),
                    "merchant": item.get("stream", {}).get("merchant", {}).get("name")
                    if item.get("stream", {}).get("merchant") else None,
                } if item.get("stream") else None,
                "category": item.get("category", {}).get("name") if item.get("category") else None,
                "account": item.get("account", {}).get("displayName") if item.get("account") else None,
            }
            recurring_list.append(recurring_info)

        return json_success(recurring_list)
    except Exception as e:
        return json_error("get_recurring_transactions", e)


@mcp.tool()
async def get_transactions_needing_review(
    needs_review: bool = True,
    days: Optional[int] = None,
    uncategorized_only: bool = False,
    without_notes_only: bool = False,
    limit: int = 100,
    account_id: Optional[str] = None,
) -> str:
    """
    Get transactions that need review based on various criteria.

    This is the primary tool for finding transactions to categorize and review.

    Args:
        needs_review: Filter for transactions flagged as needing review (default: True)
        days: Only include transactions from the last N days (e.g., 7 for last week)
        uncategorized_only: Only include transactions without a category assigned
        without_notes_only: Only include transactions without notes/memos
        limit: Maximum number of transactions to return (default: 100)
        account_id: Filter by specific account ID

    Returns:
        List of transactions matching the criteria with full details.
    """
    try:
        client = await get_monarch_client()

        filters: Dict[str, Any] = {"limit": limit}

        if days:
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            filters["start_date"] = start
            filters["end_date"] = end

        if account_id:
            filters["account_ids"] = [account_id]

        if without_notes_only:
            filters["has_notes"] = False

        transactions_data = await client.get_transactions(**filters)

        transaction_list = []
        for txn in transactions_data.get("allTransactions", {}).get("results", []):
            if needs_review and not txn.get("needsReview", False):
                continue

            if uncategorized_only:
                category = txn.get("category")
                if category and category.get("id"):
                    continue

            transaction_list.append(format_transaction(txn))

        return json_success(transaction_list)
    except Exception as e:
        return json_error("get_transactions_needing_review", e)
