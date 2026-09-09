# Revocation Freshness Watermark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, authenticated revocation-freshness watermark path that keeps a partitioned worker fail-closed until both a recent authority watermark and the worker's local revocation-state digest agree.

**Architecture:** Extend the existing AIE v0.3 gateway rather than replacing its revocation semantics. The durable store exposes a canonical SHA-256 digest of revocation truth; a new `RevocationFreshnessMonitor` tracks the newest authenticated authority watermark using local monotonic receive time; the existing PR #59 gateway hook consumes `monitor.is_fresh`; and the existing mTLS federation boundary carries `aie-revocation-freshness/0.1` payloads. Actual revocation truth remains `aie-revocation/0.3` and denial after convergence remains `AIE-AUTH-003`.

**Tech Stack:** Python 3.11/3.12/3.13, stdlib `hashlib`, `json`, `time`, SQLite/WAL, existing AIE HTTP+mTLS federation helpers, pytest, GitHub Actions self-hosted AIE matrix, CodeQL.

**Spec:** `docs/superpowers/specs/2026-09-09-partitioned-revocation-freshness-design.md`

## Global Constraints

- Execution MUST start from `main` after AIE PR #59 (`fix(gateway): fail closed on stale revocation view`) has merged; do not reimplement the hook in this plan.
- Unverifiable freshness MUST deny with existing `AIE-FRESH-001`.
- Known local revocation MUST continue to deny with existing `AIE-AUTH-003`.
- Freshness denial MUST happen before budget reservation, policy execution, or upstream effect.
- No freshness monitor configured MUST preserve existing gateway behavior.
- A new/restarted monitor MUST begin stale.
- Remote wall-clock timestamps MUST NOT participate in the freshness admission decision.
- Only authenticated federation identity establishes source trust; payload `source_gateway` is consistency data, not authentication.
- Equal/lower watermark sequences MUST NOT extend freshness.
- A recent watermark MUST NOT make the worker fresh while its local canonical revocation digest differs from the authority digest carried by that watermark.
- This plan does not add consensus, quorum leases, distributed transactions, or a production propagation-SLO claim.
- STUDY-012B integration is a separate follow-on plan in `Aftergraph/intelligence-systems-research`; this plan provides the AIE primitives and a deterministic two-gateway integration proof only.

---

## File Map

- `src/aie_runtime/gateway/durable.py`: canonical local revocation-state digest.
- `src/aie_runtime/gateway/freshness.py` (new): monotonic watermark monitor; no transport concerns.
- `src/aie_runtime/gateway/federation.py`: freshness-watermark publisher over the existing peer transport patterns.
- `src/aie_runtime/gateway/http.py`: authenticated `/federation/revocation-freshness` ingress and monitor wiring.
- `src/aie_runtime/gateway/cli.py`: config-to-monitor wiring only; no background heartbeat scheduler.
- `examples/gateway_config_v03.json`: reference configuration for expected source and TTL.
- `tests/gateway/test_durable.py`: digest determinism and mutation behavior.
- `tests/gateway/test_revocation_freshness_monitor.py` (new): monitor state machine.
- `tests/gateway/test_revocation_federation_v03.py`: publisher payload/peer behavior.
- `tests/gateway/test_http_gateway.py`: authenticated ingress behavior.
- `tests/gateway/test_cli_v03.py`: config wiring and backward compatibility.
- `tests/gateway/test_partitioned_revocation_integration.py` (new): two-view partition/heal proof, including both heal orders.

---

### Task 1: Canonical Revocation-State Digest

**Files:**
- Modify: `src/aie_runtime/gateway/durable.py`
- Test: `tests/gateway/test_durable.py`

**Interfaces:**
- Consumes: existing SQLite table `revocations(lease_id, revoked_at, source_gateway)`.
- Produces: `SQLiteGatewayStore.revocation_state_sha256() -> str`.

