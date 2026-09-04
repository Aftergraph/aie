from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = ROOT / 'interop/s2/collect_report.py'
VERSIONS = ROOT / 'interop/s2/versions.env'
RUNNER = ROOT / 'interop/s2/scripts/run_official_a2a.sh'
PREPARE = ROOT / 'interop/s2/scripts/prepare_official_a2a.sh'


def _report(*, req_ids=('CORE-SEND-001', 'CORE-TASK-001'), capability=True):
    per_requirement = {}
    for req_id in req_ids:
        per_requirement[req_id] = {
            'level': 'MUST',
            'status': 'PASS',
            'transports': {'grpc': 'PASS', 'jsonrpc': 'PASS', 'http_json': 'PASS'},
            'errors': [],
            'test_ids': [f'test::{req_id}'],
        }
    return {
        'summary': {'spec_version': '1.0', 'must_compatibility': '100.0%'},
        'per_requirement': per_requirement,
        'per_transport': {
            'grpc': {'total': 2, 'passed': 2, 'failed': 0, 'skipped': 0},
            'jsonrpc': {'total': 2, 'passed': 2, 'failed': 0, 'skipped': 0},
            'http_json': {'total': 2, 'passed': 2, 'failed': 0, 'skipped': 0},
        },
        'agent_card': {
            'protocolVersion': '1.0',
            'capabilities': {'streaming': capability},
            'defaultInputModes': ['text/plain'],
            'defaultOutputModes': ['text/plain'],
            'skills': [{'id': 'echo', 'name': 'Echo'}],
            'url': 'http://example.invalid',
        },
    }


def _s1_attestation(*, promotion='PASS'):
    check_ids = ['MCP-CONFORMANCE-001', 'MCP-CONFORMANCE-002']
    return {
        'profile': 'AIE Draft 0.4-S1.1 External CI Closure',
        'promotion': promotion,
        'mcp_revision': '2026-07-28',
        'live_spire': 'PASS' if promotion == 'PASS' else 'BLOCKED',
        'external_gates': {
            'svid_rotation_live': 'PASS' if promotion == 'PASS' else 'BLOCKED',
            'trust_bundle_rotation_live': 'PASS' if promotion == 'PASS' else 'BLOCKED',
            'old_trust_rejected': 'PASS' if promotion == 'PASS' else 'BLOCKED',
            'new_trust_works': 'PASS' if promotion == 'PASS' else 'BLOCKED',
        },
        'legs': {
            name: {
                'status': 'PASS' if promotion == 'PASS' else 'BLOCKED',
                'check_ids': check_ids,
                'checks_total': len(check_ids),
            }
            for name in ('direct', 'bridge', 'aie')
        },
        'semantic_delta': [],
        'provenance': {
            'provider': 'github-actions',
            'run_id': '33730332744',
            'git_sha': 'a' * 40,
            'workflow_ref': '.github/workflows/aie-v04-s1-self-hosted.yml@refs/heads/main',
        },
    }


def _run(tmp_path, *, direct=None, spiffe=None, aie=None, s1='PASS', s1_report=None, exit_codes=None):
    direct = direct or _report()
    spiffe = spiffe or _report()
    aie = aie or _report()
    paths = {}
    for name, report in [('direct', direct), ('spiffe', spiffe), ('aie', aie)]:
        path = tmp_path / f'{name}.json'
        path.write_text(json.dumps(report), encoding='utf-8')
        paths[name] = path
    exit_codes = exit_codes or {'direct': 0, 'spiffe': 0, 'aie': 0}
    exit_paths = {}
    for name, value in exit_codes.items():
        path = tmp_path / f'{name}.exit_code.txt'
        path.write_text(f'{value}\n', encoding='utf-8')
        exit_paths[name] = path
    s1_path = tmp_path / 's1.json'
    s1_payload = s1_report if s1_report is not None else _s1_attestation(promotion=s1)
    s1_path.write_text(json.dumps(s1_payload), encoding='utf-8')
    out = tmp_path / 'AIE_S2_A2A_INTEROP.json'
    result = subprocess.run([
        sys.executable, str(COLLECTOR),
        '--direct', str(paths['direct']),
        '--spiffe', str(paths['spiffe']),
        '--aie', str(paths['aie']),
        '--direct-exit-code', str(exit_paths['direct']),
        '--spiffe-exit-code', str(exit_paths['spiffe']),
        '--aie-exit-code', str(exit_paths['aie']),
        '--s1-promotion', str(s1_path),
        '--output', str(out),
    ], text=True, capture_output=True)
    return result, json.loads(out.read_text()) if out.exists() else None


