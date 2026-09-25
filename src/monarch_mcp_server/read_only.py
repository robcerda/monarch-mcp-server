"""Opt in read only mode.

Set ``MONARCH_MCP_READ_ONLY`` to a truthy value and the mutating tools are
never registered, so they do not appear in the tool list and cannot be called
at all. This is stronger than relying on client side approval prompts: a tool
that is not registered cannot be invoked by a model that was talked into it by
a merchant name or memo it read back, which is the threat the README's
approval section is about.

Read only is off by default. Enabling it is a deliberate choice, so existing
setups keep working exactly as before.
"""

import logging
import os
from typing import Any, Callable, FrozenSet, TypeVar

from mcp.types import ToolAnnotations

logger = logging.getLogger(__name__)

ENV_VAR = "MONARCH_MCP_READ_ONLY"

_TRUTHY = frozenset({"1", "true", "t", "yes", "y", "on"})

# Every registered tool that writes. Listed explicitly rather than matched by
# name prefix: this is a security control, and a tool silently failing to be
# recognised as mutating would defeat the whole point.
MUTATING_TOOLS: FrozenSet[str] = frozenset(
    {
        # Transactions
        "create_transaction",
        "update_transaction",
        "delete_transaction",
        "categorize_transaction",
        "update_transaction_notes",
        "mark_transaction_reviewed",
        "bulk_categorize_transactions",
        "split_transaction",
        "upload_account_balance_history",
        # Tags
        "set_transaction_tags",
        "add_transaction_tag",
        "create_transaction_tag",
        # Rules
        "create_transaction_rule",
        "update_transaction_rule",
        "delete_transaction_rule",
        "reorder_transaction_rule",
        # Categories and budgets
        "create_transaction_category",
        "update_category",
        "set_budget_amount",
        # Goals
        "update_savings_goal",
        "set_goal_contribution",
        # Merchants
        "update_merchant",
        "review_recurring_stream",
        # Session mutation. Logging out or replacing the stored session is a
        # change to durable state, and a read only deployment should not be
        # able to do it either.
        "monarch_login",
        "monarch_login_with_token",
        "monarch_logout",
        # Accounts
        "update_account",
        # Side effecting: posts a refresh request to the institutions.
        "refresh_accounts",
    }
)

F = TypeVar("F", bound=Callable[..., Any])


def is_read_only() -> bool:
    """Whether read only mode is enabled for this process."""
    return os.environ.get(ENV_VAR, "").strip().lower() in _TRUTHY


def annotations_for(name: str) -> ToolAnnotations:
    """MCP tool hints derived from MUTATING_TOOLS, so clients can tell reads from writes."""
    if name in MUTATING_TOOLS:
        return ToolAnnotations(readOnlyHint=False, destructiveHint=True)
    return ToolAnnotations(readOnlyHint=True)


def install(mcp: Any) -> None:
    """Wrap ``mcp.tool()`` to annotate every tool and, in read only mode, skip
    mutating ones.

    Wrapping registration is what keeps this change small: every tool module
    already registers through ``@mcp.tool()``, so nothing else has to know
    about read only mode or annotations, and the decorated function is still
    returned so the re-exports in ``server.py`` keep working.
    """
    read_only = is_read_only()
    original_tool = mcp.tool

    def guarded_tool(*args: Any, **kwargs: Any) -> Callable[[F], F]:
        def decorator(fn: F) -> F:
            # FastMCP.tool() takes `name` as its first positional parameter, so
            # @mcp.tool("some_name") must be honoured too. Comparing only
            # fn.__name__ would let a renamed mutating tool through the gate.
            positional = args[0] if args and isinstance(args[0], str) else None
            name = positional or kwargs.get("name") or getattr(fn, "__name__", "")
            if read_only and name in MUTATING_TOOLS:
                logger.info("Read only mode: not registering %s", name)
                return fn
            register = original_tool(
                *args, **{**kwargs, "annotations": annotations_for(str(name))}
            )
            return register(fn)  # type: ignore[no-any-return]

        # Support bare `@mcp.tool` (no call) as well as `@mcp.tool(...)`.
        if len(args) == 1 and callable(args[0]) and not kwargs:
            # Route through the no-arg form so the function is not forwarded
            # to original_tool as the positional `name`.
            return guarded_tool()(args[0])  # type: ignore[return-value]
        return decorator

    mcp.tool = guarded_tool  # type: ignore[method-assign]
    if read_only:
        logger.warning(
            "%s is set: %d mutating tools will not be registered",
            ENV_VAR,
            len(MUTATING_TOOLS),
        )
