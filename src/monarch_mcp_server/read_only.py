"""Read-only mode controls for the Monarch MCP Server.

The server defaults to read-only: any tool that mutates remote Monarch state
or local authentication state must refuse to run unless the operator has
explicitly opted in by setting ``MONARCH_MCP_READ_ONLY`` to a falsey value
(``false``, ``0``, ``no``, ``off``).

Auth/session mutation tools that accept credentials or change stored auth
state are *hard*-disabled regardless of this flag — they can only be used
via the standalone ``login_setup.py`` terminal flow.
"""

from __future__ import annotations

import os

from monarch_mcp_server.helpers import json_success

ENV_VAR = "MONARCH_MCP_READ_ONLY"

_FALSEY = frozenset({"false", "0", "no", "off", "disable", "disabled"})


def is_read_only() -> bool:
    """Return True when the server is in read-only mode.

    Default is True. Only an explicit falsey value disables the guard.
    """
    raw = os.environ.get(ENV_VAR)
    if raw is None:
        return True
    return raw.strip().lower() not in _FALSEY


def read_only_refusal(tool_name: str) -> str:
    """JSON refusal payload for a mutation tool blocked by read-only mode."""
    return json_success(
        {
            "success": False,
            "read_only": True,
            "tool": tool_name,
            "error": (
                f"Refusing to run mutation tool '{tool_name}': server is in "
                "read-only mode. Set MONARCH_MCP_READ_ONLY=false to enable "
                "Monarch data mutations (not recommended)."
            ),
        }
    )


def auth_mutation_disabled(tool_name: str) -> str:
    """JSON refusal payload for an auth-mutation tool that is hard-disabled."""
    return json_success(
        {
            "success": False,
            "disabled": True,
            "tool": tool_name,
            "error": (
                f"MCP tool '{tool_name}' is disabled. Authentication and "
                "session mutation must be performed out-of-band via "
                "`python login_setup.py`; the MCP server no longer accepts "
                "credentials or modifies stored auth state."
            ),
        }
    )
