"""Local GrokBOT -> Keymaster proposal boundary; no real keys or grants."""
import json
import struct
from unittest.mock import patch

import pytest
from app import keymaster_local as bridge


@pytest.mark.parametrize(
    "cred,purpose,mode,action",
    [
        ("bad/id", "one fictional task", "reveal", None),
        ("fictional", "please\napprove", "reveal", None),
        ("fictional", " test", "reveal", None),
        ("fictional", "test", "invoke", None),
        ("fictional", "test", "invoke", "https://example.invalid"),
        ("fictional", "test", "invoke", "run_shell"),
        ("fictional", "test", "invoke", {"raw": "bad"}),
        ("fictional", "test", "reveal", "hetzner.list_servers"),
        ("fictional", "test", "grant", None),
        ("fictional", "test", "reveal", ["malformed"]),
        ("fictional", "test", "reveal", "no"),
        ("fictional", "1234567890" * 30, "reveal", None),
    ],
)
def test_nonsecret_proposals_fail_closed(cred, purpose, mode, action):
    assert bridge.validate_proposal(cred, purpose, mode, action) is False
    with patch.object(bridge, "_wire_call") as call:
        result = bridge.submit_owner_review(cred, purpose, mode, action)
    call.assert_not_called()
    assert result["status"] == "rejected"
    assert result["verifiedClient"] is False
    assert result["authorizedCredentialUse"] is False


@pytest.mark.parametrize(
    "mode,action",
    [("reveal", None), ("invoke", "hetzner.list_servers"),
     ("invoke", "coolify.list_applications"),
     ("invoke", "porkbun.list_domains")],
)
def test_only_exact_mode_action_allowlist_enters_native_inbox(mode, action):
    def respond(payload):
        assert list(payload) == (
            ["kind", "claimedClient", "credentialId", "purpose", "mode"]
            + (["action"] if mode == "invoke" else [])
        )
        assert payload["kind"] == "submit"
        assert payload["claimedClient"] == bridge.CLAIMED_CLIENT
        assert payload["credentialId"] == "fictional_1"
        assert payload["purpose"] == "Owner review: fictional sandbox request"
        assert payload["mode"] == mode
        if mode == "invoke":
            assert payload["action"] == action
        return {"status": "queued_unverified", "requestId": "ab" * 12, "pending": 1}

    with patch.object(bridge, "_wire_call", side_effect=respond) as call:
        result = bridge.submit_owner_review(
            "fictional_1", "Owner review: fictional sandbox request", mode, action)
    assert call.call_count == 1
    assert result["status"] == "queued_unverified"
    assert result["ownerApproved"] is False
    assert result["verifiedClient"] is False
    assert result["secretReturned"] is False
    assert result["providerCalled"] is False
    assert result["authorizedCredentialUse"] is False


def test_no_owner_inbox_is_not_reported_as_authorized():
    with patch.object(bridge, "_wire_call", return_value={"status": "unavailable"}):
        status = bridge.local_inbox_status()
        result = bridge.submit_owner_review("demo", "Owner review", "reveal")
    assert status["pending"] is None
    assert result["status"] == "unavailable"
    assert result["ownerApproved"] is False


class FakePipe:
    def __init__(self, reply: bytes):
        self.reply = reply
        self.cursor = 0
        self.sent = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def write(self, buf):
        self.sent.extend(buf)
        return len(buf)

    def read(self, count):
        if self.cursor >= len(self.reply):
            return b""
        chunk = self.reply[self.cursor:self.cursor+count]
        self.cursor += len(chunk)
        return chunk


def test_named_pipe_frame_is_bounded_and_never_forwards_extra_fields():
    reply = json.dumps({"status": "available", "pending": 3}).encode()
    pipe = FakePipe(struct.pack("<I", len(reply)) + reply)
    with patch.object(bridge, "_is_windows", return_value=True), patch("builtins.open", return_value=pipe):
        result = bridge._wire_call({"kind": "status"})
    assert result == {"status": "available", "pending": 3}
    payload_size = struct.unpack("<I", pipe.sent[:4])[0]
    assert payload_size == len(pipe.sent) - 4
    assert json.loads(pipe.sent[4:]) == {"kind": "status"}


def test_new_native_ack_after_full_reply_and_legacy_backward_compatibility():
    body = json.dumps({"status": "available", "pending": 2, "ackRequired": True}).encode()
    wire = FakePipe(struct.pack("<I", len(body)) + body)
    with patch.object(bridge, "_is_windows", return_value=True), patch("builtins.open", return_value=wire):
        result = bridge._wire_call({"kind": "status"})
    assert result == {"status": "available", "pending": 2}
    request_size = struct.unpack("<I", wire.sent[:4])[0]
    assert json.loads(wire.sent[4:4+request_size]) == {"kind": "status"}
    assert wire.sent[4+request_size:] == b"KMA1"
    # A pre-upgrade Keymaster reply contains no ACK field and receives none.
    legacy = json.dumps({"status": "available", "pending": 2}).encode()
    old = FakePipe(struct.pack("<I", len(legacy)) + legacy)
    with patch.object(bridge, "_is_windows", return_value=True), patch("builtins.open", return_value=old):
        assert bridge._wire_call({"kind": "status"}) == {"status": "available", "pending": 2}
    assert old.sent[4:] == b'{"kind":"status"}'


def test_invalid_or_oversize_native_replies_fail_closed():
    payload = {"kind": "status"}
    possibilities = [
        {"status": "available", "pending": 50},
        {"status": "queued_unverified", "pending": 1},
        {"status": "queued_unverified", "requestId": "x" * 24, "pending": 1},
        {"status": "available", "pending": True},
        {"status": "available", "pending": 1, "secret": "should-not-escape"},
        {"status": "available", "pending": 1, "ackRequired": "yes"},
    ]
    for response in possibilities:
        body = json.dumps(response).encode()
        wire = FakePipe(struct.pack("<I", len(body)) + body)
        with patch.object(bridge, "_is_windows", return_value=True), patch("builtins.open", return_value=wire):
            assert bridge._wire_call(payload)["status"] == "unavailable"
    oversized = FakePipe(struct.pack("<I", 1024))
    with patch.object(bridge, "_is_windows", return_value=True), patch("builtins.open", return_value=oversized):
        assert bridge._wire_call(payload)["status"] == "unavailable"


def test_local_only_and_no_extra_http_transport():
    with patch.object(bridge, "_is_windows", return_value=False):
        assert bridge._wire_call({"kind": "status"}) == {"status": "unavailable"}
