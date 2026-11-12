"""Real local MCP JSON-RPC smoke; no webhook secrets or provider calls."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import tempfile

from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.stdio import callback_app


def test_stdio_callback_receiver_exposes_only_token_bound_routes_not_unauthenticated_http_mcp():
    routes = {getattr(route, "path", "") for route in callback_app().routes}
    assert "/callbacks/{token}" in routes
    assert "/hooks/grokbot" in routes
    assert "/healthz" in routes
    assert "/mcp" not in routes
    assert "/sse" not in routes
    with TestClient(callback_app()) as client:
        assert client.get("/healthz").json() == {"ok": True}
        assert client.post("/mcp", json={}).status_code == 404


def test_real_grokbot_stdio_mcp_process_discover_and_status_without_webhook():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        environ = dict(os.environ)
        environ.update({
            "DB_PATH": str(Path(directory) / "runs.db"),
            "PORT": str(port),
            "PUBLIC_BASE_URL": f"http://127.0.0.1:{port}",
            "CURSOR_WEBHOOK_URL": "",
            "CURSOR_WEBHOOK_API_KEY": "",
            "MCP_API_KEY": "",
            "INBOUND_WEBHOOK_SECRET": "",
            "ALLOWED_HOSTS": "",
            "CLEANUP_INTERVAL_SECONDS": "0",
        })

        async def exercise():
            params = StdioServerParameters(
                command=sys.executable,
                args=[str(root / "scripts" / "grokbot-mcp-stdio.py")],
                env=environ,
                cwd=directory,
            )
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    available = {item.name for item in (await session.list_tools()).tools}
                    assert available == {
                        "bridge_status", "ask_grokbot", "wait_for_grokbot_answer",
                        "list_grokbot_runs", "get_grokbot_run", "cancel_run",
                        "list_grokbot_events", "get_grokbot_event",
                        "keymaster_local_inbox_status", "keymaster_request_owner_review",
                    }
                    output = await session.call_tool("bridge_status", {})
                    assert output.is_error is False
                    payload = json.loads(output.content[0].text)
                    assert payload["webhook_url_configured"] is False
                    assert payload["webhook_api_key_configured"] is False
                    response = await session.call_tool("keymaster_local_inbox_status", {})
                    assert response.is_error is False
                    inbox = json.loads(response.content[0].text)
                    assert inbox["status"] in ("available", "unavailable")
                    assert inbox["verifiedClient"] is False
                    assert inbox["authorizedCredentialUse"] is False
                    # Reject arbitrary action/credential-like values locally.
                    bad = await session.call_tool("keymaster_request_owner_review", {
                        "credential_id": "fictional_only",
                        "purpose": "This is not a credential",
                        "mode": "invoke",
                        "action": "https://example.invalid/key"
                    })
                    assert bad.is_error is False
                    refused = json.loads(bad.content[0].text)
                    assert refused["status"] == "rejected"
                    assert refused["authorizedCredentialUse"] is False
        asyncio.run(asyncio.wait_for(exercise(), timeout=20))
        assert (Path(directory) / "runs.db").is_file()
