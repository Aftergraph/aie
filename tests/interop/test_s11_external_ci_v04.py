from __future__ import annotations

from pathlib import Path

from aie_runtime.s1_interop import build_s11_report


ROOT = Path(__file__).resolve().parents[2]


def _pass_leg(name: str) -> dict[str, object]:
    return {
        "name": name,
        "status": "PASS",
        "exit_code": 0,
        "checks_total": 2,
        "checks_success": 2,
        "checks_failed": [],
        "check_ids": ["a", "b"],
        "checks_files": [f"results/{name}/checks.json"],
    }


def test_s11_report_requires_external_rotation_gates_and_records_provenance():
    report = build_s11_report(
        local_gates={"workload_api_stream": "PASS", "authority_binding": "PASS"},
        external_gates={
            "svid_rotation_live": "PASS",
            "trust_bundle_rotation_live": "PASS",
            "old_trust_rejected": "PASS",
        },
        legs={name: _pass_leg(name) for name in ("direct", "bridge", "aie")},
        live_spire="PASS",
        provenance={"provider": "github-actions", "run_id": "123", "git_sha": "abc"},
    )
    assert report["profile"] == "AIE Draft 0.4-S1.1 External CI Closure"
    assert report["promotion"] == "PASS"
    assert report["versions"]["mcp_requirements"] == "2026-07-28"
    assert report["versions"]["mcp_conformance"] == "0.2.0-alpha.11"
    assert report["versions"]["spire"] == "1.15.2"
    assert report["provenance"]["provider"] == "github-actions"


def test_s11_report_fails_when_live_rotation_did_not_pass():
    report = build_s11_report(
        local_gates={"workload_api_stream": "PASS"},
        external_gates={
            "svid_rotation_live": "PASS",
            "trust_bundle_rotation_live": "FAIL",
            "old_trust_rejected": "PASS",
        },
        legs={name: _pass_leg(name) for name in ("direct", "bridge", "aie")},
        live_spire="PASS",
        provenance={},
    )
    assert report["promotion"] == "FAIL"


def test_external_ci_workflow_is_read_only_pinned_and_uploads_evidence():
    workflow = (ROOT / ".github/workflows/aie-v04-s1-external-interop.yml").read_text(encoding="utf-8")
    assert "ubuntu-24.04" in workflow
    assert "contents: read" in workflow
    assert "timeout-minutes:" in workflow
    assert "interop/s1/scripts/ci_external_s1.sh" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "AIE_S1_1_PROMOTION.json" in workflow
    assert "if-no-files-found: error" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "pull-requests: write" not in workflow
    assert "contents: write" not in workflow


def test_rotation_gate_uses_spire_local_authority_rotation_and_requires_old_trust_rejection():
    script = (ROOT / "interop/s1/scripts/run_live_rotation_gate.sh").read_text(encoding="utf-8")
    assert "localauthority x509 show" in script
    assert "localauthority x509 prepare" in script
    assert "localauthority x509 activate" in script
    assert "localauthority x509 revoke" in script
    assert "old_trust_rejected" in script
    assert "rotation_probe.py" in script


def test_external_ci_driver_refuses_promotion_unless_canonical_report_passes():
    script = (ROOT / "interop/s1/scripts/ci_external_s1.sh").read_text(encoding="utf-8")
    assert "run_live_rotation_gate.sh" in script
    assert "run_official_mcp.sh" in script
    assert "collect_report.py" in script
    assert "AIE_S1_1_PROMOTION.json" in script
    assert '"promotion"' in script
    assert "PASS" in script


def test_ci_preserves_absolute_python_uv_and_npx_paths_across_sudo_boundary():
    workflow = (ROOT / ".github/workflows/aie-v04-s1-external-interop.yml").read_text(encoding="utf-8")
    driver = (ROOT / "interop/s1/scripts/ci_external_s1.sh").read_text(encoding="utf-8")
    conformance = (ROOT / "interop/s1/scripts/run_official_mcp.sh").read_text(encoding="utf-8")
    assert "AIE_S1_PYTHON" in workflow
    assert "AIE_S1_UV" in workflow
    assert "AIE_S1_NPX" in workflow
    assert "AIE_S1_UV" in driver
    assert "AIE_S1_NPX" in conformance


def test_lab_assigns_write_ownership_to_gateway_and_rotation_workloads():
    components = (ROOT / "interop/s1/scripts/start_components.sh").read_text(encoding="utf-8")
    rotation = (ROOT / "interop/s1/scripts/run_live_rotation_gate.sh").read_text(encoding="utf-8")
    gateway = (ROOT / "interop/s1/config/gateway.json").read_text(encoding="utf-8")
    assert "gateway-data" in components
    assert "chown aie-s1-gateway" in components
    assert "/gateway-data/gateway.sqlite3" in gateway
    assert "chown aie-s1-client" in rotation


def test_ci_driver_copies_lab_logs_into_workspace_evidence_on_exit():
    driver = (ROOT / "interop/s1/scripts/ci_external_s1.sh").read_text(encoding="utf-8")
    assert "lab-logs" in driver
    assert "stop_lab.sh" in driver


def test_spire_lab_uses_short_agent_and_workload_svid_ttls_for_bounded_rotation_gate():
    config = (ROOT / "interop/s1/spire/server.conf").read_text(encoding="utf-8")
    assert 'default_x509_svid_ttl = "60s"' in config
    assert 'agent_ttl = "60s"' in config


def test_rotation_probe_uses_original_old_context_for_trust_rejection_check():
    # ponytail: the `old_trust_rejected` gate must prove the gateway's
    # server-side trust store no longer trusts the old CA. The only way
    # to do that is to test from a client whose trust store still contains
    # the OLD CA — i.e. the original snapshot from before the rotation
    # subscription. A fresh fetch returns the post-rotation SVID/bundle,
    # whose chain is now trusted, so the test degenerates into
    # `new_trust_works` and the gate is meaningless. Regression: a
    # previous refactor introduced a fresh fetch and silently turned
    # this gate into a tautology that always passed.
    probe = (ROOT / "interop/s1/rotation_probe.py").read_text(encoding="utf-8")
    assert "old_client_ctx)" in probe or "old_client_ctx)" in probe.replace(" ", "")
    # The fresh-fetch pattern is what the regression introduced; assert
    # the probe does NOT re-fetch a SVID just to build the old context.
    assert "old_client_ctx_fresh" not in probe, (
        "rotation probe must use the original old_client_ctx for the "
        "old_trust_rejected gate; re-fetching the SVID returns the "
        "post-rotation chain and makes the gate tautological."
    )
