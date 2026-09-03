#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def load_versions() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in (HERE / 'versions.env').read_text(encoding='utf-8').splitlines():
        raw = raw.strip()
        if not raw or raw.startswith('#'):
            continue
        key, value = raw.split('=', 1)
        values[key] = value
    return values


def must_requirements(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    requirements = report.get('per_requirement') or {}
    return {
        str(req_id): dict(entry)
        for req_id, entry in requirements.items()
        if str((entry or {}).get('level', '')).upper() == 'MUST'
    }


def card_semantics(report: dict[str, Any]) -> dict[str, Any]:
    card = report.get('agent_card') or {}
    return {
        'protocolVersion': card.get('protocolVersion'),
        'capabilities': card.get('capabilities'),
        'defaultInputModes': card.get('defaultInputModes'),
        'defaultOutputModes': card.get('defaultOutputModes'),
        'skills': card.get('skills'),
    }


def validate_s1_attestation(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get('profile') != 'AIE Draft 0.4-S1.1 External CI Closure':
        errors.append('profile')
    if report.get('promotion') != 'PASS':
        errors.append('promotion')
    if report.get('mcp_revision') != '2026-07-28':
        errors.append('mcp_revision')
    if report.get('live_spire') != 'PASS':
        errors.append('live_spire')

    required_external = {
        'svid_rotation_live',
        'trust_bundle_rotation_live',
        'old_trust_rejected',
        'new_trust_works',
    }
    external = report.get('external_gates') or {}
    for gate in sorted(required_external):
        if external.get(gate) != 'PASS':
            errors.append(f'external_gate:{gate}')

    legs = report.get('legs') or {}
    check_sets: list[tuple[str, ...]] = []
    for name in ('direct', 'bridge', 'aie'):
        leg = legs.get(name) or {}
        check_ids = tuple(sorted(str(value) for value in (leg.get('check_ids') or [])))
        check_sets.append(check_ids)
        if leg.get('status') != 'PASS':
            errors.append(f'leg_status:{name}')
        if not check_ids:
            errors.append(f'leg_checks_empty:{name}')
        try:
            checks_total = int(leg.get('checks_total'))
        except (TypeError, ValueError):
            errors.append(f'leg_checks_total:{name}')
        else:
            if checks_total != len(check_ids):
                errors.append(f'leg_checks_total:{name}')
    if not (check_sets[0] == check_sets[1] == check_sets[2]):
        errors.append('leg_check_id_parity')

    if report.get('semantic_delta') != []:
        errors.append('semantic_delta')

    provenance = report.get('provenance') or {}
    if provenance.get('provider') != 'github-actions':
        errors.append('provenance_provider')
    for key in ('run_id', 'git_sha', 'workflow_ref'):
        if not str(provenance.get(key) or '').strip():
            errors.append(f'provenance:{key}')
    git_sha = str(provenance.get('git_sha') or '')
    if git_sha and (len(git_sha) != 40 or any(ch not in '0123456789abcdefABCDEF' for ch in git_sha)):
        errors.append('provenance:git_sha_format')

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description='Aggregate official A2A TCK parity evidence for AIE S2.')
    parser.add_argument('--direct', type=Path, required=True)
    parser.add_argument('--spiffe', type=Path, required=True)
    parser.add_argument('--aie', type=Path, required=True)
    parser.add_argument('--direct-exit-code', type=Path, required=True)
    parser.add_argument('--spiffe-exit-code', type=Path, required=True)
    parser.add_argument('--aie-exit-code', type=Path, required=True)
    parser.add_argument('--s1-promotion', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    reports = {
        'direct': load_json(args.direct),
        'spiffe': load_json(args.spiffe),
        'aie': load_json(args.aie),
    }
    must = {name: must_requirements(report) for name, report in reports.items()}
    ids = {name: set(values) for name, values in must.items()}
    ids_equal = ids['direct'] == ids['spiffe'] == ids['aie']

    semantic_delta: list[str] = []
    if not ids['direct']:
        semantic_delta.append('empty-must-set:direct')
    if not ids_equal:
        semantic_delta.append(
            'requirement-id-set:'
            + json.dumps({name: sorted(value) for name, value in ids.items()}, sort_keys=True)
        )

    statuses_equal = True
    for req_id in sorted(set().union(*ids.values())):
        entries = [must[name].get(req_id) for name in ('direct', 'spiffe', 'aie')]
        if any(entry is None for entry in entries):
            statuses_equal = False
            continue
        signature = [
            {
                'status': entry.get('status'),
                'transports': entry.get('transports') or {},
                'test_ids': sorted(entry.get('test_ids') or []),
            }
            for entry in entries
        ]
        if not (signature[0] == signature[1] == signature[2]):
            statuses_equal = False
            semantic_delta.append(f'requirement-semantics:{req_id}:{json.dumps(signature, sort_keys=True)}')

    direct_all_pass = True
    for req_id, entry in sorted(must['direct'].items()):
        if str(entry.get('status', '')).upper() != 'PASS':
            direct_all_pass = False
            semantic_delta.append(f'direct-must-not-pass:{req_id}:{entry.get("status")}')

    required_transports = {'grpc', 'jsonrpc', 'http_json'}
    transport_coverage = True
    transport_summaries: dict[str, dict[str, Any]] = {}
    for name, report in reports.items():
        per_transport = report.get('per_transport') or {}
        transport_summaries[name] = {transport: per_transport.get(transport) for transport in sorted(required_transports)}
        missing = sorted(required_transports - set(per_transport))
        empty = sorted(
            transport for transport in required_transports
            if transport in per_transport and int((per_transport.get(transport) or {}).get('total', 0)) <= 0
        )
        if missing or empty:
            transport_coverage = False
            semantic_delta.append(f'transport-coverage:{name}:missing={missing}:empty={empty}')

    exit_codes = {
        'direct': int(args.direct_exit_code.read_text(encoding='utf-8').strip()),
        'spiffe': int(args.spiffe_exit_code.read_text(encoding='utf-8').strip()),
        'aie': int(args.aie_exit_code.read_text(encoding='utf-8').strip()),
    }
    for name, code in exit_codes.items():
        if code != 0:
            semantic_delta.append(f'tck-exit-code:{name}:{code}')

    card_signatures = {name: card_semantics(report) for name, report in reports.items()}
    cards_equal = card_signatures['direct'] == card_signatures['spiffe'] == card_signatures['aie']
    if not cards_equal:
        semantic_delta.append('agent-card-semantics:' + json.dumps(card_signatures, sort_keys=True))

    s1 = load_json(args.s1_promotion)
    s1_status = str(s1.get('promotion') or '')
    s1_validation_errors = validate_s1_attestation(s1)
    s1_satisfied = not s1_validation_errors
    if semantic_delta or not direct_all_pass or not statuses_equal:
        promotion = 'FAIL'
    elif not s1_satisfied:
        promotion = 'BLOCKED_BY_S1'
    else:
        promotion = 'PASS'

    versions = load_versions()
    output = {
        'version': 'aie-s2-a2a-interop/0.1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'provenance': {
            'a2a_protocol_version': versions['A2A_PROTOCOL_VERSION'],
            'a2a_tck_version': versions['A2A_TCK_VERSION'],
            'a2a_tck_commit': versions['A2A_TCK_COMMIT'],
            'a2a_tck_repo': versions['A2A_TCK_REPO'],
            'a2a_python_sdk_reference_version': versions['A2A_PYTHON_SDK_VERSION'],
        },
        's1_dependency': {
            'promotion': s1_status,
            'satisfied': s1_satisfied,
            'validation_errors': s1_validation_errors,
            'source': str(args.s1_promotion),
        },
        'must_requirement_ids': sorted(ids['direct']),
        'legs': {
            name: {
                'report': str(path),
                'must_count': len(must[name]),
                'must_compatibility': (reports[name].get('summary') or {}).get('must_compatibility'),
                'tck_exit_code': exit_codes[name],
            }
            for name, path in [('direct', args.direct), ('spiffe', args.spiffe), ('aie', args.aie)]
        },
        'parity': {
            'ids_equal': ids_equal,
            'statuses_equal': statuses_equal,
            'agent_card_semantics_equal': cards_equal,
            'transport_coverage': transport_coverage,
            'transport_summaries': transport_summaries,
            'semantic_delta': semantic_delta,
        },
        'promotion': promotion,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'promotion': promotion, 'output': str(args.output)}))
    return 1 if promotion == 'FAIL' else 0


if __name__ == '__main__':
    raise SystemExit(main())
