from __future__ import annotations

import pytest

from aie_runtime.gateway import forwarding as forwarding_module
from aie_runtime.gateway.forwarding import HTTPUpstreamForwarder


def test_plain_forward_stream_yields_first_available_http_chunk(monkeypatch):
    class FakeResponse:
        status = 200
        headers = {"Content-Type": "text/event-stream"}

        def __init__(self):
            self.read1_calls = 0
            self.closed = False

        def read(self, amount=-1):
            raise AssertionError("streaming forwarder must not use coalescing response.read()")

        def read1(self, amount=-1):
            self.read1_calls += 1
            if self.read1_calls == 1:
                return b"data: first\n\n"
            return b""

        def close(self):
            self.closed = True

    response = FakeResponse()
    monkeypatch.setattr(forwarding_module.urllib.request, "urlopen", lambda *args, **kwargs: response)

    forwarder = HTTPUpstreamForwarder("http://example.org/mcp")
    result = forwarder.forward_stream(
        method="POST",
        headers={"Accept": "text/event-stream"},
        body={"jsonrpc": "2.0", "id": 1, "method": "subscriptions/listen", "params": {}},
    )

    assert result.status == 200
    assert result.headers["Content-Type"] == "text/event-stream"
    assert next(result.stream) == b"data: first\n\n"
    with pytest.raises(StopIteration):
        next(result.stream)
    assert response.closed is True