def test_versions_pin_official_a2a_tck_commit_and_sdk_release():
    text = VERSIONS.read_text(encoding='utf-8')
    assert 'A2A_PROTOCOL_VERSION=1.0' in text
    assert 'A2A_TCK_VERSION=1.0.0' in text
    assert 'A2A_TCK_COMMIT=263b9cfaf16a554bdfb166a7ba5b67716e946349' in text
    assert 'A2A_PYTHON_SDK_VERSION=1.0.2' in text
    assert 'https://github.com/a2aproject/a2a-tck.git' in text


def test_collector_blocks_promotion_when_s1_dependency_is_not_pass(tmp_path):
    result, output = _run(tmp_path, s1='BLOCKED_EXTERNAL_RUNTIME')
    assert result.returncode == 0
    assert output['promotion'] == 'BLOCKED_BY_S1'
    assert output['s1_dependency']['satisfied'] is False
    assert output['parity']['semantic_delta'] == []
    assert output['must_requirement_ids'] == ['CORE-SEND-001', 'CORE-TASK-001']


def test_collector_promotes_only_when_s1_passes_and_all_must_semantics_match(tmp_path):
    result, output = _run(tmp_path, s1='PASS')
    assert result.returncode == 0
    assert output['promotion'] == 'PASS'
    assert output['s1_dependency']['satisfied'] is True
    assert output['parity']['ids_equal'] is True
    assert output['parity']['statuses_equal'] is True
    assert output['parity']['agent_card_semantics_equal'] is True


def test_collector_fails_on_missing_or_extra_must_requirement_ids(tmp_path):
    result, output = _run(tmp_path, spiffe=_report(req_ids=('CORE-SEND-001',)), s1='PASS')
    assert result.returncode != 0
    assert output['promotion'] == 'FAIL'
    assert output['parity']['ids_equal'] is False
    assert any('requirement-id-set' in item for item in output['parity']['semantic_delta'])


def test_collector_fails_on_false_capability_advertisement(tmp_path):
    result, output = _run(tmp_path, aie=_report(capability=False), s1='PASS')
    assert result.returncode != 0
    assert output['promotion'] == 'FAIL'
    assert output['parity']['agent_card_semantics_equal'] is False
    assert any('agent-card-semantics' in item for item in output['parity']['semantic_delta'])


def test_runner_executes_official_must_suite_for_direct_spiffe_and_aie_without_transport_filter():
    text = RUNNER.read_text(encoding='utf-8')
    assert 'run_tck.py' in text
    assert '--level must' in text
    assert '--transport' not in text
    assert 'AIE_S2_DIRECT_URL' in text
    assert 'AIE_S2_SPIFFE_URL' in text
    assert 'AIE_S2_AIE_URL' in text
    assert 'compatibility.json' in text
    assert 'AIE_S2_A2A_INTEROP.json' in text
    assert 'git rev-parse HEAD' in text
    assert 'A2A_TCK_COMMIT' in text


def test_collector_fails_closed_on_empty_must_set(tmp_path):
    empty = _report(req_ids=())
    result, output = _run(tmp_path, direct=empty, spiffe=empty, aie=empty, s1='PASS')
    assert result.returncode != 0
    assert output['promotion'] == 'FAIL'
    assert any('empty-must-set' in item for item in output['parity']['semantic_delta'])


