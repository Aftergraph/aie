# Partition-Safe Revocation Freshness Design

Date: 2026-09-09
Status: Design for review
Scope: AIE gateway and federation freshness semantics required by STUDY-012B ICT-008

## 1. Problem

AIE currently has two useful revocation mechanisms:

1. the gateway checks local durable and in-memory revocation state before authority admission; and
2. `RevocationReplicator` pushes canonical `aie-revocation/0.3` events to configured peers.

Those mechanisms are sufficient when the worker's revocation view is current. They are not sufficient to prove that the view is current during a network partition. A push-only channel cannot distinguish "no revocations have occurred" from "the revocation source is unreachable and an event was missed".

The result is a distributed TOCTOU gap: a worker can retain a locally valid descendant lease after the authoritative side has revoked its ancestor.

A connectivity heartbeat alone is also insufficient. If a partition heals and a heartbeat arrives before the missed revocation event, a heartbeat-only design could incorrectly reopen execution while the worker still has stale revocation state.

The design must therefore prove both recent contact and revocation-state convergence before a configured gateway may treat its distributed revocation view as fresh.

## 2. Goals

The implementation must provide all of the following:

- an independent freshness signal that does not infer connectivity from absence of revocation events;
- cryptographic binding between the authority's current revocation set and the worker's applied revocation set;
- bounded stale-authority exposure during a partition;
- fail-closed admission with the existing `AIE-FRESH-001` error when freshness is unverifiable;
- no budget reservation and no protected external effect after freshness denial;
- monotonic anti-replay semantics for freshness confirmations;
- deterministic, injectable local monotonic time for conformance and STUDY-012B validation;
- safe restart semantics where an unconfirmed monitor starts stale;
- safe partition healing regardless of whether the watermark or missed revocation event arrives first;
- return to normal `AIE-AUTH-003` revocation denial after convergence;
- backward compatibility when no freshness monitor is configured.

## 3. Non-Goals

This slice will not implement consensus, quorum leases, global linearizability, distributed transactions, or a production SLO for revocation propagation time.

It will not claim that a freshness timeout makes revocation instantaneous. The configured freshness TTL defines the maximum period in which a partitioned worker may still consider a previously synchronized view fresh.

It will not change the existing meaning of `AIE-AUTH-003` or invent a new authority error. Unverifiable freshness is already represented by `AIE-FRESH-001` in the Draft 0.3 error registry.

It will not replace `aie-revocation/0.3`. Existing revocation events remain the authoritative mechanism for applying individual revoked lease identifiers.

## 4. Alternatives Considered

### A. Synchronous authority lookup on every action

Each worker asks the authoritative gateway whether its revocation state is current before every protected action.

Advantages:

- conceptually simple;
- minimal stale window when the authority is reachable.

Disadvantages:

- converts every protected action into a distributed round trip;
- couples availability and latency directly to the authority service;
- turns a short control-plane outage into an immediate global execution outage;
- does not fit AIE's portable local enforcement model well.

### B. Monotonic freshness watermark with revocation-state digest and bounded TTL

The authority emits authenticated, monotonically increasing freshness confirmations. Each confirmation carries a SHA-256 digest of the authority's canonical revocation state. A worker records the newest accepted sequence, the authority digest, and the local monotonic receive time.

A worker is fresh only when both conditions hold:

1. the confirmation is still within the configured TTL; and
2. the worker's locally computed revocation-state digest equals the authority digest in that confirmation.

Advantages:

- no network round trip on the execution path;
- deterministic fail-closed behavior under partition;
- a heartbeat cannot reopen execution before missed revocations have actually converged;
- local monotonic time avoids using remote wall clock for TTL evaluation;
- replayed or reordered confirmations cannot extend freshness once observed;
- restart can safely begin stale until a new confirmation arrives;
- existing `aie-revocation/0.3` events remain unchanged.

Disadvantages:

- there is a deliberate bounded stale window equal to the TTL;
- the authority must emit periodic confirmations;
- both peers need a canonical revocation-state digest implementation;
- operational tuning is required for the TTL and heartbeat cadence.

### C. Quorum or consensus-backed revocation state

Require a quorum or consensus protocol before workers may execute protected actions.

Advantages:

- stronger consistency model.

Disadvantages:

- substantially more operational and protocol complexity;
- changes AIE from a portable institution layer into a distributed consensus system;
- unnecessary for the present falsification and conformance objective.

## 5. Decision

Use option B: an authenticated monotonic freshness watermark carrying a canonical revocation-state digest, combined with a bounded TTL.

