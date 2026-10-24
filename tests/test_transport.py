"""Transport selection and real MCP requests through the HTTP ASGI application."""

import json
from unittest.mock import Mock

import pytest
from starlette.testclient import TestClient

from monarch_mcp_server import app


@pytest.fixture(autouse=True)
def isolate_transport(monkeypatch):
    for suffix in ("TRANSPORT", "HOST", "PORT", "ALLOWED_HOSTS", "ALLOWED_ORIGINS"):
        monkeypatch.delenv(f"MONARCH_MCP_{suffix}", raising=False)
    monkeypatch.setattr(app.mcp, "settings", app.mcp.settings.model_copy(deep=True))
    # mcp 1.x caches the session manager on the server as _session_manager and
    # reuses it, so it has to be cleared between tests. 2.x exposes it as a
    # read-only property on the low-level server and builds one per app, so
    # there is nothing to clear. Checking the instance dict rather than
    # hasattr matters: in 1.x the session_manager property raises when it has
    # not been built yet, and hasattr propagates that.
    if "_session_manager" in vars(app.mcp):
        monkeypatch.setattr(app.mcp, "_session_manager", None)
    run = Mock()
    monkeypatch.setattr(app.mcp, "run", run)
    return run


def applied_http_config(run_mock):
    """Where the host, port and transport security ended up.

    mcp 1.x reads them off mcp.settings; 2.x takes them as run() keyword
    arguments. The tests care that main() applied them, not which API the
    installed version exposes.
    """
    kwargs = run_mock.call_args.kwargs
    if "host" in kwargs:
        return kwargs["host"], kwargs["port"], kwargs["transport_security"]
    settings = app.mcp.settings
    return settings.host, settings.port, settings.transport_security


def test_default_remains_stdio(isolate_transport):
    app.main([])
    isolate_transport.assert_called_once_with()


def test_environment_configures_http(monkeypatch, isolate_transport):
    monkeypatch.setenv("MONARCH_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MONARCH_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("MONARCH_MCP_PORT", "9000")
    monkeypatch.setenv(
        "MONARCH_MCP_ALLOWED_HOSTS", "mcp.example.com, server.lan:9000, "
    )
    monkeypatch.setenv("MONARCH_MCP_ALLOWED_ORIGINS", "https://client.example.com")
    app.main([])
    assert isolate_transport.call_args.kwargs["transport"] == "streamable-http"
    host, port, security = applied_http_config(isolate_transport)
    assert (host, port) == ("0.0.0.0", 9000)
    assert security.enable_dns_rebinding_protection
    assert "server.lan:9000" in security.allowed_hosts
    assert "https://client.example.com" in security.allowed_origins


def test_cli_overrides_environment(monkeypatch, isolate_transport):
    monkeypatch.setenv("MONARCH_MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("MONARCH_MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MONARCH_MCP_PORT", "invalid")
    monkeypatch.setenv("MONARCH_MCP_ALLOWED_HOSTS", "old.example.com")
    monkeypatch.setenv("MONARCH_MCP_ALLOWED_ORIGINS", "https://old.example.com")
    app.main(
        [
            "--transport",
            "http",
            "--host",
            "0.0.0.0",
            "--port",
            "9001",
            "--allowed-host",
            "mcp.example.com",
            "--allowed-host",
            "server.lan:9001",
            "--allowed-origin",
            "https://client.example.com",
        ]
    )
    assert isolate_transport.call_args.kwargs["transport"] == "streamable-http"
    host, port, security = applied_http_config(isolate_transport)
    assert (host, port) == ("0.0.0.0", 9001)
    assert "mcp.example.com" in security.allowed_hosts
    assert "server.lan:9001" in security.allowed_hosts
    assert "old.example.com" not in security.allowed_hosts
    assert "https://client.example.com" in security.allowed_origins
    assert "https://old.example.com" not in security.allowed_origins


def test_stdio_overrides_container_default(monkeypatch, isolate_transport):
    monkeypatch.setenv("MONARCH_MCP_TRANSPORT", "streamable-http")
    app.main(["--transport", "stdio"])
    isolate_transport.assert_called_once_with()


@pytest.mark.parametrize("port", ["0", "65536", "-1", "invalid"])
def test_invalid_environment_port_fails(monkeypatch, isolate_transport, port):
    monkeypatch.setenv("MONARCH_MCP_PORT", port)
    with pytest.raises(SystemExit) as exc:
        app.main([])
    assert exc.value.code == 2
    isolate_transport.assert_not_called()


def test_invalid_environment_transport_fails(monkeypatch, isolate_transport):
    monkeypatch.setenv("MONARCH_MCP_TRANSPORT", "invalid")
    with pytest.raises(SystemExit) as exc:
        app.main([])
    assert exc.value.code == 2
    isolate_transport.assert_not_called()


HEADERS = {"Accept": "application/json, text/event-stream"}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "transport-test", "version": "1.0"},
    },
}