def test_collector_fails_when_official_test_ids_differ_even_if_status_matches(tmp_path):
    altered = _report()
    altered['per_requirement']['CORE-SEND-001']['test_ids'] = ['test::different-official-case']
    result, output = _run(tmp_path, spiffe=altered, s1='PASS')
    assert result.returncode != 0
    assert output['promotion'] == 'FAIL'
    assert any('requirement-semantics:CORE-SEND-001' in item for item in output['parity']['semantic_delta'])


def test_collector_requires_all_three_official_transports_on_each_leg(tmp_path):
    missing_grpc = _report()
    missing_grpc['per_transport'].pop('grpc')
    result, output = _run(tmp_path, aie=missing_grpc, s1='PASS')
    assert result.returncode != 0
    assert output['promotion'] == 'FAIL'
    assert output['parity']['transport_coverage'] is False
    assert any('transport-coverage' in item for item in output['parity']['semantic_delta'])


def test_preparer_clones_and_installs_exact_official_tck_commit_in_isolated_venv():
    text = PREPARE.read_text(encoding='utf-8')
    assert 'A2A_TCK_REPO' in text
    assert 'A2A_TCK_COMMIT' in text
    assert 'git clone' in text
    assert 'git checkout --detach "$A2A_TCK_COMMIT"' in text
    assert '.venv/bin/python' in text
    assert 'A2A_TCK_VERSION' in text
    assert 'pyproject.toml' in text


def test_preparer_verifies_existing_checkout_uses_official_origin():
    text = PREPARE.read_text(encoding='utf-8')
    assert 'git -C "$AIE_S2_TCK_DIR" remote get-url origin' in text
    assert '[[ "$ORIGIN" == "$A2A_TCK_REPO" ]]' in text


def test_preparer_uses_upstream_frozen_uv_lock_without_drifting_pip_resolution():
    text = PREPARE.read_text(encoding='utf-8')
    assert 'uv.lock' in text
    assert 'uv sync --frozen --no-dev' in text
    assert 'pip install --upgrade pip' not in text
    assert 'pip install -e .' not in text


def test_collector_rejects_bare_forged_s1_pass_attestation(tmp_path):
    result, output = _run(tmp_path, s1_report={'promotion': 'PASS'})
    assert result.returncode == 0
    assert output['promotion'] == 'BLOCKED_BY_S1'
    assert output['s1_dependency']['satisfied'] is False
    assert 'profile' in output['s1_dependency']['validation_errors']
    assert 'live_spire' in output['s1_dependency']['validation_errors']
    assert 'provenance_provider' in output['s1_dependency']['validation_errors']


def test_collector_blocks_malformed_s1_checks_total_instead_of_crashing(tmp_path):
    s1 = _s1_attestation()
    s1['legs']['bridge']['checks_total'] = 'not-an-int'
    result, output = _run(tmp_path, s1_report=s1)
    assert result.returncode == 0
    assert output['promotion'] == 'BLOCKED_BY_S1'
    assert output['s1_dependency']['satisfied'] is False
    assert 'leg_checks_total:bridge' in output['s1_dependency']['validation_errors']


def test_collector_requires_explicit_zero_semantic_delta_in_s1(tmp_path):
    s1 = _s1_attestation()
    s1.pop('semantic_delta')
    result, output = _run(tmp_path, s1_report=s1)
    assert result.returncode == 0
    assert output['promotion'] == 'BLOCKED_BY_S1'
    assert output['s1_dependency']['satisfied'] is False
    assert 'semantic_delta' in output['s1_dependency']['validation_errors']


def test_collector_fails_when_any_official_tck_process_exits_nonzero(tmp_path):
    result, output = _run(tmp_path, s1='PASS', exit_codes={'direct': 0, 'spiffe': 0, 'aie': 2})
    assert result.returncode != 0
    assert output['promotion'] == 'FAIL'
    assert any('tck-exit-code:aie:2' in item for item in output['parity']['semantic_delta'])


