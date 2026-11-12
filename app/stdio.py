"""Local stdio MCP entrypoint with a loopback-only webhook callback receiver.

Use this when a local AI host wants to call Grok Bot as an MCP tool without
running a remote MCP *server*. Grok Bot itself still needs its Cursor webhook;
the callback must be reachable via an explicitly configured public HTTPS
reverse proxy/tunnel to this loopback listener.

No credential values or API keys are accepted as MCP tool arguments.
Remote Keymaster's Windows pipe is NOT exposed here.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path


def _choose_local_db() -> None:
    """Keep the unconfigured local stdio run store outside git checkout."""
    if os.getenv("DB_PATH"):
        return
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        state = base / "GrokBOTMCPBridge"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
        state = base / "grokbot-mcp-bridge"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.environ["DB_PATH"] = str(state / "bridge.db")


# Must precede importing app.config, which freezes its environment fields.
_choose_local_db()

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from app import config, tools  # noqa: E402,F401 — register all existing MCP tools
from app.mcp_app import mcp  # noqa: E402
from app.routes import register_routes  # noqa: E402


def callback_app() -> FastAPI:
    """The only HTTP listener is for signed Grok Bot events / run callbacks.

    No HTTP MCP is installed in this app. The MCP API is on STDIO only.
    The callback routes reuse the existing bounded/token-aware implementation.
    """
    application = FastAPI()
    register_routes(application, stdio_callback_only=True)
    return application


async def serve_stdio() -> None:
    if mcp is None:
        raise RuntimeError("MCP SDK is required for local stdio mode")
    # Never expose a token-auth callback listener on a public interface from
    # an AI-host launch. Public routing, if wanted, is owner-configured
    # HTTPS ingress terminating at this loopback port.
    server = uvicorn.Server(uvicorn.Config(
        callback_app(), host="127.0.0.1", port=config.PORT,
        log_level="warning", access_log=False,
    ))
    receiver = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            if receiver.done():
                raise RuntimeError("GrokBOT callback listener could not start")
            await asyncio.sleep(0.025)
        else:
            raise RuntimeError("GrokBOT callback listener startup timed out")
        # STDOUT is reserved exclusively for MCP JSON-RPC.
        await mcp.run_stdio_async()
    finally:
        server.should_exit = True
        await receiver


def main() -> None:
    asyncio.run(serve_stdio())


if __name__ == "__main__":
    main()
