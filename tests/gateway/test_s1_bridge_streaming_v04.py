from __future__ import annotations

import pytest

from aie_runtime.gateway import bridge as bridge_module


def test_plain_bridge_stream_yields_first_available_http_chunk(monkeypatch):
    class FakeResponse:
        status = 200

        def __init__(self):
            self.read1_calls = 0

        def getheaders(self):
            return [("Content-Type", "text/event-stream")]

        def read(self, amount=-1):
            raise AssertionError("streaming bridge must not use coalescing HTTPResponse.read()")

        def read1(self, amount=-1):
            self.read1_calls += 1
            if self.read1_calls == 1:
                return b"data: first\n\n"
            return b""

    response = FakeResponse()
    connections = []

    class FakeConnection:
        def __init__(self, *args, **kwargs):
            self.closed = False
            connections.append(self)

        def request(self, *args, **kwargs):
            return None

        def getresponse(self):
            return response

        def close(self):
            self.closed = True

    monkeypatch.setattr(bridge_module.http.client, "HTTPConnection", FakeConnection)

    status, headers, stream = bridge_module._request_stream(
        "POST",
        "http://example.org/mcp",
        b"{}",
        {"Content-Type": "application/json"},
        timeout=3,
        ssl_context=None,
    )

    assert status == 200
    assert headers["Content-Type"] == "text/event-stream"
    assert next(stream) == b"data: first\n\n"
    with pytest.raises(StopIteration):
        next(stream)
    assert connections[-1].closed is True


def test_send_stream_annotation_resolves_iterable():
    from typing import Iterable, get_type_hints

    from aie_runtime.gateway.bridge import _BridgeHandler

    hints = get_type_hints(_BridgeHandler._send_stream)
    assert hints["stream"] is Iterable[bytes]


def test_send_stream_writes_each_chunk_from_an_iterable():
    from aie_runtime.gateway.bridge import _BridgeHandler

    written = []

    class _W:
        def write(self, data):
            written.append(data)

        def flush(self):
            return None

    class Handler(_BridgeHandler):
        def send_response(self, status):
            return None

        def send_header(self, key, value):
            return None

        def end_headers(self):
            return None

        @property
        def command(self):
            return "POST"

        @property
        def wfile(self):
            return _W()

    handler = Handler.__new__(Handler)
    handler._send_stream(200, {"Content-Type": "text/event-stream"}, iter([b"a", b"b"]))
    joined = b"".join(written)
    assert b"1\r\na\r\n" in joined
    assert b"1\r\nb\r\n" in joined
