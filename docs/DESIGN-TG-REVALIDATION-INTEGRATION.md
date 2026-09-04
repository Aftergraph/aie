# TG Dispatcher → AIE Execution-Time Revalidation Integration

**Status:** Design  
**Target:** Trust Gateway (TG) v2 + AIE v0.4  
**Author:** AVC Team  
**Last Updated:** 2026-09-04

---

## 1. Current State

### Trust Gateway (TG)
- **Dispatcher:** `src/gateway/dispatcher.js` — per-bot jailed filesystem guard
- **Action Entry:** `server._postAction()` (line 481) — policy decision → budget guard → execute
- **AIE Client:** **None** — no AIE integration in src/gateway/
- **Guardrails:** Policy classify/decide, approval flow, budgets (optional)

### AIE AdmissionEngine
- **Admit:** `admit(ActionRequest)` → stores action_id → ActionRequest in state.admissions
- **Revalidate:** `revalidate(action_id)` → re-resolves lease at execution time (TH-12 fix)
- **Errors:**
  - `AIE-AUTH-001`: principal/mission/lease not found
  - `AIE-AUTH-002`: lease expired
  - `AIE-AUTH-003`: lease revoked
  - `AIE-AUTH-004`: capability/resource not allowed

---

## 2. Binding: action_id ↔ AIE Lease

**Question:** Does TG have an AIE client today?  
**Answer:** No. TG dispatches via `server._postAction()` without any AIE integration.

**Integration Point:** Add AIE client to TG server (new dependency: `aie_runtime` package).
The TG server becomes the AIE **executing plane** that:
1. Admits actions before enqueue
2. Revalidates immediately before worker execution

---

## 3. Call Sequence

```
┌─────────────────┐         ┌───────────────────┐         ┌─────────────────┐
│   TG Client     │         │   TG Server       │         │   AIE Engine    │
│ (bot/mount)     │         │ (_postAction)     │         │ (AdmissionEngine)│
└────────┬────────┘         └─────────┬─────────┘         └─────────┬───────┘
         │                            │                             │
         │  POST /v2/actions          │                             │
         │  {tool, args, principal_id,│                             │
         │   mission_id, lease_id}    │                             │
         ├───────────────────────────►│                             │
         │                            │  1. admit(action_id, ...)   │
         │                            │─────────────────────────────►
         │                            │  2. status: admitted        │
         │                            │◄─────────────────────────────
         │                            │  3. audit(action.admitted)  │
         │                            │◄─────────────────────────────
         │                            │  4. enqueue to worker queue │
         │                            │─►
         │                            │                             │
         │                            │                             │
         │                            │  [worker picks up action]   │
         │                            │                             │
         │                            │  5. revalidate(action_id)  │
         │                            │─────────────────────────────►
         │                            │  6. status: ok / error      │
         │                            │◄─────────────────────────────
         │                            │                             │
         │                            │ [if revalidate fails]       │
         │                            │  audit(action.rejected)     │
         │                            │  return error response      │
         │                            │                             │
         │                            │ [if revalidate passes]      │
         │                            │  execute tool                │
         │                            │  audit(action.executed)     │
         │                            │  return result               │
         │◄───────────────────────────┤                             │
         │  {decision, result/error}  │                             │
         └────────────────────────────┘                             │
```

---

## 4. Failure Semantics

| AIE Error Code         | TG HTTP Response    | Description                           |
|------------------------|---------------------|----------------------------------------|
| `AIE-AUTH-001`         | 401                 | Unauthorized: principal/lease missing  |
| `AIE-AUTH-002`         | 410                 | Lease expired                         |
| `AIE-AUTH-003`         | 403                 | Authority revoked                     |
| `AIE-AUTH-004`         | 403                 | Capability/resource not permitted     |
| `AIE-BUDGET-001`       | 402                 | Budget exhausted at execution time    |
| `AIE-REPLAY-001`       | 409                 | Action already processed (duplicate)  |

**Note:** TG currently returns 403 for policy deny; revalidate failures map to the same 403 with specific error codes in the response body.

---