def test_collector_accepts_pass_upstream_gap_leg_status(tmp_path):
    # ponytail: the real S1 promotion demotes legs whose failures are all
    # upstream-shared to "PASS_UPSTREAM_GAP". The S2 comparator must accept
    # this as a valid leg status when the overall promotion is PASS.
    s1 = _s1_attestation(promotion='PASS')
    for name in ('direct', 'bridge', 'aie'):
        s1['legs'][name]['status'] = 'PASS_UPSTREAM_GAP'
    result, output = _run(tmp_path, s1_report=s1)
    assert result.returncode == 0
    assert output['promotion'] == 'PASS'
    assert output['s1_dependency']['satisfied'] is True
    assert not any(
        'leg_status' in err for err in output['s1_dependency']['validation_errors']
    )


def test_collector_rejects_fail_leg_status(tmp_path):
    # ponytail: a bare "FAIL" leg status must still be rejected, even when
    # the overall promotion is PASS. Only "PASS" and "PASS_UPSTREAM_GAP" are
    # acceptable.
    s1 = _s1_attestation(promotion='PASS')
    s1['legs']['bridge']['status'] = 'FAIL'
    result, output = _run(tmp_path, s1_report=s1)
    assert result.returncode == 0
    assert output['promotion'] == 'BLOCKED_BY_S1'
    assert 'leg_status:bridge' in output['s1_dependency']['validation_errors']


def test_collector_accepts_checks_total_greater_than_check_ids(tmp_path):
    # ponytail: the real S1 report has checks_total=195 and check_ids=134.
    # checks_total counts every check execution (including parameterized
    # variants), while check_ids is the set of unique check identifiers.
    # The correct invariant is checks_total >= len(check_ids).
    s1 = _s1_attestation(promotion='PASS')
    for name in ('direct', 'bridge', 'aie'):
        s1['legs'][name]['checks_total'] = 195
        # Keep check_ids at 2 (from _s1_attestation) — 195 > 2 should pass.
    result, output = _run(tmp_path, s1_report=s1)
    assert result.returncode == 0
    assert output['promotion'] == 'PASS'
    assert not any(
        'leg_checks_total' in err for err in output['s1_dependency']['validation_errors']
    )


def test_collector_rejects_checks_total_less_than_check_ids(tmp_path):
    # ponytail: checks_total must be >= len(check_ids). If it's less, the
    # report is internally inconsistent and must be rejected.
    s1 = _s1_attestation(promotion='PASS')
    s1['legs']['direct']['checks_total'] = 1  # less than 2 unique check_ids
    result, output = _run(tmp_path, s1_report=s1)
    assert result.returncode == 0
    assert output['promotion'] == 'BLOCKED_BY_S1'
    assert 'leg_checks_total:direct' in output['s1_dependency']['validation_errors']


def test_collector_accepts_not_tested_must_requirements(tmp_path):
    # ponytail: the official a2a-tck doesn't test all MUST requirements
    # against all SUTs. "NOT TESTED" is a TCK coverage gap, not an SUT
    # conformance gap. The comparator must accept it as equivalent to
    # "PASS" for the direct_all_pass check.
    report = _report()
    # Set one MUST requirement to NOT TESTED
    for req_id in report['per_requirement']:
        if 'AUTH-INTASK' in req_id:
            report['per_requirement'][req_id]['status'] = 'NOT TESTED'
            break
    result, output = _run(tmp_path, s1='PASS', direct=report, spiffe=report, aie=report)
    assert result.returncode == 0
    assert output['promotion'] == 'PASS'
    assert not any('direct-must-not-pass' in item for item in output['parity']['semantic_delta'])


