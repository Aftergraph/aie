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
