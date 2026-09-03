from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from aie_runtime.engine import AuthorityLease, Mission, Principal
from aie_runtime.gateway.cli import build_server_options_from_config
from aie_runtime.gateway.core import AIEGateway
from aie_runtime.gateway.durable import SQLiteGatewayStore
from aie_runtime.gateway.forwarding import HTTPUpstreamForwarder
from aie_runtime.gateway.http import create_http_server
from aie_runtime.gateway.policy import LocalPolicyAdapter
from aie_runtime.gateway.protocols.a2a_http_json import normalize_a2a_http_json_request
from aie_runtime.store import InMemoryState

NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)


class CaptureUpstream(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def log_message(self, format, *args):
        return

    def _capture(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        type(self).calls.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": raw,
            }
        )
        payload = json.dumps({"ok": True, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _capture
    do_POST = _capture


def make_gateway(tmp_path, *, tenant: str | None = None):
    state = InMemoryState()
    spiffe = "spiffe://example.org/agent/a"
    state.principals["p"] = Principal("p", "agent", spiffe)
    state.missions["m"] = Mission("m", "active")
    if tenant:
        prefixes = (f"a2a://tenant/{tenant}/",)
    else:
        prefixes = ("a2a://message/", "a2a://task")
    state.leases["l"] = AuthorityLease(
        "l",
        "p",
        "m",
        {"a2a.message.send", "a2a.task.get", "a2a.task.list", "a2a.task.cancel"},
        prefixes,
        NOW + timedelta(hours=1),
        100,
    )
    return AIEGateway(
        state=state,
        store=SQLiteGatewayStore(tmp_path / "gateway.db"),
        policy=LocalPolicyAdapter(lambda _: True),
        clock=lambda: NOW,
        authority_bindings={spiffe: ("m", "l")},
    )


def headers():
    return {
        "Content-Type": "application/json",
        "A2A-Version": "1.0",
        "X-AIE-Verified-Spiffe-ID": "spiffe://example.org/agent/a",
        "X-AIE-Identity-Verified": "true",
        "A2A-Extensions": "https://example.org/ext",
        "AIE-Secret": "must-not-forward",
    }


def request(base: str, method: str, path: str, body=None):
    raw = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=raw, headers=headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def start_stack(tmp_path, *, tenant=None):
    CaptureUpstream.calls = []
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), CaptureUpstream)
    ut = threading.Thread(target=upstream.serve_forever, daemon=True)
    ut.start()
    gateway = create_http_server(
        make_gateway(tmp_path, tenant=tenant),
        host="127.0.0.1",
        port=0,
        admin_token="admin",
        trust_header_identity=True,
        forwarders={"a2a_http_json": HTTPUpstreamForwarder(f"http://127.0.0.1:{upstream.server_port}/api")},
    )
    gt = threading.Thread(target=gateway.serve_forever, daemon=True)
    gt.start()
    return upstream, ut, gateway, gt


def stop_stack(upstream, ut, gateway, gt):
    gateway.shutdown()
    gateway.server_close()
    upstream.shutdown()
    upstream.server_close()
    gt.join(timeout=2)
    ut.join(timeout=2)


def test_http_json_send_preserves_wire_request_and_replays_by_message_id(tmp_path):
    upstream, ut, gateway, gt = start_stack(tmp_path)
    base = f"http://127.0.0.1:{gateway.server_port}"
    body = {"message": {"messageId": "msg-1", "role": "ROLE_USER", "parts": []}}
    try:
        status, payload = request(base, "POST", "/message:send", body)
        assert status == 200 and payload["ok"] is True
        assert CaptureUpstream.calls[0]["method"] == "POST"
        assert CaptureUpstream.calls[0]["path"] == "/api/message:send"
        assert json.loads(CaptureUpstream.calls[0]["body"]) == body
        assert CaptureUpstream.calls[0]["headers"]["a2a-extensions"] == "https://example.org/ext"
        assert "aie-secret" not in CaptureUpstream.calls[0]["headers"]

        second_status, second = request(base, "POST", "/message:send", body)
        assert second_status == 409
        assert second["error_code"] == "AIE-REPLAY-001"
        assert len(CaptureUpstream.calls) == 1
    finally:
        stop_stack(upstream, ut, gateway, gt)


