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

The design must let a configured gateway fail closed when revocation freshness cannot be proven, while preserving the existing gateway contract for deployments that do not opt into distributed freshness enforcement.

## 2. Goals

The implementation must provide all of the following:

- an independent freshness signal that does not infer connectivity from absence of revocation events;
- bounded stale-authority exposure during a partition;
- fail-closed admission with the existing `AIE-FRESH-001` error when freshness is unverifiable;
- no budget reservation and no protected external effect after freshness denial;
- monotonic anti-replay semantics for freshness confirmations;
- deterministic, injectable time for conformance and STUDY-012B validation;
- safe restart semantics where an unconfirmed monitor starts stale;
- explicit partition healing and return to normal `AIE-AUTH-003` revocation denial once the missed revocation is replicated;
- backward compatibility when no freshness monitor is configured.

## 3. Non-Goals

This slice will not implement consensus, quorum leases, global linearizability, distributed transactions, or a production SLO for revocation propagation time.

It will not claim that a freshness timeout makes revocation instantaneous. The mechanism provides a bounded fail-closed window. The configured freshness TTL defines the maximum period in which a partitioned worker may still consider its view current.

It will not change the existing meaning of `AIE-AUTH-003` or invent a new authority error. Unverifiable freshness is already represented by `AIE-FRESH-001` in the Draft 0.3 error registry.

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

### B. Monotonic freshness watermark with bounded TTL

The authority sends authenticated, monotonically increasing freshness confirmations. A worker records the newest accepted sequence and the local monotonic time at which it was observed. The worker is fresh only while the elapsed local time is within a configured TTL.

Advantages:

- no network round trip on the execution path;
- deterministic fail-closed behavior under partition;
- local monotonic time avoids wall-clock synchronization requirements;
- replayed or reordered confirmations cannot extend freshness;
- restart can safely begin stale until a new confirmation arrives.

Disadvantages:

- there is a deliberate bounded stale window equal to the TTL;
- the authority must emit periodic confirmations;
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

Use option B: an authenticated monotonic freshness watermark with a bounded TTL.

The design deliberately separates three concerns:

1. **Revocation truth**: existing AIE revocation state and `AIE-AUTH-003`.
2. **Freshness truth**: whether the worker can prove that its revocation view is recent enough, represented by `AIE-FRESH-001` when it cannot.
3. **Transport**: how trusted freshness confirmations and revocation events reach a peer.

This separation prevents a missing transport event from being misinterpreted as proof that no revocation exists.

## 6. Components

### 6.1 Gateway freshness gate

AIE PR #59 introduces an optional `revocation_freshness_check: Callable[[], bool]` boundary on `AIEGateway`.

When configured, the gateway runs the check after local authority resolution and before budget reservation. The same gate applies to `handle()` and `forward()`.

Semantics:

- exactly `True` means the revocation view is fresh enough to continue;
- `False`, `None`, any other value, or detector exception maps to `AIE-FRESH-001`;
- denial occurs before budget reservation, policy execution, or upstream effect;
- absence of a configured check preserves current behavior.

### 6.2 `RevocationFreshnessMonitor`

Add a small stateful component under `aie_runtime.gateway.federation` or a dedicated `gateway.freshness` module.

Conceptual state:

```text
expected_source_gateway: str
freshness_ttl: timedelta
last_sequence: int | None
last_confirmed_monotonic: float | None
clock: Callable[[], float]
```

Public behavior:

```text
observe(source_gateway, sequence) -> bool
is_fresh() -> bool
status() -> diagnostic snapshot
```

Rules:

- a new monitor is stale until it accepts a trusted confirmation;
- `source_gateway` must match the configured source;
- `sequence` must be a non-negative integer;
- only a strictly greater sequence refreshes `last_confirmed_monotonic`;
- equal or lower sequence values are replay/stale input and must not refresh freshness;
- `is_fresh()` is true only while `clock() - last_confirmed_monotonic <= freshness_ttl`;
- monitor errors never cause the gateway to fail open.

Using local monotonic receive time avoids trusting remote wall clocks for the admission decision.

### 6.3 Freshness watermark transport

Define a small canonical federation payload, versioned separately from revocation events:

```json
{
  "version": "aie-revocation-freshness/0.1",
  "source_gateway": "spiffe://example.org/gateway/a",
  "sequence": 42
}
```

The transport boundary must reuse the existing authenticated federation identity/trust checks. A payload field alone never establishes trust.

The authority increments `sequence` for each emitted freshness confirmation, not only for revocations. This makes replay detection independent of whether revocation state changed.

A receiving peer passes an authenticated source identity and sequence to its monitor. Old, duplicated, foreign-source, malformed, or unauthenticated watermarks do not refresh freshness.

### 6.4 Revocation transport remains authoritative

The existing `aie-revocation/0.3` event remains the mechanism that carries the actual revoked lease identifier.

The watermark does not encode or replace revocation truth. It only proves that the worker has recently communicated with the expected authority source.

After a partition heals:

1. the missed revocation event is delivered and persisted to the worker's durable revocation store;
2. a new monotonic freshness confirmation is accepted;
3. the worker's freshness gate becomes true again;
4. normal authority resolution still denies the revoked descendant through ancestor traversal with `AIE-AUTH-003`.

This prevents a healed worker from becoming executable merely because heartbeat freshness returned.

## 7. Execution Data Flow

### Healthy path

