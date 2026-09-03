from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping
from urllib.parse import quote, unquote
import uuid

from ..model import NormalizedAction, ProtocolError
from .a2a import A2A_VERSION, normalize_a2a_request


@dataclass(frozen=True)
class A2AHTTPJSONRequest:
    admission_body: dict[str, Any]
    tenant: str | None
    operation: str
    action: NormalizedAction


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def _tenant_and_route(path: str) -> tuple[str | None, str]:
    if not path.startswith("/"):
        raise ProtocolError("AIE-PROTO-002", "HTTP+JSON path must be absolute")

    for route in ("/message:send", "/tasks"):
        if path == route:
            return None, route
        if path.endswith(route):
            prefix = path[: -len(route)].strip("/")
            if prefix:
                return unquote(prefix), route

    match = re.fullmatch(r"/(?:(?P<tenant>.+)/)?tasks/(?P<task>[^/]+?)(?P<cancel>:cancel)?", path)
    if match:
        tenant = unquote(match.group("tenant")) if match.group("tenant") else None
        route = f"/tasks/{match.group('task')}{match.group('cancel') or ''}"
        return tenant, route

    raise ProtocolError("AIE-PROTO-001", f"unsupported A2A HTTP+JSON path: {path!r}")


def _validate_tenant(path_tenant: str | None, body: Mapping[str, Any]) -> str | None:
    raw = body.get("tenant")
    body_tenant = str(raw) if raw not in (None, "") else None
    if path_tenant is None and body_tenant is not None:
        raise ProtocolError("AIE-PROTO-002", "HTTP+JSON tenant body requires matching tenant path prefix")
    if path_tenant is not None and body_tenant is not None and body_tenant != path_tenant:
        raise ProtocolError("AIE-PROTO-002", "HTTP+JSON tenant path/body mismatch")
    return path_tenant


def _with_action(
    *,
    admission: dict[str, Any],
    tenant: str | None,
    operation: str,
    headers: Mapping[str, str],
) -> A2AHTTPJSONRequest:
    internal_headers = dict(headers)
    if tenant:
        internal_headers["AIE-A2A-Tenant"] = tenant
    action = normalize_a2a_request(internal_headers, admission)
    return A2AHTTPJSONRequest(admission, tenant, operation, action)


def normalize_a2a_http_json_request(
    *,
    method: str,
    path: str,
    query: str,
    headers: Mapping[str, str],
    body: Mapping[str, Any],
) -> A2AHTTPJSONRequest:
    del query  # Query bytes are forwarded unchanged; admission uses path/body semantics.
    version = _header(headers, "A2A-Version") or A2A_VERSION
    if version != A2A_VERSION:
        raise ProtocolError("AIE-PROTO-001", f"unsupported A2A version: {version!r}")

    tenant, route = _tenant_and_route(path)
    tenant = _validate_tenant(tenant, body)
    tenant_key = quote(tenant or "", safe="")

    if method == "POST" and route == "/message:send":
        if tenant is not None and not body.get("tenant"):
            raise ProtocolError("AIE-PROTO-002", "tenant HTTP+JSON message must carry tenant in request body")
        message = body.get("message") if isinstance(body.get("message"), Mapping) else {}
        message_id = str(message.get("messageId") or message.get("message_id") or "")
        if not message_id:
            raise ProtocolError("AIE-PROTO-002", "HTTP+JSON messageId is required")
        admission = {
            "jsonrpc": "2.0",
            "id": f"a2a-http-send:{tenant_key}:{message_id}",
            "method": "message/send",
            "params": {"message": {"messageId": message_id}},
        }
        return _with_action(admission=admission, tenant=tenant, operation="message/send", headers=headers)

    if method == "GET" and route == "/tasks":
        admission = {
            "jsonrpc": "2.0",
            "id": "a2a-http-read:" + uuid.uuid4().hex,
            "method": "tasks/list",
            "params": {},
        }
        return _with_action(admission=admission, tenant=tenant, operation="tasks/list", headers=headers)

    task_match = re.fullmatch(r"/tasks/(?P<task>[^/]+?)(?P<cancel>:cancel)?", route)
    if task_match:
        task_id = unquote(task_match.group("task"))
        if method == "GET" and not task_match.group("cancel"):
            admission = {
                "jsonrpc": "2.0",
                "id": "a2a-http-read:" + uuid.uuid4().hex,
                "method": "tasks/get",
                "params": {"id": task_id},
            }
            return _with_action(admission=admission, tenant=tenant, operation="tasks/get", headers=headers)

        if method == "POST" and task_match.group("cancel"):
            if tenant is not None and not body.get("tenant"):
                raise ProtocolError("AIE-PROTO-002", "tenant HTTP+JSON cancel must carry tenant in request body")
            body_id = str(body.get("id") or body.get("taskId") or task_id)
            if body_id != task_id:
                raise ProtocolError("AIE-PROTO-002", "HTTP+JSON task path/body id mismatch")
            admission = {
                "jsonrpc": "2.0",
                "id": f"a2a-http-cancel:{tenant_key}:{task_id}",
                "method": "tasks/cancel",
                "params": {"id": task_id},
            }
            return _with_action(admission=admission, tenant=tenant, operation="tasks/cancel", headers=headers)

    raise ProtocolError("AIE-PROTO-001", f"unsupported A2A HTTP+JSON operation: {method} {path}")


def is_a2a_http_json_nonstreaming(method: str, path: str) -> bool:
    try:
        _tenant, route = _tenant_and_route(path)
    except ProtocolError:
        return False
    if method == "POST" and route == "/message:send":
        return True
    if method == "GET" and route == "/tasks":
        return True
    if method == "GET" and re.fullmatch(r"/tasks/[^/]+", route):
        return True
    if method == "POST" and re.fullmatch(r"/tasks/[^/]+:cancel", route):
        return True
    return False