The digest is over the complete canonical revocation relation, not SQLite row order. Canonical value:

```python
rows = [
    {
        "lease_id": str(row["lease_id"]),
        "revoked_at": str(row["revoked_at"]),
        "source_gateway": row["source_gateway"],
    }
    for row in query_ordered_by_lease_id
]
raw = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
return hashlib.sha256(raw).hexdigest()
```

- [ ] **Step 1: Add RED tests for deterministic empty and populated digests**

Append tests that construct two stores with the same revocations inserted in opposite orders and prove their digest is identical; also prove a newly added revocation changes the digest.

```python
import hashlib
import json


def _expected_revocation_digest(rows):
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def test_revocation_state_sha256_is_canonical_and_order_independent(tmp_path):
    a = SQLiteGatewayStore(tmp_path / "a.db")
    b = SQLiteGatewayStore(tmp_path / "b.db")
    revocations = [
        ("lease:b", "2026-09-09T17:00:02+00:00", "spiffe://example.org/gateway/a"),
        ("lease:a", "2026-09-09T17:00:01+00:00", "spiffe://example.org/gateway/a"),
    ]
    for lease_id, revoked_at, source in revocations:
        a.revoke(lease_id, revoked_at=revoked_at, source_gateway=source)
    for lease_id, revoked_at, source in reversed(revocations):
        b.revoke(lease_id, revoked_at=revoked_at, source_gateway=source)

    expected = _expected_revocation_digest([
        {"lease_id": "lease:a", "revoked_at": "2026-09-09T17:00:01+00:00", "source_gateway": "spiffe://example.org/gateway/a"},
        {"lease_id": "lease:b", "revoked_at": "2026-09-09T17:00:02+00:00", "source_gateway": "spiffe://example.org/gateway/a"},
    ])
    assert a.revocation_state_sha256() == expected
    assert b.revocation_state_sha256() == expected


def test_revocation_state_sha256_changes_when_revocation_truth_changes(tmp_path):
    store = SQLiteGatewayStore(tmp_path / "gateway.db")
    before = store.revocation_state_sha256()
    store.revoke("lease:parent", revoked_at="2026-09-09T17:00:00+00:00", source_gateway="local-admin")
    assert store.revocation_state_sha256() != before
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python -m pytest -q tests/gateway/test_durable.py -k revocation_state_sha256
```

Expected: FAIL because `SQLiteGatewayStore` has no `revocation_state_sha256` method.

- [ ] **Step 3: Implement the minimal canonical digest**

Add `import hashlib` and:

```python
def revocation_state_sha256(self) -> str:
    with self._connect() as con:
        rows = con.execute(
            "SELECT lease_id,revoked_at,source_gateway FROM revocations ORDER BY lease_id ASC"
        ).fetchall()
    canonical = [
        {
            "lease_id": str(row["lease_id"]),
            "revoked_at": str(row["revoked_at"]),
            "source_gateway": row["source_gateway"],
        }
        for row in rows
    ]
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
```

- [ ] **Step 4: Run focused and durable-store tests**

```bash
python -m pytest -q tests/gateway/test_durable.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aie_runtime/gateway/durable.py tests/gateway/test_durable.py
git commit -m "feat(gateway): hash canonical revocation state"
```

---

### Task 2: Monotonic RevocationFreshnessMonitor

**Files:**
- Create: `src/aie_runtime/gateway/freshness.py`
- Create: `tests/gateway/test_revocation_freshness_monitor.py`

**Interfaces:**
- Consumes: `Callable[[], str]` returning the current local canonical revocation digest.
- Produces:

```python
class RevocationFreshnessMonitor:
    def __init__(
        self,
        *,
        expected_source_gateway: str,
        freshness_ttl: float,
        local_revocation_state_sha256: Callable[[], str],
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None: ...

    def observe(self, *, source_gateway: str, sequence: int, revocation_state_sha256: str) -> bool: ...
    def is_fresh(self) -> bool: ...
    def status(self) -> dict[str, object]: ...
```

