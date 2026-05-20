"""Transaction management tools."""

import asyncio
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import (
    first_present,
    format_exception,
    format_transaction,
    json_error,
    json_success,
    tool_response_envelope,
)
from monarch_mcp_server.read_only import is_read_only, read_only_refusal

logger = logging.getLogger(__name__)

KNOWN_CURRENCY_CODES = {
    "AED",
    "AUD",
    "BRL",
    "CAD",
    "CHF",
    "CNY",
    "EUR",
    "GBP",
    "HKD",
    "JPY",
    "MXN",
    "NOK",
    "NZD",
    "SEK",
    "SGD",
    "THB",
    "USD",
    "ZAR",
}


def _normalize_search_text(value: Any) -> str:
    if value is None:
        return ""

    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return ascii_text.casefold()


def _search_tokens(search: str) -> List[str]:
    return [
        token
        for token in re.split(r"\s+", _normalize_search_text(search).strip())
        if token
    ]


def _name_from_value(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        return value.get("name")
    if isinstance(value, str):
        return value
    return None


def _id_from_value(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        return value.get("id")
    return None


def _raw_transaction_matches_search(
    txn: Dict[str, Any],
    category_metadata: Dict[str, Dict[str, Optional[str]]],
    search: str,
) -> bool:
    tokens = _search_tokens(search)
    if not tokens:
        return True

    category = txn.get("category") if isinstance(txn.get("category"), dict) else {}
    account = txn.get("account") if isinstance(txn.get("account"), dict) else {}
    merchant = txn.get("merchant")
    category_id = category.get("id") if isinstance(category, dict) else None
    metadata = category_metadata.get(category_id, {})

    values = [
        txn.get("description"),
        txn.get("originalStatement"),
        txn.get("plaidDescription"),
        txn.get("plaidName"),
        txn.get("notes"),
        _name_from_value(merchant),
        _id_from_value(merchant),
        category.get("name") if isinstance(category, dict) else None,
        category_id,
        metadata.get("group"),
        metadata.get("group_id"),
        account.get("displayName") if isinstance(account, dict) else None,
        account.get("name") if isinstance(account, dict) else None,
        account.get("id") if isinstance(account, dict) else None,
    ]
    for tag in txn.get("tags", []):
        if isinstance(tag, dict):
            values.extend([tag.get("id"), tag.get("name")])

    haystack = " ".join(_normalize_search_text(value) for value in values if value)
    return all(token in haystack for token in tokens)


def _direction_from_amount(amount: Any) -> Optional[str]:
    if amount is None:
        return None

    try:
        parsed = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        return None

    if parsed > 0:
        return "inflow"
    if parsed < 0:
        return "outflow"
    return "zero"


def _currency_from_text(text: Any) -> Optional[str]:
    if not isinstance(text, str):
        return None

    for match in re.findall(r"\b[A-Z]{3}\b", text.upper()):
        if match in KNOWN_CURRENCY_CODES:
            return match
    return None


def _currency_from_transaction(txn: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Resolve a transaction's currency and the source of that value.

    Returns ``(currency, source)`` where source is one of:
    - ``"api"``: explicit currency field on the transaction or account
    - ``"account_name_guess"``: regex-matched a 3-letter code in the account
      display/name (heuristic; may be wrong for accounts named "USD Bank" etc.)
    - ``None``: no currency could be derived
    """
    account = txn.get("account") if isinstance(txn.get("account"), dict) else {}
    amount = txn.get("amount") if isinstance(txn.get("amount"), dict) else {}

    direct_currency = first_present(
        txn.get("currency"),
        txn.get("currencyCode"),
        txn.get("isoCurrencyCode"),
        amount.get("currency") if isinstance(amount, dict) else None,
        amount.get("currencyCode") if isinstance(amount, dict) else None,
        account.get("currency") if isinstance(account, dict) else None,
        account.get("currencyCode") if isinstance(account, dict) else None,
        account.get("isoCurrencyCode") if isinstance(account, dict) else None,
    )
    if direct_currency:
        return str(direct_currency).upper(), "api"

    guessed = first_present(
        _currency_from_text(
            account.get("displayName") if isinstance(account, dict) else None
        ),
        _currency_from_text(account.get("name") if isinstance(account, dict) else None),
    )
    if guessed:
        return guessed, "account_name_guess"
    return None, None


def _format_transaction_row(
    txn: Dict[str, Any],
    category_metadata: Dict[str, Dict[str, Optional[str]]],
) -> Dict[str, Any]:
    category = txn.get("category") if isinstance(txn.get("category"), dict) else {}
    account = txn.get("account") if isinstance(txn.get("account"), dict) else {}
    merchant = txn.get("merchant")
    category_id = category.get("id") if isinstance(category, dict) else None
    txn_category_metadata = category_metadata.get(category_id, {})

    if category_id:
        category_group = (
            category.get("group") if isinstance(category.get("group"), dict) else {}
        )
        txn_category_metadata = {
            "group": first_present(
                txn_category_metadata.get("group"),
                category_group.get("name"),
            ),
            "group_id": first_present(
                txn_category_metadata.get("group_id"),
                category_group.get("id"),
            ),
            "group_type": first_present(
                txn_category_metadata.get("group_type"),
                category_group.get("type"),
            ),
        }

    amount = txn.get("amount")
    direction = _direction_from_amount(amount)
    plaid_description = first_present(
        txn.get("plaidDescription"),
        txn.get("plaidName"),
        txn.get("originalStatement"),
    )
    original_statement = first_present(txn.get("originalStatement"), plaid_description)
    transaction_type = first_present(
        txn.get("transactionType"),
        txn.get("type"),
        txn.get("kind"),
        txn_category_metadata.get("group_type"),
        direction,
    )
    currency, currency_source = _currency_from_transaction(txn)

    return {
        "id": txn.get("id"),
        "date": txn.get("date"),
        "amount": amount,
        "currency": currency,
        "currency_source": currency_source,
        "direction": direction,
        "direction_source": "amount_sign" if direction else None,
        "transaction_type": transaction_type,
        "description": txn.get("description"),
        "original_statement": original_statement,
        "plaid_description": plaid_description,
        "notes": txn.get("notes"),
        "category": category.get("name") if isinstance(category, dict) else None,
        "category_id": category_id,
        "category_group": txn_category_metadata.get("group"),
        "category_group_id": txn_category_metadata.get("group_id"),
        "account": account.get("displayName") if isinstance(account, dict) else None,
        "account_id": account.get("id") if isinstance(account, dict) else None,
        "merchant": _name_from_value(merchant),
        "merchant_id": _id_from_value(merchant),
        "is_pending": txn.get("isPending", txn.get("pending", False)),
        "needs_review": txn.get("needsReview", False),
        "review_status": txn.get("reviewStatus"),
        "is_recurring": bool(
            txn.get("isRecurring") or txn.get("recurringTransactionStream")
        ),
        "is_split_transaction": bool(txn.get("isSplitTransaction")),
        "hide_from_reports": txn.get("hideFromReports", False),
        "tags": [
            {"id": tag.get("id"), "name": tag.get("name")}
            for tag in (txn.get("tags") or [])
        ],
    }


@mcp.tool()
async def get_transactions(
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_id: Optional[str] = None,
    search: Optional[str] = None,
    category_ids: Optional[List[str]] = None,
    category_group_ids: Optional[List[str]] = None,
    account_ids: Optional[List[str]] = None,
    tag_ids: Optional[List[str]] = None,
    has_notes: Optional[bool] = None,
    is_split: Optional[bool] = None,
    is_recurring: Optional[bool] = None,
    wide_search: bool = False,
    search_scan_limit: int = 200,
) -> str:
    """
    Get transactions from Monarch Money.

    Args:
        limit: Number of transactions to retrieve (default: 100)
        offset: Number of transactions to skip (default: 0)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        account_id: Specific account ID to filter by (deprecated, use account_ids)
        search: Search query to filter transactions
        category_ids: List of category IDs to filter by
        category_group_ids: List of category group IDs to filter by
        account_ids: List of account IDs to filter by
        tag_ids: List of tag IDs to filter by
        has_notes: Filter for transactions with/without notes
        is_split: Filter for split transactions
        is_recurring: Filter for recurring transactions
        wide_search: Opt-in fallback that pulls a page of transactions and
                     filters them locally across description, original
                     statement, plaid name, notes, merchant, category,
                     account, and tags when Monarch's server-side search
                     returns empty or errors. Off by default because it can
                     be expensive; turn on when a search you expect to match
                     comes back empty.
        search_scan_limit: Maximum transactions the wide_search fallback
                           will scan locally (default 200)
    """
    try:
        client = await get_monarch_client()
        category_metadata: Dict[str, Dict[str, Optional[str]]] = {}

        async def _load_category_metadata(required: bool = False) -> None:
            nonlocal category_metadata
            if category_metadata:
                return

            try:
                data = await client.get_transaction_categories()
            except Exception:
                if required:
                    raise
                logger.info("Skipping transaction category enrichment", exc_info=True)
                return

            for cat in data.get("categories", []):
                group = cat.get("group") if isinstance(cat.get("group"), dict) else {}
                category_metadata[cat.get("id")] = {
                    "group": group.get("name") if isinstance(group, dict) else None,
                    "group_id": group.get("id") if isinstance(group, dict) else None,
                    "group_type": (
                        group.get("type") if isinstance(group, dict) else None
                    ),
                }

        # category_metadata is loaded lazily: only when category_group_ids
        # is in filters or when wide_search needs it for haystack matching.
        # Ordinary calls rely on whatever Monarch returns inline on each
        # transaction's `category.group` field.

        filters: Dict[str, Any] = {}
        if start_date:
            filters["start_date"] = start_date
        if end_date:
            filters["end_date"] = end_date

        merged_account_ids: List[str] = list(account_ids) if account_ids else []
        if account_id and account_id not in merged_account_ids:
            merged_account_ids.append(account_id)
        if merged_account_ids:
            filters["account_ids"] = merged_account_ids

        if search:
            filters["search"] = search

        merged_category_ids = list(category_ids or [])
        if category_group_ids:
            await _load_category_metadata(required=True)
            group_category_ids = [
                category_id
                for category_id, metadata in category_metadata.items()
                if metadata.get("group_id") in category_group_ids
            ]
            for category_id in group_category_ids:
                if category_id not in merged_category_ids:
                    merged_category_ids.append(category_id)

            if not merged_category_ids:
                empty_args = {
                    "limit": limit,
                    "offset": offset,
                    "start_date": start_date,
                    "end_date": end_date,
                    "account_id": account_id,
                    "search": search,
                    "category_ids": category_ids,
                    "category_group_ids": category_group_ids,
                    "account_ids": account_ids,
                    "tag_ids": tag_ids,
                    "has_notes": has_notes,
                    "is_split": is_split,
                    "is_recurring": is_recurring,
                    "wide_search": wide_search,
                    "search_scan_limit": search_scan_limit,
                }
                return json_success(
                    tool_response_envelope(
                        "get_transactions",
                        empty_args,
                        [],
                        search_info={"strategy": "server", "fallback_reason": None},
                    )
                )

        if merged_category_ids:
            filters["category_ids"] = merged_category_ids
        if tag_ids:
            filters["tag_ids"] = tag_ids
        if has_notes is not None:
            filters["has_notes"] = has_notes
        if is_split is not None:
            filters["is_split"] = is_split
        if is_recurring is not None:
            filters["is_recurring"] = is_recurring

        async def _wide_search(
            reason: str, original_error: Optional[Exception] = None
        ) -> tuple[Dict[str, Any], Dict[str, Any]]:
            if not search or not wide_search:
                if original_error:
                    raise original_error
                return {"allTransactions": {"results": []}}, {
                    "strategy": "server",
                    "fallback_reason": None,
                }

            scan_limit = max(limit, search_scan_limit)
            fallback_filters = {
                key: value for key, value in filters.items() if key != "search"
            }
            fallback_data = await client.get_transactions(
                limit=scan_limit,
                offset=0,
                **fallback_filters,
            )
            all_fallback_transactions = fallback_data.get("allTransactions", {})
            fallback_results = all_fallback_transactions.get("results", [])
            # Load category metadata only now that we know wide_search will run;
            # the haystack uses category group name/id in matching.
            await _load_category_metadata()
            matches = [
                txn
                for txn in fallback_results
                if _raw_transaction_matches_search(txn, category_metadata, search)
            ]
            total_matches = len(matches)
            page = matches[offset : offset + limit]
            return {
                **fallback_data,
                "allTransactions": {
                    **all_fallback_transactions,
                    "results": page,
                    "totalCount": total_matches,
                },
            }, {
                "strategy": "wide",
                "fallback_reason": reason,
                "scan_limit": scan_limit,
                "scanned_count": len(fallback_results),
                "server_error": (
                    format_exception(original_error) if original_error else None
                ),
            }

        try:
            transactions = await client.get_transactions(
                limit=limit,
                offset=offset,
                **filters,
            )
            if (
                search
                and wide_search
                and not transactions.get("allTransactions", {}).get("results", [])
            ):
                transactions, search_info = await _wide_search("empty_server_results")
            else:
                search_info = {"strategy": "server", "fallback_reason": None}
        except Exception as original_error:
            # Server search failed. If the caller opted into wide_search and
            # there is a search query, try the local-scan fallback. Otherwise
            # propagate the original error untouched.
            if not search or not wide_search:
                raise
            transactions, search_info = await _wide_search(
                "server_error", original_error
            )

        all_transactions = transactions.get("allTransactions", {})
        transaction_list = [
            _format_transaction_row(txn, category_metadata)
            for txn in all_transactions.get("results", [])
        ]
        args_summary = {
            "limit": limit,
            "offset": offset,
            "start_date": start_date,
            "end_date": end_date,
            "account_id": account_id,
            "search": search,
            "category_ids": category_ids,
            "category_group_ids": category_group_ids,
            "account_ids": account_ids,
            "tag_ids": tag_ids,
            "has_notes": has_notes,
            "is_split": is_split,
            "is_recurring": is_recurring,
            "wide_search": wide_search,
            "search_scan_limit": search_scan_limit,
        }
        total_count = first_present(
            all_transactions.get("totalCount"),
            all_transactions.get("total_count"),
            all_transactions.get("count"),
        )

        return json_success(
            tool_response_envelope(
                "get_transactions",
                args_summary,
                transaction_list,
                total_count=total_count,
                search_info=search_info,
            )
        )
    except Exception as e:
        return json.dumps(
            {
                "error": True,
                "tool": "get_transactions",
                "message": format_exception(e),
            },
            indent=2,
            default=str,
        )


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
    date: str,
    account_id: str,
    amount: float,
    merchant_name: str,
    category_id: str,
    notes: Optional[str] = None,
    update_balance: Optional[bool] = False,
) -> str:
    """
    Create a new transaction in Monarch Money.

    Args:
        date: Transaction date in YYYY-MM-DD format
        account_id: The account ID to add the transaction to
        amount: Transaction amount (positive for income, negative for expenses)
        merchant_name: Merchant or payee name
        category_id: Category ID for the transaction
        notes: Optional notes for the transaction
        update_balance: Whether to update the account balance (default: false)
    """
    if is_read_only():
        return read_only_refusal("create_transaction")
    try:
        client = await get_monarch_client()

        transaction_data: Dict[str, Any] = {
            "date": date,
            "account_id": account_id,
            "amount": amount,
            "merchant_name": merchant_name,
            "category_id": category_id,
        }

        if notes:
            transaction_data["notes"] = notes
        if update_balance:
            transaction_data["update_balance"] = update_balance

        result = await client.create_transaction(**transaction_data)
        return json_success(result)
    except Exception as e:
        return json_error("create_transaction", e)


@mcp.tool()
async def update_transaction(
    transaction_id: str,
    category_id: Optional[str] = None,
    merchant_name: Optional[str] = None,
    goal_id: Optional[str] = None,
    amount: Optional[float] = None,
    date: Optional[str] = None,
    hide_from_reports: Optional[bool] = None,
    needs_review: Optional[bool] = None,
    notes: Optional[str] = None,
) -> str:
    """
    Update an existing transaction in Monarch Money.

    Args:
        transaction_id: The ID of the transaction to update
        category_id: New category ID
        merchant_name: New merchant or payee name
        goal_id: Goal ID to associate with the transaction
        amount: New transaction amount
        date: New transaction date in YYYY-MM-DD format
        hide_from_reports: Whether to hide this transaction from reports
        needs_review: Whether this transaction needs review
        notes: Notes for the transaction
    """
    if is_read_only():
        return read_only_refusal("update_transaction")
    try:
        client = await get_monarch_client()

        update_data: Dict[str, Any] = {"transaction_id": transaction_id}

        if category_id is not None:
            update_data["category_id"] = category_id
        if merchant_name is not None:
            update_data["merchant_name"] = merchant_name
        if goal_id is not None:
            update_data["goal_id"] = goal_id
        if amount is not None:
            update_data["amount"] = amount
        if date is not None:
            update_data["date"] = date
        if hide_from_reports is not None:
            update_data["hide_from_reports"] = hide_from_reports
        if needs_review is not None:
            update_data["needs_review"] = needs_review
        if notes is not None:
            update_data["notes"] = notes

        result = await client.update_transaction(**update_data)
        return json_success(result)
    except Exception as e:
        return json_error("update_transaction", e)


@mcp.tool()
async def categorize_transaction(transaction_id: str, category_id: str) -> str:
    """
    Assign a category to a transaction.

    Args:
        transaction_id: The ID of the transaction to categorize
        category_id: The category ID to assign
    """
    if is_read_only():
        return read_only_refusal("categorize_transaction")
    try:
        client = await get_monarch_client()
        result = await client.update_transaction(
            transaction_id=transaction_id, category_id=category_id
        )
        return json_success(result)
    except Exception as e:
        return json_error("categorize_transaction", e)


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
    if is_read_only():
        return read_only_refusal("update_transaction_notes")
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
    if is_read_only():
        return read_only_refusal("mark_transaction_reviewed")
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
    dry_run: bool = False,
) -> str:
    """
    Apply the same category to multiple transactions at once.

    This is useful for categorizing similar transactions in bulk,
    such as all purchases from the same merchant.

    Args:
        transaction_ids: List of transaction IDs to categorize
        category_id: The category ID to apply to all transactions
        mark_reviewed: Whether to also mark transactions as reviewed (default: True)
        dry_run: If True, return what would be updated without making changes

    Returns:
        Summary of results including success/failure counts. When dry_run is
        True, the response includes a "dry_run" flag and the planned updates.
    """
    try:
        if dry_run:
            return json_success({
                "dry_run": True,
                "total": len(transaction_ids),
                "transaction_ids": list(transaction_ids),
                "category_id": category_id,
                "mark_reviewed": mark_reviewed,
            })

        if is_read_only():
            return read_only_refusal("bulk_categorize_transactions")

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
                results["errors"].append(
                    {
                        "transaction_id": txn_id,
                        "error": str(outcome),
                    }
                )
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
    if is_read_only():
        return read_only_refusal("delete_transaction")
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
                "stream": (
                    {
                        "id": item.get("stream", {}).get("id"),
                        "frequency": item.get("stream", {}).get("frequency"),
                        "amount": item.get("stream", {}).get("amount"),
                        "is_approximate": item.get("stream", {}).get(
                            "isApproximate", False
                        ),
                        "merchant": (
                            item.get("stream", {}).get("merchant", {}).get("name")
                            if item.get("stream", {}).get("merchant")
                            else None
                        ),
                    }
                    if item.get("stream")
                    else None
                ),
                "category": (
                    item.get("category", {}).get("name")
                    if item.get("category")
                    else None
                ),
                "account": (
                    item.get("account", {}).get("displayName")
                    if item.get("account")
                    else None
                ),
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
