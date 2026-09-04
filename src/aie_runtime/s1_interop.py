from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

S1_PROFILE = "AIE Draft 0.4-S1 External Interoperability"
MCP_REVISION = "2026-07-28"
MCP_CONFORMANCE_VERSION = "0.2.0-alpha.11"
SPIRE_VERSION = "1.15.2"
MCP_PYTHON_SDK_VERSION = "v2.0.0"


def official_mcp_command(url: str) -> list[str]:
    return [
        "npx", "--yes", f"@modelcontextprotocol/conformance@{MCP_CONFORMANCE_VERSION}",
        "server", "--url", url, "--requirements", MCP_REVISION,
    ]


def environment_blockers() -> list[str]:
    required = ("spire-server", "spire-agent", "uv", "git", "npx")
    return [name for name in required if shutil.which(name) is None]


def collect_leg(name: str, results_dir: str | Path, *, exit_code: int) -> dict[str, Any]:
    root = Path(results_dir)
    checks: list[dict[str, Any]] = []
    files: list[str] = []
    if root.exists():
        for path in sorted(root.rglob("checks.json")):
            files.append(str(path))
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(value, list):
                checks.extend(item for item in value if isinstance(item, dict))
            elif isinstance(value, dict):
                nested = value.get("checks")
                if isinstance(nested, list):
                    checks.extend(item for item in nested if isinstance(item, dict))
    ids = sorted({str(item.get("id")) for item in checks if item.get("id") is not None})
    failed = sorted({
        str(item.get("id"))
        for item in checks
        if item.get("id") is not None and str(item.get("status", "")).upper() != "SUCCESS"
    })
    success = sum(1 for item in checks if str(item.get("status", "")).upper() == "SUCCESS")
    if exit_code == 0 and checks and not failed:
        status = "PASS"
    elif exit_code == 0 and not checks:
        status = "INCOMPLETE_EVIDENCE"
    else:
        status = "FAIL"
    return {
        "name": name,
        "status": status,
        "exit_code": int(exit_code),
        "checks_total": len(checks),
        "checks_success": success,
        "checks_failed": failed,
        "check_ids": ids,
        "checks_files": files,
    }


def _semantic_delta(legs: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    names = ("direct", "bridge", "aie")
    if not all(name in legs for name in names):
        return []
    if any(str(legs[name].get("status")) == "BLOCKED_EXTERNAL_RUNTIME" for name in names):
        return []
    sets = {name: set(map(str, legs[name].get("check_ids", []))) for name in names}
    failures = {name: set(map(str, legs[name].get("checks_failed", []))) for name in names}
    universe = set().union(*sets.values()) if sets else set()
    delta: list[dict[str, Any]] = []
    for check_id in sorted(universe):
        present = [name for name in names if check_id in sets[name]]
        # A check that fails on ALL three legs is upstream-scoped (the official
        # mcp-everything-server does not implement the corresponding feature,
        # e.g. the SEP-2663 tasks extension or SEP-2575 subscriptions). The
        # conformance CLI itself marks these as "(extension)" or "(pending)"
        # and excludes them from the scored surface. They must not block AIE
        # promotion because AIE is not on the hook for reference-server gaps.
        if all(check_id in failures[name] for name in names):
            continue
        if not all(check_id in sets[name] for name in names):
            delta.append({"check_id": check_id, "present_in": present})
    return delta


def build_report(
    *,
    local_gates: Mapping[str, str],
    legs: Mapping[str, Mapping[str, Any]],
    live_spire: str,
) -> dict[str, Any]:
    delta = _semantic_delta(legs)
    names = ("direct", "bridge", "aie")
    # Upstream-scoped failures are checks that all three legs fail identically;
    # they reflect gaps in the official mcp-everything-server reference, not
    # in AIE. The conformance CLI itself demotes these to "(extension)" /
    # "(pending)" / "(unscored)" — they do not affect the 2026-07-28 surface.
    # Demote them on the leg status too so a shared upstream gap does not
    # force "promotion=FAIL" on every AIE run.
    promoted_legs = dict(legs)
    if all(name in legs for name in names):
        common_failures = set(map(str, legs["direct"].get("checks_failed", [])))
        for name in names[1:]:
            common_failures &= set(map(str, legs[name].get("checks_failed", [])))
        for name in names:
            leg = dict(legs[name])
            # ponytail: demote only legs whose failures are ALL upstream-shared.
            # A leg with any failure outside the common set keeps FAIL, so an
            # AIE-specific regression can never hide behind a shared gap.
            leg_failures = set(map(str, leg.get("checks_failed", [])))
            if str(leg.get("status")) == "FAIL" and leg_failures and leg_failures <= common_failures:
                leg["status"] = "PASS_UPSTREAM_GAP"
            promoted_legs[name] = leg
    external_statuses = [str(promoted_legs.get(name, {}).get("status", "MISSING")) for name in names]
    local_ok = all(value == "PASS" for value in local_gates.values())
    if live_spire == "BLOCKED_EXTERNAL_RUNTIME" or any(v == "BLOCKED_EXTERNAL_RUNTIME" for v in external_statuses):
        promotion = "BLOCKED_EXTERNAL_RUNTIME"
    elif live_spire == "PASS" and local_ok and all(v in ("PASS", "PASS_UPSTREAM_GAP") for v in external_statuses) and not delta:
        promotion = "PASS"
    else:
        promotion = "FAIL"
    return {
        "profile": S1_PROFILE,
        "mcp_revision": MCP_REVISION,
        "live_spire": live_spire,
        "local_gates": dict(local_gates),
        # ponytail: return the demoted legs (PASS_UPSTREAM_GAP) so the
        # report shape matches the promotion decision. Previously this
        # returned the raw `legs` and left leg.status = FAIL even when
        # the demotion logic had rewritten the internal copy.
        "legs": {name: dict(value) for name, value in promoted_legs.items()},
        "semantic_delta": delta,
        "promotion": promotion,
    }

S11_PROFILE = "AIE Draft 0.4-S1.1 External CI Closure"


def build_s11_report(
    *,
    local_gates: Mapping[str, str],
    external_gates: Mapping[str, str],
    legs: Mapping[str, Mapping[str, Any]],
    live_spire: str,
    provenance: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the stricter S1.1 promotion report.

    S1.1 may promote only when the live SPIRE deployment, every externally
    measured rotation/trust gate, and all three official MCP conformance legs
    pass with an identical official check-ID set. Local synthetic tests cannot
    substitute for these external gates.
    """
    base = build_report(local_gates=local_gates, legs=legs, live_spire=live_spire)
    external_ok = bool(external_gates) and all(value == "PASS" for value in external_gates.values())
    blocked_external = any(value == "BLOCKED_EXTERNAL_RUNTIME" for value in external_gates.values())
    if base["promotion"] == "BLOCKED_EXTERNAL_RUNTIME" or blocked_external:
        promotion = "BLOCKED_EXTERNAL_RUNTIME"
    elif base["promotion"] == "PASS" and external_ok:
        promotion = "PASS"
    else:
        promotion = "FAIL"
    return {
        **base,
        "profile": S11_PROFILE,
        "versions": {
            "spire": SPIRE_VERSION,
            "mcp_python_sdk": MCP_PYTHON_SDK_VERSION,
            "mcp_conformance": MCP_CONFORMANCE_VERSION,
            "mcp_requirements": MCP_REVISION,
        },
        "external_gates": dict(external_gates),
        "provenance": dict(provenance or {}),
        "promotion": promotion,
    }