# mcp 1.x configures the HTTP app from global settings; 2.x takes the same
# values as run() keyword arguments, so build_http_app forwards them.
#
# The rejection codes are upstream's to choose and have moved: a forged Host
# is 421 throughout, while a refused Origin was 400 up to about mcp 1.13 and
# is 403 by 1.30 and on 2.x. The property under test is that the request is
# refused, so both codes are accepted rather than pinning the suite to one
# release's choice.
REJECTED_HOST = (421,)
REJECTED_ORIGIN = (400, 403)
ACCEPTED = (200,)


def build_http_app(run_mock):
    """Build the ASGI app the way the installed version's run() would.

    Without this, 2.x would come up with default Host/Origin rules instead of
    the ones main() computed, and the validation tests would prove nothing.
    """
    kwargs = dict(run_mock.call_args.kwargs)
    kwargs.pop("transport", None)
    kwargs.pop("port", None)  # bind time only, not an app argument
    return app.mcp.streamable_http_app(**kwargs)


def rpc_result(response):
    assert response.status_code == 200, response.text
    # Keep the production SSE response mode, rather than changing server settings.
    data = next(
        line[6:] for line in response.text.splitlines() if line.startswith("data: ")
    )
    return json.loads(data)["result"]


def test_http_initialize_list_and_call_tool(mock_monarch_client, isolate_transport):
    app.main(["--transport", "http", "--host", "0.0.0.0"])
    with TestClient(
        build_http_app(isolate_transport), base_url="http://localhost:8000"
    ) as client:
        response = client.post("/mcp", headers=HEADERS, json=INITIALIZE)
        assert rpc_result(response)["serverInfo"]["name"] == "Monarch Money MCP Server"
        headers = {**HEADERS, "Mcp-Session-Id": response.headers["mcp-session-id"]}
        initialized = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )
        assert initialized.status_code == 202
        listed = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
        assert "get_accounts" in {tool["name"] for tool in rpc_result(listed)["tools"]}
        called = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_accounts", "arguments": {}},
            },
        )
        result = rpc_result(called)
        assert not result.get("isError")
        assert "Checking Account" in result["content"][0]["text"]
        mock_monarch_client.get_accounts.assert_awaited_once()
        assert client.delete("/mcp", headers=headers).status_code == 200


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"Host": "evil.example"}, REJECTED_HOST),
        ({"Origin": "https://evil.example"}, REJECTED_ORIGIN),
        ({"Origin": "null"}, REJECTED_ORIGIN),
        ({"Origin": "http://localhost"}, ACCEPTED),
        ({"Host": "localhost"}, ACCEPTED),
    ],
)
def test_http_validates_host_and_origin(headers, status, isolate_transport):
    app.main(["--transport", "http", "--host", "0.0.0.0"])
    with TestClient(
        build_http_app(isolate_transport), base_url="http://localhost:8000"
    ) as client:
        response = client.post("/mcp", headers={**HEADERS, **headers}, json=INITIALIZE)
        assert response.status_code in status


def test_http_allows_configured_remote_host_and_origin(isolate_transport):
    app.main(
        [
            "--transport",
            "http",
            "--allowed-host",
            "mcp.example.com",
            "--allowed-origin",
            "https://client.example.com",
        ]
    )
    with TestClient(
        build_http_app(isolate_transport), base_url="https://mcp.example.com"
    ) as client:
        response = client.post(
            "/mcp",
            json=INITIALIZE,
            headers={
                **HEADERS,
                "Origin": "https://client.example.com",
            },
        )
        assert "serverInfo" in rpc_result(response)
