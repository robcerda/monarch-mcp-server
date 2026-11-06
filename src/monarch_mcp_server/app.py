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

# Starlette redirects /mcp/ to /mcp at routing time, before the endpoint and so
# before the Host check, and it builds the Location header from the request's
# own Host. A request with Host: evil.example therefore got a 307 to
# http://evil.example/mcp, and a 307 preserves the method and body, which here
# means tool arguments. Behind the reverse proxy the README recommends, which
# passes the public Host through, a client configured with a trailing slash
# would resend its body to an attacker chosen host.
#
# mcp.run() builds the Starlette app internally, so the builder is wrapped
# rather than the run path, which leaves the transport selection untouched.
_build_streamable_http_app = mcp.streamable_http_app


def _streamable_http_app_without_slash_redirect(*args, **kwargs):  # type: ignore[no-untyped-def]
    # Arguments are forwarded: mcp 1.x builds the app with no arguments, but
    # 2.x passes the host and transport security through here, so swallowing
    # them would silently drop the Host/Origin validation.
    http_app = _build_streamable_http_app(*args, **kwargs)
    http_app.router.redirect_slashes = False
    return http_app


mcp.streamable_http_app = _streamable_http_app_without_slash_redirect

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


def _split_host_port(value: str) -> tuple[str, str | None]:
    """Split a Host value into host and port, honouring IPv6 brackets."""
    if value.startswith("["):
        closing = value.find("]")
        if closing == -1:
            return value, None
        host, rest = value[: closing + 1], value[closing + 1 :]
        if rest.startswith(":"):
            return host, rest[1:]
        return host, None
    host, separator, port = value.rpartition(":")
    if not separator:
        return value, None
    return host, port


def _allowed_host_forms(value: str) -> list[str]:
    """Expand one operator supplied Host value into allowlist entries.

    Upstream matches these with a case sensitive prefix test, which refuses
    hosts that are the same host written differently (see #156). Three
    normalisations here, none of which widen what is accepted to a different
    machine:

    - lowercased, since Host is case insensitive
    - a single trailing dot stripped, since the FQDN root form is the same host
    - a value given without a port also gets the ":*" form, so an operator who
      allows mcp.example.com accepts mcp.example.com:8443, the way the
      loopback defaults already accept a port

    A value that already carries a port is passed through unchanged, so an
    operator can still pin one exactly.
    """
    host, port = _split_host_port(value.strip())
    host = host.lower()
    if host.endswith(".") and not host.endswith(".."):
        host = host[:-1]
    if not host:
        return []
    if port is not None:
        return [f"{host}:{port}"]
    return [host, f"{host}:*"]


def _expand_allowed_hosts(values: list[str]) -> list[str]:
    """Flatten the operator supplied hosts, keeping order and dropping dupes."""
    out: list[str] = []
    for value in values:
        for form in _allowed_host_forms(value):
            if form not in out:
                out.append(form)
    return out


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

    run_kwargs: dict = {}
    if args.transport != "stdio":
        from mcp.server.transport_security import TransportSecuritySettings

        # Listening on all interfaces must not disable Host/Origin validation.
        # Remote clients explicitly allow their public hostname (including port).
        security = TransportSecuritySettings(
            allowed_hosts=[
                "localhost",
                "localhost:*",
                "127.0.0.1",
                "127.0.0.1:*",
                "[::1]",
                "[::1]:*",
                *_expand_allowed_hosts(
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
        # mcp 1.x reads host, port and transport_security off Settings. 2.x
        # removed those fields and takes them as run() keyword arguments
        # instead, so assigning them there raises. Pick by what the installed
        # Settings model actually declares rather than by version number.
        if "host" in type(mcp.settings).__pydantic_fields__:
            mcp.settings.host = args.host
            mcp.settings.port = args.port
            mcp.settings.transport_security = security
        else:
            run_kwargs = {
                "host": args.host,
                "port": args.port,
                "transport_security": security,
            }

    logger.info("Starting Monarch Money MCP Server (%s)...", args.transport)
    try:
        if args.transport == "stdio":
            mcp.run()
        else:
            mcp.run(transport="streamable-http", **run_kwargs)
    except Exception as e:
        logger.error(f"Failed to run server: {str(e)}")
        raise


if __name__ == "__main__":
    main()