State rules:
- initial `last_sequence=None`, `last_confirmed_monotonic=None`, `authority_revocation_state_sha256=None`;
- `freshness_ttl` must be `> 0`;
- source must equal `expected_source_gateway`;
- `type(sequence) is int` and `sequence >= 0`;
- `revocation_state_sha256` must be exactly 64 lowercase hex characters;
- only `sequence > last_sequence` updates state/time;
- accepted watermarks may carry a digest not yet present locally; that state is stored, but `is_fresh()` remains false until the local digest matches;
- `is_fresh()` requires confirmed state, age `<= freshness_ttl`, and digest equality.

- [ ] **Step 1: Write RED state-machine tests**

Create tests covering all of these exact behaviors:

```python
from aie_runtime.gateway.freshness import RevocationFreshnessMonitor


def test_monitor_starts_stale_and_becomes_fresh_on_matching_watermark():
    now = [10.0]
    digest = ["a" * 64]
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: digest[0],
        monotonic_clock=lambda: now[0],
    )
    assert monitor.is_fresh() is False
    assert monitor.observe(
        source_gateway="spiffe://example.org/gateway/a",
        sequence=1,
        revocation_state_sha256="a" * 64,
    ) is True
    assert monitor.is_fresh() is True


def test_monitor_expires_by_local_monotonic_ttl():
    now = [10.0]
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: "a" * 64,
        monotonic_clock=lambda: now[0],
    )
    monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=1, revocation_state_sha256="a" * 64)
    now[0] = 15.001
    assert monitor.is_fresh() is False


def test_duplicate_or_lower_sequence_cannot_extend_freshness():
    now = [10.0]
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: "a" * 64,
        monotonic_clock=lambda: now[0],
    )
    assert monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=5, revocation_state_sha256="a" * 64)
    now[0] = 14.0
    assert monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=5, revocation_state_sha256="a" * 64) is False
    assert monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=4, revocation_state_sha256="a" * 64) is False
    now[0] = 15.001
    assert monitor.is_fresh() is False


def test_new_watermark_does_not_restore_freshness_until_local_digest_matches():
    now = [10.0]
    local = ["a" * 64]
    monitor = RevocationFreshnessMonitor(
        expected_source_gateway="spiffe://example.org/gateway/a",
        freshness_ttl=5.0,
        local_revocation_state_sha256=lambda: local[0],
        monotonic_clock=lambda: now[0],
    )
    assert monitor.observe(source_gateway="spiffe://example.org/gateway/a", sequence=2, revocation_state_sha256="b" * 64)
    assert monitor.is_fresh() is False
    local[0] = "b" * 64
    assert monitor.is_fresh() is True
```

Also add explicit tests for wrong source, bool-as-int rejection (`sequence=True`), negative sequence, uppercase/malformed digest, TTL `<= 0`, and a new monitor after simulated restart starting stale.

- [ ] **Step 2: Run the new file and verify RED**

```bash
python -m pytest -q tests/gateway/test_revocation_freshness_monitor.py
```

Expected: collection/import FAIL because `gateway.freshness` does not exist.

- [ ] **Step 3: Implement the minimal monitor**

