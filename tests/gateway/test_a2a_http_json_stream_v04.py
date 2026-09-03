import http.client
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aie_runtime.engine import AuthorityLease, Mission, Principal
from aie_runtime.gateway.a2a_http_json import A2AHTTPJSONForwarder, create_a2a_http_json_server
from aie_runtime.gateway.core import AIEGateway
from aie_runtime.gateway.durable import SQLiteGatewayStore
from aie_runtime.gateway.policy import LocalPolicyAdapter
from aie_runtime.store import InMemoryState

NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)


class SSEUpstream(BaseHTTPRequestHandler):
    first_sent = threading.Event()
    release = threading.Event()
    calls = []

    def log_message(self, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        type(self).calls.append((self.path, body))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b'data: {"phase":"first"}\n\n')
        self.wfile.flush()
        type(self).first_sent.set()
        type(self).release.wait(timeout=3)
        try:
            self.wfile.write(b'data: {"phase":"second"}\n\n')
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def make_gateway(tmp_path):
    state = InMemoryState()
    state.principals["p"] = Principal("p", "agent", "spiffe://example.org/a")
    state.missions["m"] = Mission("m", "active")
    state.leases["l"] = AuthorityLease(
        "l",
        "p",
        "m",
        {"a2a.message.stream", "a2a.task.subscribe"},
        ("a2a://message/", "a2a://task/"),
        NOW + timedelta(hours=1),
        100,
    )
    return AIEGateway(
        state=state,
        store=SQLiteGatewayStore(tmp_path / "stream.db"),
        policy=LocalPolicyAdapter(lambda _: True),
        clock=lambda: NOW,
    )


def start(tmp_path):
    SSEUpstream.first_sent = threading.Event()
    SSEUpstream.release = threading.Event()
    SSEUpstream.calls = []
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), SSEUpstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    gateway = make_gateway(tmp_path)
    server = create_a2a_http_json_server(
        gateway,
        A2AHTTPJSONForwarder(f"http://127.0.0.1:{upstream.server_port}"),
        trust_header_identity=True,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, upstream, gateway


def headers():
    return {
        "X-AIE-Verified-Spiffe-ID": "spiffe://example.org/a",
        "X-AIE-Identity-Verified": "true",
        "AIE-Mission-Id": "m",
        "AIE-Authority-Lease": "l",
        "A2A-Version": "1.0",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Cache-Control": "no-store",
    }


def wait_outcome(gateway, action_id, timeout=2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = gateway.store.get_outcome(action_id)
        if value is not None:
            return value
        time.sleep(0.01)
    return None


def test_message_stream_forwards_first_event_before_terminal_outcome(tmp_path):
    server, upstream, gateway = start(tmp_path)
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        body = json.dumps({"message": {"messageId": "stream-1"}}).encode()
        conn.request("POST", "/message:stream", body=body, headers=headers())
        response = conn.getresponse()
        assert response.status == 200
        assert "text/event-stream" in response.getheader("Content-Type")
        assert response.readline() == b'data: {"phase":"first"}\n'
        assert response.readline() == b"\n"
        assert SSEUpstream.first_sent.is_set()
        assert gateway.store.get_outcome("stream-1") is None

        SSEUpstream.release.set()
        rest = response.read()
        assert b'"phase":"second"' in rest
        outcome = wait_outcome(gateway, "stream-1")
        assert outcome is not None
        assert outcome["status"] == "admitted"
    finally:
        SSEUpstream.release.set()
        conn.close()
        server.shutdown()
        upstream.shutdown()


def test_task_subscribe_is_repeatable_and_not_replay_blocked(tmp_path):
    server, upstream, gateway = start(tmp_path)
    try:
        for _ in range(2):
            SSEUpstream.first_sent.clear()
            SSEUpstream.release.set()
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            conn.request("POST", "/tasks/t1:subscribe", body=b"{}", headers=headers())
            response = conn.getresponse()
            assert response.status == 200
            assert b'"phase":"first"' in response.read()
            conn.close()
        assert len(SSEUpstream.calls) == 2
        evidence = gateway.store.list_evidence()
        subscribe = [
            event
            for event in evidence
            if event.get("aie.capability") == "a2a.task.subscribe"
        ]
        assert len(subscribe) == 2
        assert all(event["aie.resource"] == "a2a://task/t1" for event in subscribe)
        assert subscribe[0]["aie.action.id"] != subscribe[1]["aie.action.id"]
    finally:
        SSEUpstream.release.set()
        server.shutdown()
        upstream.shutdown()


def test_client_disconnect_after_dispatch_becomes_uncertain(tmp_path):
    server, upstream, gateway = start(tmp_path)
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    body = json.dumps({"message": {"messageId": "stream-drop"}}).encode()
    try:
        conn.request("POST", "/message:stream", body=body, headers=headers())
        response = conn.getresponse()
        assert response.readline().startswith(b"data:")
        response.close()
        conn.close()
        SSEUpstream.release.set()
        outcome = wait_outcome(gateway, "stream-drop", timeout=3)
        assert outcome is not None
        assert outcome["status"] == "uncertain"
        assert outcome["error_code"] == "AIE-UPSTREAM-002"
    finally:
        SSEUpstream.release.set()
        try:
            conn.close()
        except Exception:
            pass
        server.shutdown()
        upstream.shutdown()
