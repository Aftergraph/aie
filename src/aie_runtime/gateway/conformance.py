from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any


def _request_json(base_url: str, method: str, path: str, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(base_url.rstrip("/") + path, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def run_gateway_conformance(
    base_url: str,
    *,
    admin_token: str,
    spiffe_id: str,
    mission_id: str,
    lease_id: str,
    mcp_tool: str,
) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:10]
    checks: list[dict[str, Any]] = []

    def add(check_id: str, passed: bool, observed: Any) -> None:
        checks.append({"id": check_id, "passed": bool(passed), "observed": observed})

    status, payload = _request_json(base_url, "GET", "/healthz")
    add("GW-HEALTH-001", status == 200 and payload.get("status") == "ok", {"status": status, "payload": payload})

    common = {
        "Content-Type": "application/json",
        "X-AIE-Verified-Spiffe-ID": spiffe_id,
        "X-AIE-Identity-Verified": "true",
        "AIE-Mission-Id": mission_id,
        "AIE-Authority-Lease": lease_id,
        "AIE-Budget-Cost": "1",
    }
    mcp_headers = common | {
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": "tools/call",
        "Mcp-Name": mcp_tool,
    }
    mcp_id = f"gw-{run_id}-mcp"
    mcp_body = {
        "jsonrpc": "2.0",
        "id": mcp_id,
        "method": "tools/call",
        "params": {"name": mcp_tool, "arguments": {"conformance": True}},
    }
    status, payload = _request_json(base_url, "POST", "/mcp", mcp_body, mcp_headers)
    add("GW-MCP-ADMIT-001", status == 200 and payload.get("status") == "admitted", {"status": status, "payload": payload})

    status, payload = _request_json(base_url, "POST", "/mcp", mcp_body, mcp_headers)
    add(
        "GW-REPLAY-001",
        status == 409 and payload.get("status") == "prior-outcome" and payload.get("error_code") == "AIE-REPLAY-001",
        {"status": status, "payload": payload},
    )

    a2a_id = f"gw-{run_id}-a2a"
    a2a_headers = common | {"A2A-Version": "1.0"}
    a2a_body = {
        "jsonrpc": "2.0",
        "id": a2a_id,
        "method": "message/send",
        "params": {"message": {"messageId": f"msg-{run_id}", "role": "user", "parts": [{"kind": "text", "text": "conformance probe"}]}},
    }
    status, payload = _request_json(base_url, "POST", "/a2a", a2a_body, a2a_headers)
    add("GW-A2A-ADMIT-001", status == 200 and payload.get("status") == "admitted", {"status": status, "payload": payload})

    status, payload = _request_json(
        base_url,
        "POST",
        "/revocations",
        {"lease_id": lease_id},
        {"Content-Type": "application/json", "Authorization": f"Bearer {admin_token}"},
    )
    revoke_ok = status == 200 and payload.get("revoked") == lease_id
    post_revoke_body = dict(mcp_body)
    post_revoke_body["id"] = f"gw-{run_id}-revoked"
    status2, payload2 = _request_json(base_url, "POST", "/mcp", post_revoke_body, mcp_headers)
    add(
        "GW-REVOKE-001",
        revoke_ok and status2 == 403 and payload2.get("error_code") == "AIE-AUTH-003",
        {"revoke_status": status, "revoke_payload": payload, "post_status": status2, "post_payload": payload2},
    )

    passed_count = sum(1 for c in checks if c["passed"])
    failed_count = len(checks) - passed_count
    return {
        "suite": "aie-gateway/0.2",
        "passed": failed_count == 0,
        "summary": {"passed": passed_count, "failed": failed_count, "total": len(checks)},
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run black-box AIE Reference Gateway conformance checks")
    parser.add_argument("base_url")
    parser.add_argument("--admin-token", required=True)
    parser.add_argument("--spiffe-id", required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--lease-id", required=True)
    parser.add_argument("--mcp-tool", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    report = run_gateway_conformance(
        args.base_url,
        admin_token=args.admin_token,
        spiffe_id=args.spiffe_id,
        mission_id=args.mission_id,
        lease_id=args.lease_id,
        mcp_tool=args.mcp_tool,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(rendered + "\n")
    else:
        print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