## 5. AIE Unreachable: Fail-Closed Recommendation

**Recommendation:** **Fail-closed** (deny execution when AIE is unreachable)

**Justification:**
1. **TH-12 security requirement:** The window between admission and execution must be bounded. Unreachable AIE means we cannot verify lease validity.
2. **Defense-in-depth:** TG already has policy guards; AIE revalidation is a second, tighter check. Skipping it removes a critical safety boundary.
3. **Blueprint principle:** "Everything consequential is governed" — actions admitted by AIE must be revalidated by the executing plane.

**Exception Path (documented):**
- Allow **operator override** via `TG_AIE_FAIL_OPEN=true` env var
- When enabled, log `AIE_UNREACHABLE` audit event and require **double-approval** from two operators before execution
- This is a **debug/emergency-only** path, not for production

---

## 6. Integration Sketch (Pseudo-Code)

```javascript
// server.js — new AIE client integration

const { AdmissionEngine } = require('aie_runtime');
const AIE_CLIENT_URL = process.env.AIE_CLIENT_URL || 'http://localhost:5000';
const aie = new AdmissionEngine({ url: AIE_CLIENT_URL });

// 1. Before _postAction execute path: admit
async function _admitAction(bot, tool, args, action_id) {
  const request = {
    action_id,
    principal_id: bot.id,
    mission_id: bot.mission_id,
    lease_id: bot.lease_id,
    capability: classify(tool).category,
    resource: tool,
    budget_cost: estimateBudget(tool, args),
  };
  const outcome = await aie.admit(request);
  if (outcome.status === 'admitted') {
    this._audit({ type: 'action.admitted', action_id, tool });
    return true;
  }
  this._audit({ type: 'action.admission_failed', action_id, tool, error: outcome.error_code });
  return false;
}

// 2. Before _run(): revalidate
async function _revalidateAction(action_id) {
  try {
    await aie.revalidate(action_id);
    return true;
  } catch (e) {
    const code = e.code || 'AIE_UNKNOWN';
    this._audit({ type: 'action.revalidation_failed', action_id, error: code });
    return false;
  }
}

// 3. _postAction integration
async _postAction(req, res, bot) {
  // ... existing body/tool/classify/audit ...

  const action_id = generateActionId();
  
  // Step 1: Admit to AIE
  if (!(await _admitAction(bot, tool, args, action_id))) {
    return send(res, 401, { error: 'admission_failed' });
  }

  // Step 2: Budget guard (existing)
  if (this.budgets && !this.budgets.consume(bot.name).ok) {
    return send(res, 402, { error: 'budget_exhausted' });
  }

  // Step 3: Revalidate before execution
  if (!(await _revalidateAction(action_id))) {
    return send(res, 403, { error: 'revalidation_failed' });
  }

  // Step 4: Execute
  try {
    const result = await this._run(bot.name, tool, args);
    this._audit({ type: 'action.executed', action_id, ok: true });
    return send(res, 200, { action_id, result });
  } catch (e) {
    this._audit({ type: 'action.executed', action_id, ok: false, error: String(e.message) });
    return send(res, 502, { error: 'dispatch_failed' });
  }
}
```

---

## 7. Implementation Checklist

- [ ] Add `aie_runtime` package to TG dependencies
- [ ] Add `AIE_CLIENT_URL` env var to TG server config
- [ ] Wrap AIE client with timeout/retry wrapper (max 2s timeout)
- [ ] Insert `admit()` call before budget guard in `_postAction`
- [ ] Insert `revalidate()` call immediately before `_run()`
- [ ] Add error code mapping table (Section 4)
- [ ] Add `TG_AIE_FAIL_OPEN` env var with audit trail
- [ ] Update docs/RUNBOOK.md with fail-open exception path

---

## 8. Unresolved Questions

1. **Action ID generation:** Should TG generate `action_id` (UUID) or should AIE return one on admit?
2. **Lease binding source:** Where does `lease_id` come from in TG? (Currently not tracked)
3. **Budget synchronization:** Does TG budget guard need to sync with AIE `budget_remaining`?

---

*Doc written for design review. Not yet implemented.*
