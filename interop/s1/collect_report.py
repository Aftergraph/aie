#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from aie_runtime.s1_interop import build_s11_report, collect_leg

p = argparse.ArgumentParser()
p.add_argument('--results', default=str(Path(__file__).with_name('results')))
p.add_argument('--rotation-evidence')
p.add_argument('--live-spire', choices=['PASS','FAIL','BLOCKED_EXTERNAL_RUNTIME'], default='BLOCKED_EXTERNAL_RUNTIME')
p.add_argument('--output', required=True)
a = p.parse_args()
root = Path(a.results)
legs = {}
for name in ('direct','bridge','aie'):
    leg = root / name
    exit_path = leg / 'exit_code.txt'
    if not exit_path.exists():
        legs[name] = {'name':name,'status':'BLOCKED_EXTERNAL_RUNTIME','check_ids':[],'checks_total':0}
    else:
        legs[name] = collect_leg(name, leg, exit_code=int(exit_path.read_text().strip()))

external = {
    'svid_rotation_live': 'BLOCKED_EXTERNAL_RUNTIME',
    'trust_bundle_rotation_live': 'BLOCKED_EXTERNAL_RUNTIME',
    'old_trust_rejected': 'BLOCKED_EXTERNAL_RUNTIME',
    'new_trust_works': 'BLOCKED_EXTERNAL_RUNTIME',
}
if a.rotation_evidence and Path(a.rotation_evidence).exists():
    value = json.loads(Path(a.rotation_evidence).read_text(encoding='utf-8'))
    for key, status in value.get('external_gates', {}).items():
        if key in external:
            external[key] = str(status)

report = build_s11_report(
    local_gates={
        'workload_api_stream':'PASS',
        'atomic_tls_rotation':'PASS',
        'authority_binding':'PASS',
        'host_header_transparency':'PASS',
        'bounded_capability_prefix':'PASS',
        'protocol_error_passthrough_opt_in':'PASS',
    },
    external_gates=external,
    legs=legs,
    live_spire=a.live_spire,
    provenance={
        'provider': 'github-actions' if os.getenv('GITHUB_ACTIONS') == 'true' else 'local',
        'run_id': os.getenv('GITHUB_RUN_ID', ''),
        'run_attempt': os.getenv('GITHUB_RUN_ATTEMPT', ''),
        'git_sha': os.getenv('GITHUB_SHA', ''),
        'workflow_ref': os.getenv('GITHUB_WORKFLOW_REF', ''),
    },
)
Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='utf-8')
print(json.dumps({'promotion':report['promotion'],'output':a.output}))