The design deliberately separates three concerns:

1. **Revocation truth**: existing AIE revocation rows and `AIE-AUTH-003`.
2. **Freshness truth**: whether the worker can prove that its local revocation set matches a recent authority watermark, represented by `AIE-FRESH-001` when it cannot.
3. **Transport**: how trusted freshness confirmations and revocation events reach a peer.

This prevents both missing revocation events and out-of-order partition healing from being misinterpreted as permission to execute.

## 6. Components

### 6.1 Gateway freshness gate

AIE PR #59 introduces an optional `revocation_freshness_check: Callable[[], bool]` boundary on `AIEGateway`.

When configured, the gateway runs the check after local authority resolution and before budget reservation. The same gate applies to `handle()` and `forward()`.

Semantics:

- exactly `True` means the revocation view is fresh enough to continue;
- `False`, `None`, any other value, or detector exception maps to `AIE-FRESH-001`;
- denial occurs before budget reservation, policy execution, or upstream effect;
- absence of a configured check preserves current behavior.

### 6.2 Canonical revocation-state digest

Add a deterministic digest operation to `SQLiteGatewayStore`:

```text
revocation_state_sha256() -> str
```

Canonical input is the ordered list of the store's revocation truth rows projected to:

```text
[
  {"lease_id": <string>, "revoked_at": <string>},
  ...
]
```

Rows are sorted lexicographically by `lease_id` before canonical JSON serialization and SHA-256 hashing.

`source_gateway` is intentionally excluded from the digest. The authoritative store may record a local administrative source while a replica records the authenticated federation gateway as its source. The revocation truth that must converge is the revoked lease and its authoritative `revoked_at` value.

The existing `INSERT OR IGNORE` primary-key behavior makes the first accepted revocation tuple stable for each lease.

### 6.3 `RevocationFreshnessMonitor`

Add a small stateful component under a dedicated `aie_runtime.gateway.freshness` module.

Conceptual state:

```text
expected_source_gateway: str
freshness_ttl_seconds: float
last_sequence: int | None
last_authority_revocation_sha256: str | None
last_confirmed_monotonic: float | None
clock: Callable[[], float]
local_revocation_digest: Callable[[], str]
```

Public behavior:

```text
observe(source_gateway, sequence, revocation_state_sha256) -> bool
is_fresh() -> bool
status() -> diagnostic snapshot
```

Rules:

- a new monitor is stale until it accepts a trusted confirmation;
- `source_gateway` must match the configured source;
- `sequence` must be a non-negative integer;
- `revocation_state_sha256` must be a lowercase 64-character SHA-256 hex digest;
- only a strictly greater sequence updates the remembered authority digest and receive time;
- equal or lower sequence values are replay/stale input and do not refresh freshness;
- `is_fresh()` requires both `clock() - last_confirmed_monotonic <= TTL` and `local_revocation_digest() == last_authority_revocation_sha256`;
- local digest failure, monitor failure, timeout, or digest mismatch is not fresh;
- monitor errors never cause the gateway to fail open.

Using local monotonic receive time avoids trusting a remote wall clock for the TTL decision.

### 6.4 Freshness watermark transport

Define a small canonical federation payload, versioned separately from revocation events:

```json
{
  "version": "aie-revocation-freshness/0.1",
  "source_gateway": "spiffe://example.org/gateway/a",
  "sequence": 42,
  "revocation_state_sha256": "<64 lowercase hex characters>"
}
```

The transport boundary reuses the existing authenticated federation identity and trust checks. A payload field alone never establishes trust.

The authority increments `sequence` for each emitted freshness confirmation, not only for revocations. This makes duplicate and reorder detection independent of whether revocation state changed.

A receiving peer passes the authenticated source identity, sequence, and digest to its monitor. Old, duplicated, foreign-source, malformed, or unauthenticated watermarks do not refresh freshness.

The application-level sequence is defense against duplicate and reordered deliveries. Transport authenticity remains anchored in the existing mTLS or explicitly trusted reference identity boundary.

### 6.5 Revocation transport remains authoritative

The existing `aie-revocation/0.3` event remains the mechanism that carries the actual revoked lease identifier and authoritative `revoked_at` timestamp.

The watermark does not replace revocation truth. It states: "the authority's canonical revocation set currently hashes to this value, and this is freshness sequence N."

After a partition heals, either delivery order is safe.

**Revocation first:**

