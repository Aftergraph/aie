from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import yaml

from .engine import ActionRequest, AdmissionEngine, AuthorityLease, Mission, Principal
from .errors import AIEError
from .functional import FunctionalRuntime
from .store import InMemoryState


def _policy(mode: str):
    if mode == "allow":
        return lambda _: True
    if mode == "deny":
        return lambda _: False
    if mode == "error":
        def broken(_):
            raise RuntimeError("policy error")
        return broken
    raise ValueError(mode)


def _object_runtime(now: datetime, setup: dict[str, Any], policy_mode: str):
    state = InMemoryState()
    state.principals["agent:a"] = Principal("agent:a", "agent", "spiffe://example.ai/a")
    state.principals["agent:b"] = Principal("agent:b", "agent", "spiffe://example.ai/b")
    state.missions["mission:m"] = Mission("mission:m", "active")
    expires = now - timedelta(seconds=1) if setup.get("expired") else now + timedelta(minutes=5)
    state.leases["lease:l"] = AuthorityLease(
        id="lease:l", principal_id="agent:a", mission_id="mission:m",
        capabilities=set(setup.get("parent_capabilities", ["repo.read", "repo.write"])), resource_prefixes=("repo://acme/",),
        expires_at=expires, budget_remaining=float(setup.get("parent_budget", 10)), revoked=bool(setup.get("revoked")),
        depth=int(setup.get("parent_depth", 0)), max_delegation_depth=int(setup.get("max_depth", 2)),
    )
    trusted = {setup["trusted_issuer"]} if setup.get("trusted_issuer") else set()
    return AdmissionEngine(state, _policy(policy_mode), clock=lambda: now, trusted_issuers=trusted)


def _functional_runtime(now: datetime, setup: dict[str, Any], policy_mode: str):
    expires = now - timedelta(seconds=1) if setup.get("expired") else now + timedelta(minutes=5)
    state = {
        "principals": {"agent:a": {"id": "agent:a"}, "agent:b": {"id": "agent:b"}},
        "missions": {"mission:m": {"id": "mission:m", "state": "active"}},
        "leases": {"lease:l": {
            "id": "lease:l", "principal_id": "agent:a", "mission_id": "mission:m",
            "capabilities": list(setup.get("parent_capabilities", ["repo.read", "repo.write"])), "resource_prefixes": ["repo://acme/"],
            "expires_at": expires.isoformat(), "budget_remaining": float(setup.get("parent_budget", 10)),
            "revoked": bool(setup.get("revoked")), "depth": int(setup.get("parent_depth", 0)), "max_delegation_depth": int(setup.get("max_depth", 2)),
        }},
        "outcomes": {}, "events": [],
    }
    trusted = {setup["trusted_issuer"]} if setup.get("trusted_issuer") else set()
    return FunctionalRuntime(state, _policy(policy_mode), now=lambda: now, trusted_issuers=trusted)


def _execute(runtime_name: str, vector: dict[str, Any], now: datetime) -> str:
    setup = vector.get("setup") or {}
    policy_mode = vector.get("policy", "allow")
    runtime = _object_runtime(now, setup, policy_mode) if runtime_name == "object" else _functional_runtime(now, setup, policy_mode)
    op = vector["operation"]
    mutate = deepcopy(vector.get("mutate") or {})
    try:
        if op == "admit":
            req = {
                "action_id": "a1", "principal_id": "agent:a", "mission_id": "mission:m",
                "lease_id": "lease:l", "capability": "repo.write", "resource": "repo://acme/x",
                "budget_cost": 1, "extensions": (),
            }
            req.update(mutate)
            if runtime_name == "object":
                if isinstance(req.get("extensions"), list):
                    req["extensions"] = tuple(req["extensions"])
                out = runtime.admit(ActionRequest(**req))
                return out.status
            out = runtime.admit(req)
            return out["status"]
        if op == "delegate":
            capabilities = set(setup.get("child_capabilities", ["repo.read"]))
            budget = float(setup.get("child_budget", 2))
            runtime.delegate(
                parent_lease_id="lease:l",
                child_lease_id="lease:child",
                child_principal_id="agent:b",
                capabilities=capabilities,
                resource_prefixes=("repo://acme/service-a",),
                budget=budget,
                ttl=timedelta(minutes=1),
            )
            return "delegated"
        if op == "revoke-descendant":
            runtime.delegate(
                parent_lease_id="lease:l",
                child_lease_id="lease:child",
                child_principal_id="agent:b",
                capabilities=set(setup.get("child_capabilities", ["repo.read"])),
                resource_prefixes=("repo://acme/service-a",),
                budget=float(setup.get("child_budget", 2)),
                ttl=timedelta(minutes=1),
            )
            runtime.revoke("lease:l")
            if runtime_name == "object":
                return "revoked" if runtime.state.leases["lease:child"].revoked else "not-revoked"
            return "revoked" if runtime.state["leases"]["lease:child"]["revoked"] else "not-revoked"
        if op == "topology":
            runtime.authorize_topology_mutation(actor="agent:a", mutation="spawn", target="agent:b")
            return "allowed"
        if op == "federation":
            runtime.verify_federated_identity(
                issuer=mutate.get("issuer", "https://issuer.example"),
                clock_skew=timedelta(seconds=int(mutate.get("clock_skew_seconds", 0))),
                max_clock_skew=timedelta(seconds=30),
                revocation_fresh=bool(mutate.get("revocation_fresh", True)),
            )
            return "allowed"
        raise ValueError(f"unsupported operation: {op}")
    except AIEError as exc:
        return exc.code


def run_suite(path: str | Path, runtimes: Iterable[str] = ("object", "functional")) -> dict[str, Any]:
    doc = yaml.safe_load(Path(path).read_text())
    now = datetime.fromisoformat(doc["clock"])
    results = []
    for runtime in runtimes:
        if runtime not in {"object", "functional"}:
            raise ValueError(f"unknown runtime: {runtime}")
        for vector in doc["vectors"]:
            actual = _execute(runtime, vector, now)
            expected = vector["expect"]
            results.append({
                "runtime": runtime,
                "vector": vector["id"],
                "expected": expected,
                "actual": actual,
                "passed": actual == expected,
            })
    passed = sum(1 for r in results if r["passed"])
    return {
        "suiteVersion": doc["suiteVersion"],
        "semanticDraft": doc["semanticDraft"],
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AIE Draft 0.3 conformance vectors")
    parser.add_argument("vectors", type=Path)
    parser.add_argument("--runtime", choices=["object", "functional", "both"], default="both")
    parser.add_argument("--json", dest="json_path", type=Path)
    args = parser.parse_args(argv)
    runtimes = ("object", "functional") if args.runtime == "both" else (args.runtime,)
    report = run_suite(args.vectors, runtimes)
    output = json.dumps(report, indent=2)
    if args.json_path:
        args.json_path.write_text(output + "\n")
    print(output)
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
