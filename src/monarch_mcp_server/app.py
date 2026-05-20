"""FastMCP application instance and entry point."""

import logging

from mcp.server.fastmcp import FastMCP

from monarch_mcp_server.read_only import ENV_VAR, is_read_only

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("Monarch Money MCP Server")

# Import tools package to trigger @mcp.tool() registration
import monarch_mcp_server.tools  # noqa: E402, F401

# Export for `mcp run`
app = mcp


def main() -> None:
    """Main entry point for the server."""
    logger.info("Starting Monarch Money MCP Server...")
    if is_read_only():
        logger.info(
            "Read-only mode active (%s unset or truthy). All Monarch data "
            "mutations are refused.",
            ENV_VAR,
        )
    else:
        logger.warning(
            "Read-only mode DISABLED via %s. Monarch data mutations are "
            "permitted by tools that explicitly opt in.",
            ENV_VAR,
        )
    try:
        mcp.run()
    except Exception as e:
        logger.error(f"Failed to run server: {str(e)}")
        raise


if __name__ == "__main__":
    main()