```python
from __future__ import annotations

import re
import time
from typing import Callable

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RevocationFreshnessMonitor:
    def __init__(self, *, expected_source_gateway: str, freshness_ttl: float,
                 local_revocation_state_sha256: Callable[[], str],
                 monotonic_clock: Callable[[], float] = time.monotonic) -> None:
        if freshness_ttl <= 0:
            raise ValueError("freshness_ttl must be > 0")
        self.expected_source_gateway = expected_source_gateway
        self.freshness_ttl = float(freshness_ttl)
        self.local_revocation_state_sha256 = local_revocation_state_sha256
        self.monotonic_clock = monotonic_clock
        self.last_sequence: int | None = None
        self.last_confirmed_monotonic: float | None = None
        self.authority_revocation_state_sha256: str | None = None

    def observe(self, *, source_gateway: str, sequence: int, revocation_state_sha256: str) -> bool:
        if source_gateway != self.expected_source_gateway:
            return False
        if type(sequence) is not int or sequence < 0:
            return False
        if not isinstance(revocation_state_sha256, str) or _SHA256_RE.fullmatch(revocation_state_sha256) is None:
            return False
        if self.last_sequence is not None and sequence <= self.last_sequence:
            return False
        self.last_sequence = sequence
        self.last_confirmed_monotonic = float(self.monotonic_clock())
        self.authority_revocation_state_sha256 = revocation_state_sha256
        return True

    def is_fresh(self) -> bool:
        if self.last_confirmed_monotonic is None or self.authority_revocation_state_sha256 is None:
            return False
        age = float(self.monotonic_clock()) - self.last_confirmed_monotonic
        if age < 0 or age > self.freshness_ttl:
            return False
        try:
            return self.local_revocation_state_sha256() == self.authority_revocation_state_sha256
        except Exception:
            return False

    def status(self) -> dict[str, object]:
        current = float(self.monotonic_clock())
        age = None if self.last_confirmed_monotonic is None else current - self.last_confirmed_monotonic
        return {
            "fresh": self.is_fresh(),
            "last_sequence": self.last_sequence,
            "age_seconds": age,
            "authority_revocation_state_sha256": self.authority_revocation_state_sha256,
        }
```

- [ ] **Step 4: Run monitor tests**

```bash
python -m pytest -q tests/gateway/test_revocation_freshness_monitor.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aie_runtime/gateway/freshness.py tests/gateway/test_revocation_freshness_monitor.py
git commit -m "feat(gateway): add revocation freshness monitor"
```

---

### Task 3: Canonical Freshness Watermark Publisher

**Files:**
- Modify: `src/aie_runtime/gateway/federation.py`
- Modify: `tests/gateway/test_revocation_federation_v03.py`

**Interfaces:**
- Consumes: existing peer URLs, source SPIFFE ID, TLS/expected-peer verification path.
- Produces:

```python
class FreshnessWatermarkReplicator:
    def publish(self, *, sequence: int, revocation_state_sha256: str) -> int: ...
```

Canonical payload:

```json
{
  "version": "aie-revocation-freshness/0.1",
  "source_gateway": "spiffe://example.org/gateway/a",
  "sequence": 42,
  "revocation_state_sha256": "<64 lowercase hex>"
}
```

- [ ] **Step 1: Add RED publisher tests**

```python
from aie_runtime.gateway.federation import FreshnessWatermarkReplicator


def test_freshness_replicator_pushes_canonical_watermark_to_all_peers():
    calls = []

    def post(url, payload, timeout):
        calls.append((url, payload, timeout))
        return {"accepted": True}

    replicator = FreshnessWatermarkReplicator(
        ["https://gw-b.example/federation/revocation-freshness"],
        source_gateway="spiffe://example.org/gateway/a",
        http_post=post,
    )
    assert replicator.publish(sequence=42, revocation_state_sha256="a" * 64) == 1
    assert calls[0][1] == {
        "version": "aie-revocation-freshness/0.1",
        "source_gateway": "spiffe://example.org/gateway/a",
        "sequence": 42,
        "revocation_state_sha256": "a" * 64,
    }
```