def test_http_json_get_task_is_repeatable_and_preserves_query(tmp_path):
    upstream, ut, gateway, gt = start_stack(tmp_path)
    base = f"http://127.0.0.1:{gateway.server_port}"
    try:
        first, _ = request(base, "GET", "/tasks/task-1?historyLength=3")
        second, _ = request(base, "GET", "/tasks/task-1?historyLength=3")
        assert (first, second) == (200, 200)
        assert [call["method"] for call in CaptureUpstream.calls] == ["GET", "GET"]
        assert [call["path"] for call in CaptureUpstream.calls] == [
            "/api/tasks/task-1?historyLength=3",
            "/api/tasks/task-1?historyLength=3",
        ]
    finally:
        stop_stack(upstream, ut, gateway, gt)


def test_http_json_tenant_is_bound_into_authority_resource_and_body_must_match_path():
    normalized = normalize_a2a_http_json_request(
        method="POST",
        path="/acme/message:send",
        query="",
        headers={"A2A-Version": "1.0"},
        body={"tenant": "acme", "message": {"messageId": "m-1"}},
    )
    assert normalized.action.resource == "a2a://tenant/acme/message/m-1"
    assert normalized.action.capability == "a2a.message.send"

    with pytest.raises(Exception) as exc:
        normalize_a2a_http_json_request(
            method="POST",
            path="/acme/message:send",
            query="",
            headers={"A2A-Version": "1.0"},
            body={"tenant": "other", "message": {"messageId": "m-1"}},
        )
    assert getattr(exc.value, "code", None) == "AIE-PROTO-002"


def test_http_json_tenant_path_cannot_use_non_tenant_lease(tmp_path):
    upstream, ut, gateway, gt = start_stack(tmp_path, tenant=None)
    base = f"http://127.0.0.1:{gateway.server_port}"
    try:
        status, payload = request(
            base,
            "POST",
            "/acme/message:send",
            {"tenant": "acme", "message": {"messageId": "m-tenant"}},
        )
        assert status == 403
        assert payload["error_code"] == "AIE-AUTH-004"
        assert CaptureUpstream.calls == []
    finally:
        stop_stack(upstream, ut, gateway, gt)


def test_http_json_tenant_lease_can_send_and_cancel_but_streaming_is_not_claimed(tmp_path):
    upstream, ut, gateway, gt = start_stack(tmp_path, tenant="acme")
    base = f"http://127.0.0.1:{gateway.server_port}"
    try:
        status, _ = request(
            base,
            "POST",
            "/acme/message:send",
            {"tenant": "acme", "message": {"messageId": "m-2"}},
        )
        assert status == 200
        cancel, _ = request(
            base,
            "POST",
            "/acme/tasks/task-2:cancel",
            {"tenant": "acme", "id": "task-2"},
        )
        assert cancel == 200
        stream, _ = request(
            base,
            "POST",
            "/acme/message:stream",
            {"tenant": "acme", "message": {"messageId": "m-3"}},
        )
        assert stream == 404
        assert len(CaptureUpstream.calls) == 2
    finally:
        stop_stack(upstream, ut, gateway, gt)


def test_config_accepts_separate_http_json_upstream(tmp_path):
    config = tmp_path / "gateway.json"
    config.write_text(
        json.dumps({"upstreams": {"a2a_http_json": {"url": "http://127.0.0.1:3000/api"}}}),
        encoding="utf-8",
    )
    options = build_server_options_from_config(config)
    assert "a2a_http_json" in options["forwarders"]
    assert options["forwarders"]["a2a_http_json"].url == "http://127.0.0.1:3000/api"