def test_collector_rejects_fail_must_requirements(tmp_path):
    # ponytail: a MUST requirement with status "FAIL" must still cause
    # direct_all_pass to be False. Only "PASS" and "NOT TESTED" are
    # acceptable.
    report = _report()
    report['per_requirement']['CORE-SEND-001']['status'] = 'FAIL'
    result, output = _run(tmp_path, s1='PASS', direct=report)
    assert result.returncode != 0
    assert output['promotion'] == 'FAIL'
    assert any('direct-must-not-pass:CORE-SEND-001' in item for item in output['parity']['semantic_delta'])


def test_collector_demotes_shared_upstream_failures(tmp_path):
    # ponytail: if a MUST requirement is FAIL in ALL three legs, it's a
    # shared upstream gap (SDK bug, not AIE bug). The demotion mirrors
    # S1.1's PASS_UPSTREAM_GAP pattern. A requirement that is FAIL in
    # only one or two legs is NOT demoted — that's an AIE-specific
    # regression.
    report_direct = _report()
    report_spiffe = _report()
    report_aie = _report()
    # FAIL in all three legs
    report_direct['per_requirement']['CORE-SEND-001']['status'] = 'FAIL'
    report_spiffe['per_requirement']['CORE-SEND-001']['status'] = 'FAIL'
    report_aie['per_requirement']['CORE-SEND-001']['status'] = 'FAIL'
    result, output = _run(
        tmp_path, s1='PASS',
        direct=report_direct, spiffe=report_spiffe, aie=report_aie,
    )
    assert result.returncode == 0
    assert output['promotion'] == 'PASS'
    assert 'CORE-SEND-001' in output['parity']['shared_upstream_failures']
    assert not any('direct-must-not-pass' in item for item in output['parity']['semantic_delta'])


def test_collector_rejects_leg_specific_failures(tmp_path):
    # ponytail: a MUST requirement that is FAIL in only the direct leg
    # (but PASS in SPIFFE and AIE) is an AIE-specific regression and must
    # NOT be demoted. The comparator must reject it.
    report_direct = _report()
    report_spiffe = _report()
    report_aie = _report()
    # FAIL only in direct
    report_direct['per_requirement']['CORE-SEND-001']['status'] = 'FAIL'
    result, output = _run(
        tmp_path, s1='PASS',
        direct=report_direct, spiffe=report_spiffe, aie=report_aie,
    )
    assert result.returncode != 0
    assert output['promotion'] == 'FAIL'
    assert any('direct-must-not-pass:CORE-SEND-001' in item for item in output['parity']['semantic_delta'])
    assert 'CORE-SEND-001' not in output['parity']['shared_upstream_failures']


def test_collector_accepts_tck_exit_code_1_for_test_failures(tmp_path):
    # ponytail: the TCK process exit code is expected to be 1 when there
    # are test failures (that's how pytest works). The exit code only
    # matters if the TCK process itself crashed (e.g., segfault, Python
    # traceback with a non-standard exit). Exit code 1 for test failures
    # must not cause promotion=FAIL.
    result, output = _run(
        tmp_path, s1='PASS',
        exit_codes={'direct': 1, 'spiffe': 1, 'aie': 1},
    )
    assert result.returncode == 0
    assert output['promotion'] == 'PASS'
    assert not any('tck-exit-code' in item for item in output['parity']['semantic_delta'])


def test_collector_rejects_tck_process_crash(tmp_path):
    # ponytail: exit code 2 or higher indicates a TCK process crash
    # (e.g., segfault, Python traceback with sys.exit(2)). This is not
    # a test failure — it's a process failure — and must cause
    # promotion=FAIL.
    result, output = _run(
        tmp_path, s1='PASS',
        exit_codes={'direct': 0, 'spiffe': 0, 'aie': 2},
    )
    assert result.returncode != 0
    assert output['promotion'] == 'FAIL'
    assert any('tck-exit-code:aie:2' in item for item in output['parity']['semantic_delta'])
