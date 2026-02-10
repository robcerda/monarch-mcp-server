"""Backward-compatibility shim.

All tools have been moved to ``monarch_mcp_server.tools.*``.
This module re-exports every public name so that existing imports
(``from monarch_mcp_server.server import get_accounts``) and the
``mcp run`` entry point keep working.
"""

# Re-export core objects
from monarch_mcp_server.app import mcp, main, app  # noqa: F401
from monarch_mcp_server.client import get_monarch_client  # noqa: F401

# Re-export all tool functions
from monarch_mcp_server.tools.auth import (  # noqa: F401
    setup_authentication,
    authenticate_with_google,
    check_auth_status,
    debug_session_loading,
)
from monarch_mcp_server.tools.accounts import (  # noqa: F401
    get_accounts,
    refresh_accounts,
    get_account_holdings,
    get_account_balance_history,
)
from monarch_mcp_server.tools.transactions import (  # noqa: F401
    get_transactions,
    search_transactions,
    get_transaction_details,
    create_transaction,
    update_transaction,
    set_transaction_category,
    update_transaction_notes,
    mark_transaction_reviewed,
    bulk_categorize_transactions,
    delete_transaction,
    get_recurring_transactions,
    get_transactions_needing_review,
)
from monarch_mcp_server.tools.summaries import (  # noqa: F401
    get_transactions_summary,
    get_spending_summary,
)
from monarch_mcp_server.tools.splits import (  # noqa: F401
    get_transaction_splits,
    split_transaction,
)
from monarch_mcp_server.tools.tags import (  # noqa: F401
    get_tags,
    set_transaction_tags,
    create_tag,
)
from monarch_mcp_server.tools.rules import (  # noqa: F401
    get_transaction_rules,
    create_transaction_rule,
    update_transaction_rule,
    delete_transaction_rule,
)
from monarch_mcp_server.tools.categories import (  # noqa: F401
    get_categories,
    get_category_groups,
)
from monarch_mcp_server.tools.budgets import (  # noqa: F401
    get_budgets,
    set_budget_amount,
)
from monarch_mcp_server.tools.financial import (  # noqa: F401
    get_cashflow,
    get_net_worth,
    get_net_worth_by_account_type,
)

if __name__ == "__main__":
    main()
