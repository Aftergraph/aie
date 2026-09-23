#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from firecracker_runtime_v23 import FirecrackerHostAdmission


def main() -> int:
    ap=argparse.ArgumentParser(description='Fail-closed Firecracker/KVM host admission doctor for Pock Bot M8.')
    ap.add_argument('--kvm',default='/dev/kvm')
    ap.add_argument('--firecracker')
    ap.add_argument('--jailer')
    ap.add_argument('--cgroup-root',default='/sys/fs/cgroup')
    ap.add_argument('--required-version')
    args=ap.parse_args()
    status=FirecrackerHostAdmission(
        kvm_path=args.kvm,
        firecracker_path=args.firecracker,
        jailer_path=args.jailer,
        cgroup_root=args.cgroup_root,
        required_version=args.required_version,
    ).status()
    print(json.dumps(status,indent=2,sort_keys=True))
    return 0 if status['readyToAttemptBoot'] else 2

if __name__=='__main__':
    raise SystemExit(main())
