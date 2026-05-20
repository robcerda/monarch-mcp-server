"""Authentication helpers — DISABLED for MCP transport.

The previous implementation used MCP elicitation to collect Monarch Money
credentials over the protocol. That flow has been removed: credentials must
not flow through the MCP transport, and the server must not be able to
mutate stored auth state on behalf of a remote client.

To authenticate, run ``python login_setup.py`` from a terminal. The
standalone script writes a session token to the system keyring; the MCP
server reads it on subsequent calls but never modifies it.
"""

from __future__ import annotations


class AuthDisabledError(RuntimeError):
    """Raised if any code path tries to invoke MCP-side login/logout."""


def _disabled(name: str) -> AuthDisabledError:
    return AuthDisabledError(
        f"{name} is disabled. Use `python login_setup.py` to manage the "
        "Monarch Money session out-of-band."
    )


async def login_interactive(*_args, **_kwargs) -> str:
    raise _disabled("login_interactive")


async def login_with_token_interactive(*_args, **_kwargs) -> str:
    raise _disabled("login_with_token_interactive")


async def logout(*_args, **_kwargs) -> str:
    raise _disabled("logout")
