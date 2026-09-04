from __future__ import annotations

import json

from aie_runtime.s1_interop import collect_leg, build_report


def _checks(path, values):
    path.mkdir(parents=True)
    (path / "checks.json").write_text(json.dumps(values), encoding="utf-8")


def test_collect_leg_reads_official_mcp_check_statuses(tmp_path):
    root = tmp_path / "results"
    _checks(root / "scenario-a", [
        {"id": "a", "status": "SUCCESS"},
        {"id": "b", "status": "FAILURE", "errorMessage": "bad"},
    ])
    leg = collect_leg("direct", root, exit_code=1)
    assert leg["status"] == "FAIL"
    assert leg["checks_total"] == 2
    assert leg["checks_success"] == 1
    assert leg["checks_failed"] == ["b"]


def test_build_report_promotes_only_when_all_external_legs_pass_with_same_check_ids(tmp_path):
    direct = tmp_path / "direct"
    bridge = tmp_path / "bridge"
    aie = tmp_path / "aie"
    checks = [{"id": "server-stateless", "status": "SUCCESS"}, {"id": "tools-call", "status": "SUCCESS"}]
    for root in (direct, bridge, aie):
        _checks(root / "run", checks)
    report = build_report(
        local_gates={"workload_api_stream": "PASS", "atomic_tls_rotation": "PASS"},
        legs={
            "direct": collect_leg("direct", direct, exit_code=0),
            "bridge": collect_leg("bridge", bridge, exit_code=0),
            "aie": collect_leg("aie", aie, exit_code=0),
        },
        live_spire="PASS",
    )
    assert report["semantic_delta"] == []
    assert report["promotion"] == "PASS"


def test_build_report_is_blocked_when_external_runtime_was_not_executed():
    report = build_report(
        local_gates={"workload_api_stream": "PASS"},
        legs={
            name: {"name": name, "status": "BLOCKED_EXTERNAL_RUNTIME", "check_ids": []}
            for name in ("direct", "bridge", "aie")
        },
        live_spire="BLOCKED_EXTERNAL_RUNTIME",
    )
    assert report["promotion"] == "BLOCKED_EXTERNAL_RUNTIME"
    assert report["semantic_delta"] == []


def test_upstream_gap_demotes_only_legs_without_leg_specific_failures(tmp_path):
    shared = {"id": "upstream-extension", "status": "FAILURE"}
    extra = {"id": "aie-regression", "status": "FAILURE"}
    ok = {"id": "server-stateless", "status": "SUCCESS"}
    roots = {}
    for name in ("direct", "bridge", "aie"):
        roots[name] = tmp_path / name
    _checks(roots["direct"] / "run", [ok, shared])
    _checks(roots["bridge"] / "run", [ok, shared])
    _checks(roots["aie"] / "run", [ok, shared, extra])
    legs = {name: collect_leg(name, roots[name], exit_code=1) for name in roots}
    report = build_report(
        local_gates={"workload_api_stream": "PASS", "atomic_tls_rotation": "PASS"},
        legs=legs,
        live_spire="PASS",
    )
    # The shared upstream-extension failure is filtered from the semantic delta;
    # only aie-regression remains and only aie has it, so a delta must surface.
    # The shared failure is demoted at the promotion layer for direct/bridge
    # (their failures are a subset of the common set), and the demoted leg
    # status is reflected in the report shape. aie keeps FAIL because its
    # aie-regression failure is outside the common set, so the evidence is
    # honest: aie is genuinely broken, not just upstream-blocked.
    assert report["semantic_delta"] == [{"check_id": "aie-regression", "present_in": ["aie"]}]
    assert report["legs"]["direct"]["status"] == "PASS_UPSTREAM_GAP"
    assert report["legs"]["bridge"]["status"] == "PASS_UPSTREAM_GAP"
    assert report["legs"]["aie"]["status"] == "FAIL"
    assert report["promotion"] == "FAIL"


def test_upstream_gap_promotes_when_all_legs_share_only_upstream_failures(tmp_path):
    shared = {"id": "upstream-extension", "status": "FAILURE"}
    ok = {"id": "server-stateless", "status": "SUCCESS"}
    roots = {}
    for name in ("direct", "bridge", "aie"):
        roots[name] = tmp_path / name
        _checks(roots[name] / "run", [ok, shared])
    legs = {name: collect_leg(name, roots[name], exit_code=1) for name in roots}
    report = build_report(
        local_gates={"workload_api_stream": "PASS", "atomic_tls_rotation": "PASS"},
        legs=legs,
        live_spire="PASS",
    )
    # No leg has a leg-specific failure outside the common set, so the
    # upstream gap is the only signal and promotion is allowed to PASS.
    # Every leg in the report shape reflects the demoted PASS_UPSTREAM_GAP
    # status so the report's leg.status matches the promotion decision.
    assert report["semantic_delta"] == []
    for name in ("direct", "bridge", "aie"):
        assert report["legs"][name]["status"] == "PASS_UPSTREAM_GAP", name
    assert report["promotion"] == "PASS"

from aie_runtime.s1_interop import official_mcp_command, environment_blockers


def test_official_mcp_command_pins_runner_and_protocol_revision(tmp_path):
    command = official_mcp_command("http://127.0.0.1:19081/mcp")
    assert command == [
        "npx", "--yes", "@modelcontextprotocol/conformance@0.2.0-alpha.11",
        "server", "--url", "http://127.0.0.1:19081/mcp",
        "--requirements", "2026-07-28",
    ]


def test_environment_blockers_reports_only_missing_required_tools(monkeypatch):
    present = {"git": "/usr/bin/git", "npx": "/usr/bin/npx"}
    monkeypatch.setattr("aie_runtime.s1_interop.shutil.which", lambda name: present.get(name))
    assert environment_blockers() == ["spire-server", "spire-agent", "uv"]