Also add validation tests rejecting `sequence=True`, negative sequence, and non-lowercase/non-64-byte digests before any network call.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/gateway/test_revocation_federation_v03.py -k freshness
```

Expected: FAIL because `FreshnessWatermarkReplicator` does not exist.

- [ ] **Step 3: Implement publisher with the existing transport posture**

Reuse the same peer POST and expected-peer-SPIFFE verification behavior as `RevocationReplicator`. Do not weaken or bypass mTLS verification. Keep sequence generation outside this class so deterministic harnesses control ordering.

- [ ] **Step 4: Run all federation tests**

```bash
python -m pytest -q tests/gateway/test_revocation_federation_v03.py tests/gateway/test_mtls_revocation_federation_v03.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aie_runtime/gateway/federation.py tests/gateway/test_revocation_federation_v03.py
git commit -m "feat(federation): publish revocation freshness watermarks"
```

---

### Task 4: Authenticated Freshness Ingress

**Files:**
- Modify: `src/aie_runtime/gateway/http.py`
- Modify: `tests/gateway/test_http_gateway.py`
- Modify: `tests/gateway/test_mtls_revocation_federation_v03.py`

**Interfaces:**
- `GatewayHTTPServer(..., revocation_freshness_monitor: RevocationFreshnessMonitor | None = None)`.
- `create_http_server(..., revocation_freshness_monitor: RevocationFreshnessMonitor | None = None)`.
- POST `/federation/revocation-freshness` accepts only authenticated identities already present in `federation_trust`.

Ingress behavior:

```python
if body.get("version") != "aie-revocation-freshness/0.1": reject 400
if body.get("source_gateway") != identity.spiffe_id: reject 400
if monitor is None: reject 503
accepted = monitor.observe(
    source_gateway=identity.spiffe_id,
    sequence=body["sequence"],
    revocation_state_sha256=body["revocation_state_sha256"],
)
return 200 {"accepted": true, "sequence": ...} if accepted else 409 {"accepted": false, ...}
```

- [ ] **Step 1: Add RED HTTP tests**

Add tests for:
1. trusted authenticated source + valid watermark => HTTP 200 and monitor sequence advances;
2. unauthenticated/foreign source => HTTP 403 and monitor unchanged;
3. payload/source identity mismatch => HTTP 400;
4. duplicate sequence => HTTP 409 and local freshness timestamp does not advance;
5. endpoint without configured monitor => HTTP 503;
6. malformed digest/sequence => HTTP 409 or 400, but never monitor mutation.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/gateway/test_http_gateway.py tests/gateway/test_mtls_revocation_federation_v03.py -k freshness
```

Expected: FAIL because route and server option do not exist.

- [ ] **Step 3: Implement the ingress route**

Add a dedicated `_federated_revocation_freshness()` handler parallel to `_federated_revocation()`. Reuse `_transport_identity()` and `federation_trust`; do not authenticate from JSON fields.

- [ ] **Step 4: Run focused HTTP/federation tests**

```bash
python -m pytest -q tests/gateway/test_http_gateway.py tests/gateway/test_mtls_revocation_federation_v03.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aie_runtime/gateway/http.py tests/gateway/test_http_gateway.py tests/gateway/test_mtls_revocation_federation_v03.py
git commit -m "feat(federation): accept authenticated freshness watermarks"
```

---

### Task 5: Config Wiring Into the PR #59 Gateway Gate

**Files:**
- Modify: `src/aie_runtime/gateway/cli.py`
- Modify: `tests/gateway/test_cli_v03.py`
- Modify: `examples/gateway_config_v03.json`

**Interfaces:**
- New optional config block under existing `federation`:

```json
"revocation_freshness": {
  "expected_source_gateway": "spiffe://example.org/gateway/a",
  "ttl_seconds": 5.0
}
```

- `build_gateway_from_config()` owns the store and therefore constructs the monitor so its digest callback is bound to the exact same `SQLiteGatewayStore` instance used by the gateway.
- The resulting gateway receives `revocation_freshness_check=monitor.is_fresh` through the PR #59 constructor API.
- `build_server_options_from_config()` exposes the same monitor instance to HTTP ingress; avoid constructing a second monitor.

Because `build_gateway_from_config()` and `build_server_options_from_config()` currently load independently, refactor minimally to one shared builder rather than creating divergent monitor instances. Introduce:

