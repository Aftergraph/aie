#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from aie_runtime.gateway.spiffe_http import request_bytes_with_peer_identity
from aie_runtime.gateway.workload_api import WorkloadAPIClient, build_ssl_contexts_from_svid


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def can_reach(target: str, expected_peer: str, context) -> tuple[bool, str]:
    try:
        status, body, _ = request_bytes_with_peer_identity(
            "GET", target, b"", {}, timeout=5.0, ssl_context=context,
            expected_peer_spiffe_id=expected_peer,
        )
        return 200 <= status < 500, f"http:{status}:{body[:80]!r}"
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--expected-peer", required=True)
    parser.add_argument("--ready-file", required=True)
    parser.add_argument("--rotated-file", required=True)
    parser.add_argument("--revoke-signal", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=float, default=150.0)
    args = parser.parse_args()

    client = WorkloadAPIClient(args.endpoint)
    initial = client.fetch_x509_svid(timeout=10.0)
    old_server_ctx, old_client_ctx = build_ssl_contexts_from_svid(initial, require_client_cert=True)
    old_ok_before, old_before_detail = can_reach(args.target, args.expected_peer, old_client_ctx)
    Path(args.ready_file).write_text("ready\n", encoding="utf-8")

    deadline = time.monotonic() + args.timeout
    updated = None
    with client.subscribe_x509_svid() as subscription:
        for material in subscription:
            cert_changed = digest(material.x509_svid) != digest(initial.x509_svid)
            bundle_changed = digest(material.bundle) != digest(initial.bundle)
            if cert_changed and bundle_changed:
                updated = material
                break
            if time.monotonic() > deadline:
                break
    if updated is None:
        Path(args.output).write_text(json.dumps({
            "svid_rotation_live": "FAIL",
            "trust_bundle_rotation_live": "FAIL",
            "old_trust_rejected": "FAIL",
            "reason": "timed out waiting for changed SVID and trust bundle",
        }, indent=2) + "\n", encoding="utf-8")
        return 2

    _, new_client_ctx = build_ssl_contexts_from_svid(updated, require_client_cert=True)
    new_ok_before_revoke, new_before_detail = can_reach(args.target, args.expected_peer, new_client_ctx)
    Path(args.rotated_file).write_text("rotated\n", encoding="utf-8")

    revoke = Path(args.revoke_signal)
    while not revoke.exists() and time.monotonic() <= deadline:
        time.sleep(0.1)
    if not revoke.exists():
        return 3
    # Give every long-lived Workload API watcher a short window to consume the
    # bundle update after the old local authority is revoked.
    time.sleep(2.0)
    old_ok_after, old_after_detail = can_reach(args.target, args.expected_peer, old_client_ctx)
    new_ok_after, new_after_detail = can_reach(args.target, args.expected_peer, new_client_ctx)

    report = {
        "spiffe_id": initial.spiffe_id,
        "initial_svid_sha256": digest(initial.x509_svid),
        "rotated_svid_sha256": digest(updated.x509_svid),
        "initial_bundle_sha256": digest(initial.bundle),
        "rotated_bundle_sha256": digest(updated.bundle),
        "svid_rotation_live": "PASS" if digest(initial.x509_svid) != digest(updated.x509_svid) else "FAIL",
        "trust_bundle_rotation_live": "PASS" if digest(initial.bundle) != digest(updated.bundle) else "FAIL",
        "new_trust_works": "PASS" if new_ok_before_revoke and new_ok_after else "FAIL",
        "old_trust_rejected": "PASS" if old_ok_before and not old_ok_after else "FAIL",
        "details": {
            "old_before": old_before_detail,
            "new_before_revoke": new_before_detail,
            "old_after_revoke": old_after_detail,
            "new_after_revoke": new_after_detail,
        },
    }
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if all(report[key] == "PASS" for key in (
        "svid_rotation_live", "trust_bundle_rotation_live", "new_trust_works", "old_trust_rejected"
    )) else 4


if __name__ == "__main__":
    raise SystemExit(main())
