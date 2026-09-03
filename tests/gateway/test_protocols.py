import pytest

from aie_runtime.gateway.model import ProtocolError
from aie_runtime.gateway.protocols.mcp import normalize_mcp_request
from aie_runtime.gateway.protocols.a2a import normalize_a2a_request


def test_mcp_tools_call_normalizes_headers_and_name_without_content_capture():
    headers = {
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": "tools/call",
        "Mcp-Name": "refund_customer",
    }
    body = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "tools/call",
        "params": {"name": "refund_customer", "arguments": {"card": "secret"}},
    }

    action = normalize_mcp_request(headers, body)

    assert action.protocol == "mcp"
    assert action.protocol_version == "2026-07-28"
    assert action.action_id == "req-1"
    assert action.capability == "mcp.tools.call:refund_customer"
    assert action.resource == "mcp://tool/refund_customer"
    assert "secret" not in repr(action)


def test_mcp_rejects_unsupported_version():
    with pytest.raises(ProtocolError) as exc:
        normalize_mcp_request(
            {"MCP-Protocol-Version": "2025-11-25", "Mcp-Method": "tools/call", "Mcp-Name": "x"},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "x"}},
        )
    assert exc.value.code == "AIE-PROTO-001"


def test_a2a_send_message_normalizes_without_message_content():
    headers = {"A2A-Version": "1.0"}
    body = {
        "jsonrpc": "2.0",
        "id": "a2a-1",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": "msg-123",
                "role": "user",
                "parts": [{"kind": "text", "text": "private content"}],
            }
        },
    }

    action = normalize_a2a_request(headers, body)

    assert action.protocol == "a2a"
    assert action.protocol_version == "1.0"
    assert action.action_id == "a2a-1"
    assert action.capability == "a2a.message.send"
    assert action.resource == "a2a://message/msg-123"
    assert "private content" not in repr(action)


def test_a2a_rejects_unsupported_version():
    with pytest.raises(ProtocolError) as exc:
        normalize_a2a_request(
            {"A2A-Version": "0.3"},
            {"jsonrpc": "2.0", "id": "x", "method": "message/send", "params": {"message": {"messageId": "m"}}},
        )
    assert exc.value.code == "AIE-PROTO-001"
