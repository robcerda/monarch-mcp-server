"""Check the installed library, which conftest replaces with a mock in-process."""

import subprocess
import sys
import textwrap


def test_installed_library_supports_transaction_ownership():
    # A fresh interpreter bypasses conftest's sys.modules mocks. Importing and
    # inspecting the class needs neither credentials nor a network request.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import inspect
                from monarchmoney import MonarchMoney

                lookup = getattr(MonarchMoney, "get_household_members", None)
                assert inspect.iscoroutinefunction(lookup), (
                    "Installed monarchmoneycommunity lacks get_household_members; "
                    "update the dependency and both lockfiles to a release containing PR #80"
                )
                inspect.signature(lookup).bind(None)
                update = inspect.signature(MonarchMoney.update_transaction)
                assert "owner_user_id" in update.parameters, (
                    "Installed monarchmoneycommunity lacks update_transaction(owner_user_id)"
                )
                assert update.parameters["owner_user_id"].default is None
                for owner in ("member-id", "", None):
                    update.bind(None, "transaction-id", owner_user_id=owner)
            """
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