1. the missed revocation event is persisted to the worker store;
2. local digest changes;
3. the worker remains stale until it receives a current authority watermark matching that digest;
4. once the watermark arrives, freshness may recover;
5. normal authority resolution denies the revoked descendant with `AIE-AUTH-003`.

**Watermark first:**

1. the worker accepts the newer watermark sequence and authority digest;
2. local digest does not match because the revocation event is still missing;
3. `is_fresh()` remains false and gateway decisions continue to deny `AIE-FRESH-001`;
4. the missed revocation event arrives and changes the local digest to the authority digest;
5. freshness may recover while the watermark remains inside TTL;
6. normal authority resolution denies the revoked descendant with `AIE-AUTH-003`.

A heartbeat therefore cannot reopen execution before revocation-state convergence.

## 7. Execution Data Flow

### Healthy path

```text
authority computes revocation digest D
    -> authority emits sequence N, digest D
    -> authenticated federation transport
    -> worker monitor observes N and D at local monotonic time T
    -> worker local revocation digest is also D
    -> protected action arrives before T + TTL
    -> local authority resolution passes
    -> monitor.is_fresh() == True
    -> budget reservation / policy / effect may continue
```

### Partition path

```text
worker last observes sequence N, digest D0 at T0
    -> network partition begins
    -> authority revokes parent lease, authority digest becomes D1
    -> authority continues emitting newer sequence values carrying D1
    -> worker receives neither revocation nor watermarks
    -> freshness TTL expires locally
    -> protected descendant action arrives
    -> local revocation view still hashes to D0 and appears unrevoked
    -> monitor.is_fresh() == False
    -> gateway denies AIE-FRESH-001 before reservation/effect
```

### Heal path with watermark arriving first

```text
partition heals
    -> worker receives sequence N+k carrying D1
    -> worker local digest is still D0
    -> monitor remains stale because D0 != D1
    -> missed aie-revocation/0.3 event reaches worker
    -> local store digest becomes D1
    -> monitor can now be fresh within TTL
    -> descendant retry resolves ancestor revocation
    -> gateway denies AIE-AUTH-003
```

## 8. Failure Semantics

| Failure | Result |
|---|---|
| No monitor configured | Existing gateway behavior, backward compatible |
| Monitor never confirmed | `AIE-FRESH-001` |
| Freshness TTL expired | `AIE-FRESH-001` |
| Local digest differs from authority watermark | `AIE-FRESH-001` |
| Local digest cannot be computed | `AIE-FRESH-001` |
| Freshness callback raises | `AIE-FRESH-001` |
| Replayed/equal sequence | Does not refresh freshness |
| Lower sequence | Does not refresh freshness |
| Foreign source | Does not refresh freshness |
| Malformed digest | Does not refresh freshness |
| Revocation known locally | `AIE-AUTH-003` |
| Watermark arrives before missed revocation | Remains `AIE-FRESH-001` until local digest converges |
| Revocation arrives before watermark | Remains `AIE-FRESH-001` until a matching current watermark arrives |
| Process restart | Monitor begins stale until a new trusted confirmation is observed |

Restart behavior is intentionally fail closed. Persisting a stale "fresh" flag across restart would convert missing liveness evidence into authority.

## 9. Ordering and Race Semantics

Freshness must be checked immediately before the first irreversible execution-plane side effect controlled by the gateway. In the current gateway this means before budget reservation and before any upstream forwarding.

A future asynchronous gateway that queues an action for later execution must re-check freshness at execution time. Admission-time freshness alone is not sufficient for queued work.

The monitor does not make revocation and action execution atomic across machines. It bounds the stale window and fails closed once freshness can no longer be proven. The stale window can never be smaller than the configured TTL without a synchronous authority check or stronger distributed-consistency mechanism.

## 10. STUDY-012B ICT-008 Mapping

The empirical validation harness uses two independent authority views:

- an authoritative store where the parent revocation occurs; and
- a worker store that remains stale while the deterministic partition is active.

All I5-derived ablations receive the same actor intent, admission history, authoritative revocation event, partition schedule, logical timing, worker initial digest, and heal schedule.

The treatment difference is narrow:

- `I5`, `I5+MB`, and `I5+B` do not configure the RP freshness gate for ICT-008, so the stale local authority view permits the protected fixture effect;
- `I5+RP` configures the real AIE freshness monitor, whose TTL expires before the protected action, so the gateway denies with `AIE-FRESH-001` before the fixture handler;
- after heal, the harness delivers the same real revocation event and watermark through the worker-side AIE federation/freshness primitives;
- digest convergence is required before freshness may recover;
- subsequent authority evaluation denies with `AIE-AUTH-003`.

