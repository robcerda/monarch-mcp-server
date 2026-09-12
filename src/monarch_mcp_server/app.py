"""FastMCP application instance and entry point."""

import argparse
import logging
import os

try:  # mcp >= 2.0 renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp < 2.0
    from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# The gql aiohttp transport logs full GraphQL requests/responses at INFO, which
# can include Monarch account payloads. Raise its floor to WARNING so those
# payloads are not written to logs. Transport-level errors still surface; drop
# this to INFO/DEBUG temporarily if you need to trace GraphQL traffic.
logging.getLogger("gql.transport.aiohttp").setLevel(logging.WARNING)

# Initialize FastMCP server
mcp = FastMCP("Monarch Money MCP Server")

# Must run before the tool modules are imported, since it works by wrapping
# mcp.tool() and registration happens at import time.
from monarch_mcp_server import read_only  # noqa: E402

read_only.install(mcp)

# Import tools package to trigger @mcp.tool() registration
import monarch_mcp_server.tools  # noqa: E402, F401

# Export for `mcp run`
app = mcp


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("port must be an integer") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _env_list(name: str) -> list[str]:
    return [
        value.strip() for value in os.environ.get(name, "").split(",") if value.strip()
    ]


def main(argv: list[str] | None = None) -> None:
    """Main entry point for the server."""
    parser = argparse.ArgumentParser(description="Monarch Money MCP Server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "http"),
        default=os.environ.get("MONARCH_MCP_TRANSPORT", "stdio"),
        help="MCP transport (env: MONARCH_MCP_TRANSPORT; default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MONARCH_MCP_HOST", "127.0.0.1"),
        help="HTTP bind address (env: MONARCH_MCP_HOST; default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=_port,
        default=os.environ.get("MONARCH_MCP_PORT", "8000"),
        help="HTTP port (env: MONARCH_MCP_PORT; default: 8000)",
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=None,
        help="Additional HTTP Host value, e.g. mcp.example.com (repeatable; "
        "env: MONARCH_MCP_ALLOWED_HOSTS, comma-separated)",
    )
    parser.add_argument(
        "--allowed-origin",
        action="append",
        default=None,
        help="Additional browser Origin, e.g. https://client.example.com (repeatable; "
        "env: MONARCH_MCP_ALLOWED_ORIGINS, comma-separated)",
    )
    args = parser.parse_args(argv)
    # argparse does not check choices for defaults supplied by the environment.
    if args.transport not in ("stdio", "streamable-http", "http"):
        parser.error("MONARCH_MCP_TRANSPORT must be stdio, streamable-http, or http")
    if not args.host.strip():
        parser.error("HTTP host must not be empty")

    if args.transport != "stdio":
        from mcp.server.transport_security import TransportSecuritySettings

        mcp.settings.host = args.host
        mcp.settings.port = args.port
        # Listening on all interfaces must not disable Host/Origin validation.
        # Remote clients explicitly allow their public hostname (including port).
        mcp.settings.transport_security = TransportSecuritySettings(
            allowed_hosts=[
                "localhost",
                "localhost:*",
                "127.0.0.1",
                "127.0.0.1:*",
                "[::1]",
                "[::1]:*",
                *(
                    args.allowed_host
                    if args.allowed_host is not None
                    else _env_list("MONARCH_MCP_ALLOWED_HOSTS")
                ),
            ],
            allowed_origins=[
                "http://localhost",
                "http://localhost:*",
                "http://127.0.0.1",
                "http://127.0.0.1:*",
                "http://[::1]",
                "http://[::1]:*",
                *(
                    args.allowed_origin
                    if args.allowed_origin is not None
                    else _env_list("MONARCH_MCP_ALLOWED_ORIGINS")
                ),
            ],
        )

    logger.info("Starting Monarch Money MCP Server (%s)...", args.transport)
    try:
        if args.transport == "stdio":
            mcp.run()
        else:
            mcp.run(transport="streamable-http")
    except Exception as e:
        logger.error(f"Failed to run server: {str(e)}")
        raise


if __name__ == "__main__":
    main()
