"""NONSECRET local Keymaster inbox proposal adapter for the stdio MCP host.

Only on the Windows machine running native Keymaster; NEVER registered in the
remote HTTP/SSE GrokBOT bridge. The native pipe is an UNTRUSTED proposal inbox,
not a privileged credential broker, an owner approval path, or identity proof.
"""
from __future__ import annotations

import json
import os
import re
import struct
from typing import Any

PIPE_NAME = r"\\.\pipe\KeymasterNonsecretRequestV1"
MAX_FRAME_BYTES = 640
MAX_PENDING = 24
# This is the bridge's DISPLAY LABEL, never an authenticated identity.
CLAIMED_CLIENT = "GrokBOT local MCP (UNVERIFIED)"
ALLOWED_ACTIONS = frozenset((
    "hetzner.list_servers", "coolify.list_applications", "porkbun.list_domains"
))
RECEIPT_PATTERN = re.compile(r"[a-f0-9]{24}\Z")
ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")


def _safe_label(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value.encode("utf-8")) <= maximum
        and value == value.strip()
        and all(
            ch.isprintable() and ch not in "<>{}\\"
            for ch in value
        )
    )


def validate_proposal(
    credential_id: object,
    purpose: object,
    mode: object,
    action: object = None,
) -> bool:
    """Mirror Rust's exact nonsecret inbound allowlist, fail closed."""
    return (
        isinstance(credential_id, str)
        and ID_PATTERN.fullmatch(credential_id) is not None
        and _safe_label(purpose, 180)
        and (
            (mode == "reveal" and action is None)
            or (mode == "invoke" and isinstance(action, str) and action in ALLOWED_ACTIONS)
        )
    )


def _read_exact(wire: Any, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = wire.read(length - len(data))
        if not chunk:
            raise OSError("local pipe closed before completing a frame")
        data.extend(chunk)
    return bytes(data)


def _is_windows() -> bool:
    return os.name == "nt"


def _wire_call(payload: dict[str, object]) -> dict[str, object]:
    if not _is_windows():
        return {"status": "unavailable"}
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if not 0 < len(encoded) <= MAX_FRAME_BYTES:
        return {"status": "rejected"}

    try:
        with open(PIPE_NAME, "r+b", buffering=0) as wire:
            wire.write(struct.pack("<I", len(encoded)) + encoded)
            head = _read_exact(wire, 4)
            size = struct.unpack("<I", head)[0]
            if not 0 < size <= MAX_FRAME_BYTES:
                return {"status": "unavailable"}
            body = _read_exact(wire, size)
            answer = json.loads(body)
            # New Keymaster instances require a four-byte nonsecret delivery
            # ACK after the entire bounded reply has been read and decoded.
            # Older running desktop builds do not advertise it.
            if isinstance(answer, dict) and answer.get("ackRequired") is True:
                wire.write(b"KMA1")
        if isinstance(answer, dict):
            ack_flag = answer.pop("ackRequired", None)
            if ack_flag is not None and ack_flag is not True:
                return {"status": "unavailable"}
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return {"status": "unavailable"}

    if not isinstance(answer, dict) or answer.get("status") not in (
        "available", "queued_unverified", "rejected", "full", "unavailable"
    ):
        return {"status": "unavailable"}
    if not set(answer).issubset({"status", "requestId", "pending"}):
        return {"status": "unavailable"}
    receipt = answer.get("requestId")
    if receipt is not None and (
        not isinstance(receipt, str) or RECEIPT_PATTERN.fullmatch(receipt) is None
    ):
        return {"status": "unavailable"}
    pending = answer.get("pending")
    if pending is not None and (
        not isinstance(pending, int) or isinstance(pending, bool)
        or not 0 <= pending <= MAX_PENDING
    ):
        return {"status": "unavailable"}
    if answer["status"] == "queued_unverified" and (
        receipt is None or pending is None
    ):
        return {"status": "unavailable"}
    if answer["status"] == "available" and pending is None:
        return {"status": "unavailable"}
    return answer


def local_inbox_status() -> dict[str, object]:
    """Count-only native inbox query; never reveals proposal identities."""
    answer = _wire_call({"kind": "status"})
    return {
        "status": answer["status"] if answer["status"] == "available" else "unavailable",
        "pending": answer.get("pending") if answer["status"] == "available" else None,
        "localWindowsOnly": True,
        "verifiedClient": False,
        "authorizedCredentialUse": False,
    }


def submit_owner_review(
    credential_id: object, purpose: object, mode: object,
    action: object = None,
) -> dict[str, object]:
    """Submit an ephemeral *unverified* proposal; no owner grant or secret."""
    if not validate_proposal(credential_id, purpose, mode, action):
        return {
            "status": "rejected",
            "reason": "INVALID_NONSECRET_REQUEST_FIELDS",
            "verifiedClient": False,
            "authorizedCredentialUse": False,
        }

    request: dict[str, object] = {
        "kind": "submit",
        "claimedClient": CLAIMED_CLIENT,
        "credentialId": credential_id,
        "purpose": purpose,
        "mode": mode,
    }
    if mode == "invoke":
        request["action"] = action
    answer = _wire_call(request)
    result: dict[str, object] = {
        "status": answer["status"],
        "verifiedClient": False,
        "authorizedCredentialUse": False,
        "ownerApproved": False,
        "secretReturned": False,
        "providerCalled": False,
    }
    if answer["status"] == "queued_unverified":
        result["requestId"] = answer["requestId"]
        result["pending"] = answer["pending"]
    return result


def register_local_keymaster_tools(mcp: Any) -> None:
    """Register only in the standalone LOCAL stdio process (never HTTP)."""
    if mcp is None:
        raise RuntimeError("MCP SDK missing")

    @mcp.tool(structured_output=False)
    async def keymaster_local_inbox_status() -> str:
        """Check the local Windows owner inbox's count. No identities or keys."""
        import asyncio
        return json.dumps(await asyncio.to_thread(local_inbox_status))

    @mcp.tool(structured_output=False)
    async def keymaster_request_owner_review(
        credential_id: str,
        purpose: str,
        mode: str,
        action: str | None = None,
    ) -> str:
        """Propose NONSECRET credential access to the Windows Keymaster owner.

        Caller name is FIXED to a GrokBOT-local MCP *unverified* display label.
        This does NOT authenticate GrokBOT or the calling AI, approve a grant,
        reveal a key, execute a provider operation or persist authority.
        Choose mode='reveal' only to propose Mode 1 (no action); mode='invoke'
        must use the exact read-only provider action allowlist.
        Put NO credentials, passwords, tokens, URLs or account data in purpose.
        A queued request means only that the owner inbox received the proposal.
        """
        import asyncio
        from app.rate_limit import check_write_limit, rate_limited_payload
        if not validate_proposal(credential_id, purpose, mode, action):
            return json.dumps(submit_owner_review(credential_id, purpose, mode, action))
        allowed, retry_after = check_write_limit()
        if not allowed:
            return json.dumps(rate_limited_payload(retry_after))
        return json.dumps(await asyncio.to_thread(
            submit_owner_review, credential_id, purpose, mode, action
        ))
