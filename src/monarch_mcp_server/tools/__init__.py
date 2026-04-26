"""Tool modules – importing this package registers all tools with the FastMCP instance."""

from monarch_mcp_server.tools import (  # noqa: F401
    auth,
    accounts,
    transactions,
    summaries,
    splits,
    tags,
    rules,
    categories,
    budgets,
    financial,
)