```python
def build_runtime_from_config(
    config_path: str | Path,
    *,
    clock: Callable[[], datetime] | None = None,
    monotonic_clock: Callable[[], float] | None = None,
) -> tuple[AIEGateway, dict[str, Any]]:
    ...
```

Keep `build_gateway_from_config()` and `build_server_options_from_config()` as compatibility wrappers if existing tests/public callers depend on them.

- [ ] **Step 1: Add RED config tests**

Prove:
- no `revocation_freshness` block => gateway hook remains `None` and existing behavior is unchanged;
- configured block => one monitor instance backs both gateway check and HTTP option;
- TTL `<= 0` rejects config;
- omitted expected source rejects configured freshness;
- an initial configured monitor is stale and therefore the gateway fails closed until a valid watermark arrives.

- [ ] **Step 2: Verify RED**

```bash
python -m pytest -q tests/gateway/test_cli_v03.py -k freshness
```

Expected: FAIL because the config block is not wired.

- [ ] **Step 3: Implement shared runtime builder and example config**

Use the existing store path resolution, policy construction, TLS construction, and federation trust logic. Do not add a heartbeat background thread in this task; emission cadence belongs to the deployment/study driver, keeping deterministic test control.

- [ ] **Step 4: Run CLI and gateway compatibility tests**

```bash
python -m pytest -q tests/gateway/test_cli.py tests/gateway/test_cli_v03.py tests/gateway/test_gateway_core.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aie_runtime/gateway/cli.py tests/gateway/test_cli_v03.py examples/gateway_config_v03.json
git commit -m "feat(gateway): wire revocation freshness from config"
```

---

### Task 6: Deterministic Two-View Partition and Both Heal Orders

**Files:**
- Create: `tests/gateway/test_partitioned_revocation_integration.py`

**Interfaces:**
- Consumes: real `SQLiteGatewayStore`, `RevocationFreshnessMonitor`, `AIEGateway`, `RevocationReplicator`, and `FreshnessWatermarkReplicator`.
- Produces: a deterministic engineering validation of the exact safety boundary STUDY-012B ICT-008 needs, without importing the research harness or treatment labels.

The test uses:
- authority store A and worker store B;
- the same parent/descendant authority fixture copied into both gateway states;
- a mutable `monotonic_now = [0.0]` clock;
- a transport switch that can drop either revocation or watermark delivery;
- a protected forwarder that increments `effects["count"]` only when actually called.

- [ ] **Step 1: Write RED partition test for the stale worker**

Scenario:
1. Authority and worker start with matching empty revocation digests.
2. Worker accepts sequence 1 / matching digest and admits one pre-fault protected action.
3. Partition turns on.
4. Authority revokes the parent lease; worker does not receive the event.
5. Advance worker monotonic time past TTL.
6. Worker attempts descendant protected action.
7. Assert `AIE-FRESH-001`, unchanged budget, and no protected effect.

This test is RED until Tasks 1-5 are present.

- [ ] **Step 2: Add watermark-first heal ordering test**

While partition heals, deliver a new authority watermark **before** the missing revocation event. Assert:
- watermark is accepted as the newest authority statement;
- worker remains not fresh because local digest does not equal watermark digest;
- action remains denied `AIE-FRESH-001` with zero effect;
- after the real revocation event is persisted, `monitor.is_fresh()` becomes true;
- retry then denies through normal ancestor revocation with `AIE-AUTH-003`.

- [ ] **Step 3: Add revocation-first heal ordering test**

Deliver the missing revocation event first. Assert:
- worker still remains stale until a newer watermark is accepted;
- action cannot run during that gap;
- after watermark arrival, worker is fresh but authority resolution still returns `AIE-AUTH-003`.

- [ ] **Step 4: Run integration tests**

```bash
python -m pytest -q tests/gateway/test_partitioned_revocation_integration.py
```

