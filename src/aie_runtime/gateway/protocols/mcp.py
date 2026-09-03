from __future__ import annotations

from typing import Any, Mapping

from ..model import NormalizedAction, ProtocolError

MCP_VERSION = "2026-07-28"


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def normalize_mcp_request(headers: Mapping[str, str], body: Mapping[str, Any]) -> NormalizedAction:
    version = _header(headers, "MCP-Protocol-Version")
    if version != MCP_VERSION:
        raise ProtocolError("AIE-PROTO-001", f"unsupported MCP version: {version!r}")

    method = _header(headers, "Mcp-Method") or str(body.get("method") or "")
    if not method:
        raise ProtocolError("AIE-PROTO-002", "missing MCP method")

    request_id = body.get("id")
    if request_id is None:
        raise ProtocolError("AIE-PROTO-002", "MCP request id is required for admission")

    name = _header(headers, "Mcp-Name")
    if method == "tools/call":
        params = body.get("params") if isinstance(body.get("params"), Mapping) else {}
        name = name or str(params.get("name") or "")
        if not name:
            raise ProtocolError("AIE-PROTO-002", "missing MCP tool name")
        capability = f"mcp.tools.call:{name}"
        resource = f"mcp://tool/{name}"
        subject_id = name
    else:
        normalized_method = method.replace("/", ".")
        capability = f"mcp.{normalized_method}"
        resource = f"mcp://method/{method}"
        subject_id = name

    return NormalizedAction(
        protocol="mcp",
        protocol_version=version,
        action_id=str(request_id),
        capability=capability,
        resource=resource,
        operation=method,
        subject_id=subject_id,
        metadata={"jsonrpc": body.get("jsonrpc", "2.0")},
    )