```text
authority emits sequence N
    -> authenticated federation transport
    -> worker monitor observes N at local monotonic time T
    -> protected action arrives before T + TTL
    -> local authority resolution passes
    -> monitor.is_fresh() == True
    -> budget reservation / policy / effect may continue
```

### Partition path

```text
worker last observes sequence N at T0
    -> network partition begins
    -> authority revokes parent lease and continues emitting N+1, N+2, ...
    -> worker receives neither revocation nor watermarks
    -> freshness TTL expires locally
    -> protected descendant action arrives
    -> local revocation view still appears unrevoked
    -> monitor.is_fresh() == False
    -> gateway denies AIE-FRESH-001 before reservation/effect
```

### Heal path

```text
partition heals
    -> authoritative revocation event reaches worker durable store
    -> current watermark sequence reaches monitor
    -> monitor becomes fresh
    -> descendant retry resolves ancestor revocation
    -> gateway denies AIE-AUTH-003
```

## 8. Failure Semantics

| Failure | Result |
|---|---|
| No monitor configured | Existing gateway behavior, backward compatible |
| Monitor never confirmed | `AIE-FRESH-001` |
| Freshness TTL expired | `AIE-FRESH-001` |
| Freshness callback raises | `AIE-FRESH-001` |
| Replayed/equal sequence | Does not refresh freshness |
| Lower sequence | Does not refresh freshness |
| Foreign source | Does not refresh freshness |
| Revocation known locally | `AIE-AUTH-003` |
| Partition heals but revocation delivery is still missing | Freshness may not be restored until both transport obligations are satisfied by deployment policy |
| Process restart | Monitor begins stale until a new trusted confirmation is observed |

The final row is intentionally fail closed. Persisting a stale "fresh" flag across restart would convert missing liveness evidence into authority.

## 9. Ordering and Race Semantics

Freshness must be checked immediately before the first irreversible execution-plane side effect controlled by the gateway. In the current gateway this means before budget reservation and before any upstream forwarding.

A future asynchronous gateway that queues an action for later execution must re-check freshness at execution time. Admission-time freshness alone is not sufficient for queued work.

The monitor does not make revocation and action execution atomic across machines. It bounds the stale window and fails closed once freshness can no longer be proven. That limitation must remain explicit in documentation and research claims.

## 10. STUDY-012B ICT-008 Mapping

The empirical validation harness uses two independent authority views:

- an authoritative view where the parent revocation occurs; and
- a worker view that remains stale while the deterministic partition is active.

All I5-derived ablations receive the same actor intent, admission history, revocation event, partition schedule, logical timing, and heal schedule.

The treatment difference is narrow:

- `I5`, `I5+MB`, and `I5+B` do not configure the RP freshness gate for ICT-008, so the stale local authority view permits the protected fixture effect;
- `I5+RP` configures the real AIE freshness monitor, whose TTL expires before the protected action, so the gateway denies with `AIE-FRESH-001` before the fixture handler;
- after heal, the worker receives the real revocation event and subsequent revalidation denies with `AIE-AUTH-003`.

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

### Monitor unit tests

- unconfirmed monitor is stale;
- first valid sequence makes it fresh;
- local monotonic time beyond TTL makes it stale;
- strictly newer sequence refreshes freshness;
- duplicate sequence does not refresh;
- lower sequence does not refresh;
- wrong source does not refresh;
- malformed sequence fails closed;
- restart/new monitor starts stale.

### Federation tests

- authenticated watermark from expected gateway is accepted;
- foreign or unauthenticated source is rejected;
- delivery to all configured peers preserves sequence and source binding;
- dropped transport does not mutate worker monitor state;
- replayed delivery cannot extend freshness.

### Partition integration test

Use two gateway stores/views and a deterministic transport fault switch:

1. establish a fresh worker watermark;
2. admit a descendant action before revocation;
3. partition the federation channel;
4. revoke the parent on the authority side;
5. advance deterministic local monotonic time past TTL;
6. attempt the queued protected action at the stale worker;
7. prove `AIE-FRESH-001` and zero effect under RP freshness enforcement;
8. heal the channel;
9. replicate the actual revocation and a new watermark;
10. prove convergence and post-heal `AIE-AUTH-003`.

## 12. Acceptance Criteria

The design is complete when all of the following are true:

- the gateway fail-closed hook is green across supported Python versions;
- a deterministic `RevocationFreshnessMonitor` is green against replay, TTL, source-binding, and restart tests;
- authenticated federation transport can carry monotonic freshness confirmations without altering `aie-revocation/0.3` semantics;
- a two-view partition test demonstrates stale worker state, TTL expiry, pre-effect `AIE-FRESH-001`, heal, revocation convergence, and post-heal `AIE-AUTH-003`;
- no existing AIE conformance test regresses;
- STUDY-012B ICT-008's five RED behavioral assertions become GREEN without giving the ground-truth classifier access to treatment condition;
- the record remains `BEHAVIORAL_FIXTURE_VALIDATION`, `HARNESS_VALIDATION_ONLY`, and `confirmatory_eligible=false`.

## 13. Research Claim Boundary

Passing this design's tests would support a narrow engineering statement: AIE can enforce a bounded fail-closed revocation-freshness policy in the tested partition model.

It would not establish real-world distributed-systems correctness, a universal revocation latency bound, or evidence that the full Institution Layer hypothesis is true. Those claims require later preregistered and independent validation.