Expected: PASS after Tasks 1-5.

- [ ] **Step 5: Run the complete gateway suite**

```bash
python -m pytest -q tests/gateway
```

Expected: PASS with zero failures.

- [ ] **Step 6: Commit**

```bash
git add tests/gateway/test_partitioned_revocation_integration.py
git commit -m "test(gateway): prove partition-safe revocation convergence"
```

---

### Task 7: Full Repository Verification and PR Claim Boundary

**Files:**
- Modify only if verification reveals a real regression; do not preemptively change unrelated files.

**Interfaces:**
- Produces: fresh verification evidence suitable for the AIE PR description and later STUDY-012B integration.

- [ ] **Step 1: Run compile and full test suite locally/on the self-hosted environment**

```bash
python -m compileall -q src interop/s1
python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Verify the original PR #59 safety contract still passes**

```bash
python -m pytest -q tests/gateway/test_partitioned_revocation_freshness.py
```

Expected: PASS, including stale detector denial before reservation/effect.

- [ ] **Step 3: Verify the new partition proof separately**

```bash
python -m pytest -q tests/gateway/test_partitioned_revocation_integration.py
```

Expected: PASS for partition, watermark-first heal, and revocation-first heal.

- [ ] **Step 4: Open a focused AIE PR**

PR title:

```text
feat(gateway): add partition-safe revocation freshness watermarks
```

PR body must state all of the following:
- this implements the bounded-TTL + digest design;
- PR #59 is a prerequisite and remains the execution-plane fail-closed hook;
- watermark freshness is distinct from revocation truth;
- the tested claim is bounded fail-closed behavior in the deterministic partition model;
- no real-world distributed-systems correctness or universal RPT bound is claimed;
- STUDY-012B remains separate and must not mark confirmatory evidence merely because this PR is green.

- [ ] **Step 5: Wait for and inspect CI rather than inferring success**

Required checks:
- AIE v0.4 self-hosted matrix: Python 3.11, 3.12, 3.13 all success;
- CodeQL success;
- no unexpected cancelled matrix caused by a superseding commit is presented as proof of success.

- [ ] **Step 6: Commit any verification-only documentation amendment only if needed**

If no source change is needed, do not create a meaningless final commit.

---

## Follow-On Boundary: STUDY-012B

After this AIE PR is merged, create a separate implementation plan in `Aftergraph/intelligence-systems-research` for ICT-008. That plan must pin the merged AIE SHA and replace only the partitioned-revocation treatment primitive with the real AIE implementation. It must preserve the preregistered actor intent, admission history, logical fault schedule, heal schedule, treatment-blind ground-truth classification, `HARNESS_VALIDATION_ONLY`, `BEHAVIORAL_FIXTURE_VALIDATION`, and `confirmatory_eligible=false` boundaries from the accepted design. No research result is promoted merely because this engineering plan passes.

## Self-Review

- **Spec coverage:** digest agreement, bounded TTL, source binding, replay resistance, restart-stale behavior, both heal orders, pre-effect fail-closed behavior, backward compatibility, authenticated transport, and two-view integration are each mapped to a concrete task.
- **Scope:** AIE runtime work is isolated here; the ISR experimental harness is intentionally deferred to its own plan after an exact merged AIE SHA exists.
- **Placeholder scan:** no TBD/TODO/"implement later" steps; every code-bearing task has explicit interfaces, RED command, GREEN command, and commit boundary.
- **Type consistency:** all later tasks consume `SQLiteGatewayStore.revocation_state_sha256()`, `RevocationFreshnessMonitor.observe(...)`, `RevocationFreshnessMonitor.is_fresh()`, and `FreshnessWatermarkReplicator.publish(...)` with the signatures defined above.
- **Claim boundary:** passing this plan supports only the narrow engineering claim described in the design spec; it does not establish confirmatory Institution Layer evidence.
