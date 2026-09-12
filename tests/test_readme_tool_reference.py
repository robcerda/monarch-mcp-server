"""The README tool table is the contract an LLM plans against.

A wrong tool name fails loudly, but a wrong parameter name tends to fail
quietly: the filter the user asked for simply does not get applied and the
over broad result still looks like a valid answer. These tests check the
table against the live registry so it cannot drift again.
"""

import inspect
import re
from pathlib import Path

import pytest

from monarch_mcp_server import server as srv
from monarch_mcp_server.app import mcp

README = Path(__file__).resolve().parent.parent / "README.md"
ROW = re.compile(
    r"^\|[ \t]*`(?P<name>\w+)`[ \t]*\|[^|\r\n]*\|(?P<params>[^|\r\n]*)\|[ \t]*$",
    re.M,
)


@pytest.mark.parametrize("padding", ["", " ", "    "])
def test_tool_rows_allow_column_alignment(padding):
    row = f"|{padding}`get_accounts`{padding}|{padding}List accounts{padding}|{padding}None{padding}|"
    match = ROW.fullmatch(row)
    assert match is not None
    assert match.group("name") == "get_accounts"
    assert match.group("params").strip() == "None"


def _documented():
    return {m.group("name"): m.group("params") for m in ROW.finditer(README.read_text())}


async def _registered():
    return {t.name for t in await mcp.list_tools()}


async def test_every_documented_tool_exists():
    documented, registered = set(_documented()), await _registered()
    assert not (documented - registered), (
        "README documents tools that are not registered: "
        f"{sorted(documented - registered)}"
    )


async def test_every_registered_tool_is_documented():
    documented, registered = set(_documented()), await _registered()
    assert not (registered - documented), (
        f"tools missing from the README table: {sorted(registered - documented)}"
    )


async def test_every_tool_is_re_exported_from_server():
    """server.py re-exports every tool for backward compatible imports.

    This also keeps the parameter check below honest: it resolves functions
    through server.py, so a tool missing here would be skipped rather than
    checked, and its README row could say anything.
    """
    missing = sorted(n for n in await _registered() if not hasattr(srv, n))
    assert not missing, f"tools not re-exported from server.py: {missing}"


async def test_documented_parameters_match_the_signatures():
    mismatches = []
    for name, params in _documented().items():
        fn = getattr(srv, name, None)
        if fn is None:
            continue
        actual = [
            p.name
            for p in inspect.signature(fn).parameters.values()
            if p.name != "ctx"
        ]
        listed = (
            []
            if params.strip() == "None"
            else [p.strip().strip("?").strip("`") for p in params.split(",")]
        )
        if listed != actual:
            mismatches.append((name, listed, actual))
    assert not mismatches, f"README parameters out of sync: {mismatches}"


async def test_approval_list_covers_every_mutating_tool():
    """The approval section exists because the model reads back data it did
    not author. A mutating tool missing from it is the whole risk."""
    text = README.read_text()
    section = text[text.index("### Recommended: require approval") :]
    registered = await _registered()
    mutating = {
        n
        for n in registered
        if n.split("_")[0]
        in {"create", "update", "delete", "set", "add", "split", "bulk", "mark"}
        or n in {"upload_account_balance_history", "categorize_transaction",
                 "review_recurring_stream", "monarch_login", "monarch_logout",
                 "monarch_login_with_token"}
    }
    missing = {n for n in mutating if f"`{n}`" not in section}
    assert not missing, f"mutating tools missing from the approval list: {sorted(missing)}"