The harness records logical fault-schedule time separately from implementation latency. `partition_logical_rpt_ms` remains `HARNESS_VALIDATION_ONLY` and `partition_rpt_confirmatory_eligible=false`.

RAAR is measured from whether delegated capability remains usable after the authoritative revocation event. In the diagnostic ICT-008 slice:

- stale baseline worker effect succeeds: RAAR = 1.0;
- freshness-enforced worker effect is denied: RAAR = 0.0.

No confirmatory or performance claim follows from those deterministic validation values.

## 11. Test Strategy

### Gateway unit tests

- stale detector denies `handle()` with `AIE-FRESH-001` before reservation;
- detector exception denies identically;
- stale detector denies `forward()` before upstream call;
- fresh detector preserves the existing authority and budget path;
- no detector preserves all existing behavior.

### Store digest tests

- empty revocation stores have one stable canonical SHA-256 value;
- insertion order does not affect the digest;
- identical `lease_id` and `revoked_at` rows on authority and worker produce the same digest despite different `source_gateway` metadata;
- adding a new revocation changes the digest;
- duplicate `INSERT OR IGNORE` does not change the digest.

### Monitor unit tests

- unconfirmed monitor is stale;
- first valid sequence with a matching local digest makes it fresh;
- valid watermark with mismatched local digest remains stale;
- local monotonic time beyond TTL makes it stale;
- strictly newer sequence refreshes the authority digest and freshness timestamp;
- duplicate sequence does not refresh;
- lower sequence does not refresh;
- wrong source does not refresh;
- malformed digest does not refresh;
- local digest exception fails closed;
- restart/new monitor starts stale.

### Federation tests

- authenticated watermark from expected gateway is accepted;
- foreign or unauthenticated source is rejected;
- delivery to configured peers preserves sequence, source binding, and digest;
- dropped transport does not mutate worker monitor state;
- replayed delivery cannot extend freshness;
- watermark-before-revocation does not reopen the gateway;
- revocation-before-watermark does not reopen the gateway until a matching watermark arrives.

### Partition integration test

Use two gateway stores/views and a deterministic transport fault switch:

1. establish identical authority and worker revocation digests;
2. deliver a trusted freshness watermark and prove the worker is fresh;
3. admit a descendant action before revocation;
4. partition the federation channel;
5. revoke the parent on the authority side, changing only the authority digest;
6. advance deterministic local monotonic time past TTL;
7. attempt the queued protected action at the stale worker;
8. prove `AIE-FRESH-001`, no budget reservation, and zero protected effect under RP freshness enforcement;
9. heal the channel and deliberately deliver the new watermark before the missed revocation;
10. prove the worker remains stale because the digests differ;
11. deliver the real `aie-revocation/0.3` event;
12. prove digest convergence and post-heal `AIE-AUTH-003`.

The reverse heal order must also be covered so neither message ordering can reopen stale authority.

## 12. Acceptance Criteria

The design is complete when all of the following are true:

- the gateway fail-closed hook is green across supported Python versions;
- `SQLiteGatewayStore.revocation_state_sha256()` is deterministic and source-metadata-independent;
- a deterministic `RevocationFreshnessMonitor` is green against replay, TTL, digest mismatch, source binding, and restart tests;
- authenticated federation transport can carry monotonic freshness confirmations and revocation-state digests without altering `aie-revocation/0.3` semantics;
- both partition-heal message orders preserve fail-closed behavior until revocation-state convergence;
- a two-view partition test demonstrates stale worker state, TTL expiry, pre-effect `AIE-FRESH-001`, heal, digest convergence, and post-heal `AIE-AUTH-003`;
- no existing AIE conformance test regresses;
- STUDY-012B ICT-008's RED behavioral assertions become GREEN without giving the ground-truth classifier access to treatment condition;
- the record remains `BEHAVIORAL_FIXTURE_VALIDATION`, `HARNESS_VALIDATION_ONLY`, and `confirmatory_eligible=false`.

## 13. Research Claim Boundary

Passing this design's tests would support a narrow engineering statement: AIE can enforce a bounded fail-closed revocation-freshness policy in the tested partition model, including safe convergence when freshness and revocation messages are reordered.

It would not establish real-world distributed-systems correctness, a universal revocation latency bound, or evidence that the full Institution Layer hypothesis is true. Those claims require later preregistered and independent validation.