"""Regression tests for mcp 1.x / 2.x import compatibility.

mcp 2.0 renamed FastMCP to MCPServer and moved Context alongside it. The
package supports both, so guard that here: a plain rename would silently
break the other major, which is how the original breakage happened.
"""


def test_app_exposes_server_instance():
    """The server instance imports and registers tools on either mcp major."""
    from monarch_mcp_server.app import mcp

    assert mcp is not None
    assert hasattr(mcp, "tool")
    assert hasattr(mcp, "run")


def test_context_is_importable():
    """Context resolves on either mcp major."""
    from monarch_mcp_server import auth

    assert auth.Context is not None


async def test_tools_are_registered():
    """Tool registration survives the import indirection."""
    from monarch_mcp_server.app import mcp

    tools = await mcp.list_tools()
    assert len(tools) > 0
