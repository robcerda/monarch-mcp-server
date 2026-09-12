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
    monkeypatch.setattr(app.mcp, "_session_manager", None)
    run = Mock()
    monkeypatch.setattr(app.mcp, "run", run)
    return run


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
    isolate_transport.assert_called_once_with(transport="streamable-http")
    assert (app.mcp.settings.host, app.mcp.settings.port) == ("0.0.0.0", 9000)
    security = app.mcp.settings.transport_security
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
    isolate_transport.assert_called_once_with(transport="streamable-http")
    assert (app.mcp.settings.host, app.mcp.settings.port) == ("0.0.0.0", 9001)
    security = app.mcp.settings.transport_security
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


def rpc_result(response):
    assert response.status_code == 200, response.text
    # Keep the production SSE response mode, rather than changing server settings.
    data = next(
        line[6:] for line in response.text.splitlines() if line.startswith("data: ")
    )
    return json.loads(data)["result"]


def test_http_initialize_list_and_call_tool(mock_monarch_client):
    app.main(["--transport", "http", "--host", "0.0.0.0"])
    with TestClient(
        app.mcp.streamable_http_app(), base_url="http://localhost:8000"
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
        ({"Host": "evil.example"}, 421),
        ({"Origin": "https://evil.example"}, 400),
        ({"Origin": "null"}, 400),
        ({"Origin": "http://localhost"}, 200),
        ({"Host": "localhost"}, 200),
    ],
)
def test_http_validates_host_and_origin(headers, status):
    app.main(["--transport", "http", "--host", "0.0.0.0"])
    with TestClient(
        app.mcp.streamable_http_app(), base_url="http://localhost:8000"
    ) as client:
        response = client.post("/mcp", headers={**HEADERS, **headers}, json=INITIALIZE)
        assert response.status_code == status


def test_http_allows_configured_remote_host_and_origin():
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
        app.mcp.streamable_http_app(), base_url="https://mcp.example.com"
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
