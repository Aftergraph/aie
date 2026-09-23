from __future__ import annotations

import hashlib
import hmac
import base64
import json
import re
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from signing_v23 import SigningProvider, build_signing_provider


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


_SENSITIVE_ARGUMENT_KEY = re.compile(r"(?:pass(?:word)?|secret|token|credential|authorization|cookie|private[_-]?key|api[_-]?key)", re.I)


def approval_argument_preview(value: Any, *, key: str | None = None, depth: int = 0) -> Any:
    """Return a bounded human-review preview without leaking secret-like argument values.

    The preview is intentionally not the canonical effect arguments. Exact binding remains
    represented by argumentsHash/effectHash, which are recomputed server-side before execution.
    """
    if key and _SENSITIVE_ARGUMENT_KEY.search(key):
        return "[REDACTED]"
    if depth >= 6:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for index, (child_key, child_value) in enumerate(value.items()):
            if index >= 40:
                out["…"] = "[TRUNCATED]"
                break
            out[str(child_key)] = approval_argument_preview(child_value, key=str(child_key), depth=depth + 1)
        return out
    if isinstance(value, list):
        items = [approval_argument_preview(v, depth=depth + 1) for v in value[:20]]
        if len(value) > 20:
            items.append("[TRUNCATED]")
        return items
    if isinstance(value, str) and len(value) > 2000:
        return value[:2000] + "…[TRUNCATED]"
    return value


class ProductionTrustPlane:
    """v23 Production Trust Plane.

    M2 keeps the exact-effect M1 laws and upgrades execution receipts to the
    SigningProvider/v1 boundary. Local Ed25519 is publicly verifiable, while
    managed KMS/HSM, provider-native ephemeral credentials, Firecracker/KVM and
    hardware attestation remain explicitly separate readiness boundaries.
    """

    contract = "ProductionTrustPlane/v1"
    effect_contract = "EffectIntent/v1"
    approval_contract = "ExactEffectApproval/v1"
    credential_contract = "CredentialGrant/v1"
    receipt_contract = "ExecutionReceipt/v1"
    recovery_contract = "ExecutionRecovery/v1"

    def __init__(self, db_path: str | Path, shared_workspace, workspace_runtime, receipt_key: bytes, signing_provider: SigningProvider | None = None, environment: str = "development"):
        self.db_path = Path(db_path)
        self.shared = shared_workspace
        self.workspace = workspace_runtime
        self.receipt_key = receipt_key
        self.signing = signing_provider or build_signing_provider(environment, receipt_key)
        self._lock = threading.RLock()

    def _db(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def init(self) -> None:
        with self._lock, self._db() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS effect_intents_v23(
                  id TEXT PRIMARY KEY,
                  workspace_id TEXT NOT NULL,
                  mission_id TEXT,
                  mission_generation INTEGER,
                  principal_id TEXT NOT NULL,
                  actor_type TEXT NOT NULL,
                  actor_id TEXT NOT NULL,
                  bot_id TEXT,
                  capability TEXT NOT NULL,
                  target TEXT NOT NULL,
                  args_json TEXT NOT NULL,
                  args_hash TEXT NOT NULL,
                  input_hashes_json TEXT NOT NULL,
                  authority_ref TEXT NOT NULL,
                  policy_ref TEXT NOT NULL,
                  risk_class TEXT NOT NULL,
                  idempotency_key TEXT NOT NULL,
                  effect_hash TEXT NOT NULL,
                  state TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  expires_at REAL NOT NULL,
                  UNIQUE(principal_id,workspace_id,idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_effect_intents_v23_principal
                  ON effect_intents_v23(principal_id,workspace_id,created_at DESC);

                CREATE TABLE IF NOT EXISTS exact_approvals_v23(
                  id TEXT PRIMARY KEY,
                  principal_id TEXT NOT NULL,
                  effect_intent_id TEXT NOT NULL,
                  effect_hash TEXT NOT NULL,
                  authority_ref TEXT NOT NULL,
                  policy_ref TEXT NOT NULL,
                  nonce_hash TEXT NOT NULL,
                  status TEXT NOT NULL,
                  decision TEXT,
                  created_at TEXT NOT NULL,
                  expires_at REAL NOT NULL,
                  resolved_at TEXT,
                  consumed_at TEXT,
                  FOREIGN KEY(effect_intent_id) REFERENCES effect_intents_v23(id)
                );
                CREATE INDEX IF NOT EXISTS idx_exact_approvals_v23_principal
                  ON exact_approvals_v23(principal_id,status,created_at DESC);

                CREATE TABLE IF NOT EXISTS credential_grants_v23(
                  id TEXT PRIMARY KEY,
                  principal_id TEXT NOT NULL,
                  workspace_id TEXT NOT NULL,
                  mission_id TEXT,
                  effect_intent_id TEXT NOT NULL,
                  capability TEXT NOT NULL,
                  destination TEXT NOT NULL,
                  provider TEXT,
                  scopes_json TEXT NOT NULL,
                  runtime_identity TEXT NOT NULL,
                  secret_ref TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  expires_at REAL NOT NULL,
                  revoked_at TEXT,
                  FOREIGN KEY(effect_intent_id) REFERENCES effect_intents_v23(id)
                );
                CREATE INDEX IF NOT EXISTS idx_credential_grants_v23_effect
                  ON credential_grants_v23(effect_intent_id,status,expires_at);

                CREATE TABLE IF NOT EXISTS execution_receipts_v23(
                  id TEXT PRIMARY KEY,
                  principal_id TEXT NOT NULL,
                  workspace_id TEXT NOT NULL,
                  mission_id TEXT,
                  actor_id TEXT NOT NULL,
                  effect_intent_id TEXT NOT NULL,
                  approval_id TEXT,
                  credential_grant_id TEXT,
                  capability TEXT NOT NULL,
                  target TEXT NOT NULL,
                  input_hash TEXT NOT NULL,
                  output_hash TEXT,
                  effect_state TEXT NOT NULL,
                  observed_json TEXT,
                  signing_mode TEXT NOT NULL,
                  signature TEXT,
                  started_at TEXT NOT NULL,
                  completed_at TEXT,
                  FOREIGN KEY(effect_intent_id) REFERENCES effect_intents_v23(id)
                );
                CREATE INDEX IF NOT EXISTS idx_execution_receipts_v23_effect
                  ON execution_receipts_v23(effect_intent_id,started_at DESC);

                CREATE TABLE IF NOT EXISTS execution_recoveries_v23(
                  id TEXT PRIMARY KEY,
                  principal_id TEXT NOT NULL,
                  workspace_id TEXT NOT NULL,
                  effect_intent_id TEXT NOT NULL,
                  receipt_id TEXT NOT NULL UNIQUE,
                  semantic_key TEXT NOT NULL,
                  previous_effect_state TEXT NOT NULL,
                  resolution TEXT NOT NULL,
                  observed_json TEXT NOT NULL,
                  observed_hash TEXT NOT NULL,
                  signing_mode TEXT NOT NULL,
                  signature TEXT,
                  signing_key_id TEXT,
                  signing_key_version TEXT,
                  public_key TEXT,
                  signature_algorithm TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(effect_intent_id) REFERENCES effect_intents_v23(id),
                  FOREIGN KEY(receipt_id) REFERENCES execution_receipts_v23(id)
                );
                CREATE INDEX IF NOT EXISTS idx_execution_recoveries_v23_principal
                  ON execution_recoveries_v23(principal_id,workspace_id,created_at DESC);
                """
            )
            intent_cols = {r[1] for r in c.execute("PRAGMA table_info(effect_intents_v23)").fetchall()}
            if "execution_mode" not in intent_cols:
                c.execute("ALTER TABLE effect_intents_v23 ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'control-plane'")
            cols = {r[1] for r in c.execute("PRAGMA table_info(execution_receipts_v23)").fetchall()}
            for name, ddl in [
                ("signing_key_id", "ALTER TABLE execution_receipts_v23 ADD COLUMN signing_key_id TEXT"),
                ("signing_key_version", "ALTER TABLE execution_receipts_v23 ADD COLUMN signing_key_version TEXT"),
                ("public_key", "ALTER TABLE execution_receipts_v23 ADD COLUMN public_key TEXT"),
                ("signature_algorithm", "ALTER TABLE execution_receipts_v23 ADD COLUMN signature_algorithm TEXT"),
            ]:
                if name not in cols:
                    c.execute(ddl)
            c.commit()

    def _authority_snapshot(self, principal_id: str, workspace_id: str) -> dict[str, Any]:
        role = self.shared.role(principal_id, workspace_id)
        allowed = self.shared.allowed(principal_id, "effects.execute", workspace_id)
        if not allowed:
            raise PermissionError("workspace_permission_required:effects.execute")
        snapshot = {
            "workspaceId": workspace_id,
            "principalId": principal_id,
            "role": role,
            "permission": "effects.execute",
            "allowed": True,
        }
        return {"ref": "authz_" + sha256_json(snapshot), "snapshot": snapshot}

    def _policy_snapshot(self, principal_id: str, workspace_id: str) -> dict[str, Any]:
        policy = self.workspace.policy(principal_id, workspace_id)
        return {"ref": "policy_" + sha256_json(policy), "policy": policy}

    def _mission_snapshot(self, principal_id: str, mission_id: str | None) -> tuple[str | None, int | None]:
        if not mission_id:
            return None, None
        mission = self.shared.mission(principal_id, mission_id)
        return mission["id"], int(mission["generation"])

    def _semantic_intent(self, *, workspace_id: str, mission_id: str | None, mission_generation: int | None,
                         principal_id: str, actor_type: str, actor_id: str, bot_id: str | None,
                         capability: str, target: str, args_hash: str, input_hashes: list[str],
                         authority_ref: str, policy_ref: str, risk_class: str, idempotency_key: str,
                         execution_mode: str) -> dict[str, Any]:
        return {
            "contract": self.effect_contract,
            "workspaceId": workspace_id,
            "missionId": mission_id,
            "missionGeneration": mission_generation,
            "principalId": principal_id,
            "actorType": actor_type,
            "actorId": actor_id,
            "botId": bot_id,
            "capability": capability,
            "target": target,
            "argumentsHash": args_hash,
            "inputHashes": sorted(input_hashes),
            "authorityRef": authority_ref,
            "policyRef": policy_ref,
            "riskClass": risk_class,
            "idempotencyKey": idempotency_key,
            "executionMode": execution_mode,
        }

    def _effect_semantic_key(self, *, principal_id: str, workspace_id: str, execution_mode: str,
                             capability: str, target: str, args_hash: str) -> str:
        """Stable duplicate-risk key that deliberately excludes the idempotency key.

        This key is not the canonical EffectIntent hash. It exists only to fence a new
        semantically-identical external effect while a prior attempt remains ATTEMPTED
        or UNKNOWN after a crash/ambiguous provider outcome.
        """
        return sha256_json({
            "principalId": principal_id,
            "workspaceId": workspace_id,
            "executionMode": execution_mode,
            "capability": capability,
            "target": target,
            "argumentsHash": args_hash,
        })

    def _unresolved_semantic_receipt(self, c: sqlite3.Connection, *, principal_id: str,
                                     workspace_id: str, execution_mode: str, capability: str,
                                     target: str, args_hash: str) -> sqlite3.Row | None:
        return c.execute(
            """
            SELECT r.*, i.execution_mode, i.args_hash
              FROM execution_receipts_v23 r
              JOIN effect_intents_v23 i ON i.id=r.effect_intent_id
         LEFT JOIN execution_recoveries_v23 x ON x.receipt_id=r.id
             WHERE r.principal_id=? AND r.workspace_id=?
               AND i.execution_mode=? AND r.capability=? AND r.target=? AND i.args_hash=?
               AND r.effect_state IN ('ATTEMPTED','UNKNOWN')
               AND x.id IS NULL
          ORDER BY r.started_at DESC
             LIMIT 1
            """,
            (principal_id, workspace_id, execution_mode, capability, target, args_hash),
        ).fetchone()

    def _latest_semantic_recovery(self, c: sqlite3.Connection, *, principal_id: str, workspace_id: str,
                                  execution_mode: str, capability: str, target: str, args_hash: str) -> sqlite3.Row | None:
        return c.execute(
            """
            SELECT x.*
              FROM execution_recoveries_v23 x
              JOIN execution_receipts_v23 r ON r.id=x.receipt_id
              JOIN effect_intents_v23 i ON i.id=r.effect_intent_id
             WHERE x.principal_id=? AND x.workspace_id=?
               AND i.execution_mode=? AND r.capability=? AND r.target=? AND i.args_hash=?
          ORDER BY x.created_at DESC
             LIMIT 1
            """,
            (principal_id, workspace_id, execution_mode, capability, target, args_hash),
        ).fetchone()

    def _assert_semantic_execution_safe(self, c: sqlite3.Connection, intent: dict[str, Any], *,
                                        approval_consumed_at: str | None) -> None:
        """Recheck duplicate-risk state at the last authority/execution boundaries.

        Intent creation is not sufficient because two semantically identical intents may
        be created before either begins. A later ATTEMPTED/UNKNOWN receipt must fence the
        other intent, and any approval consumed before a recovery decision is stale after
        reconciliation.
        """
        unresolved = self._unresolved_semantic_receipt(
            c,
            principal_id=intent["principalId"],
            workspace_id=intent["workspaceId"],
            execution_mode=intent.get("executionMode") or "control-plane",
            capability=intent["capability"],
            target=intent["target"],
            args_hash=intent["argumentsHash"],
        )
        if unresolved and unresolved["effect_intent_id"] != intent["id"]:
            raise ValueError("effect_uncertain_recovery_required")
        latest_recovery = self._latest_semantic_recovery(
            c,
            principal_id=intent["principalId"],
            workspace_id=intent["workspaceId"],
            execution_mode=intent.get("executionMode") or "control-plane",
            capability=intent["capability"],
            target=intent["target"],
            args_hash=intent["argumentsHash"],
        )
        if latest_recovery and (not approval_consumed_at or str(approval_consumed_at) <= str(latest_recovery["created_at"])):
            raise ValueError("effect_reauthorization_required_after_recovery")

    def create_effect_intent(self, principal_id: str, *, capability: str, target: str, arguments: dict[str, Any] | None,
                             actor_type: str = "bot", actor_id: str = "chief", bot_id: str | None = None,
                             mission_id: str | None = None, input_hashes: list[str] | None = None,
                             risk_class: str = "consequential", idempotency_key: str | None = None,
                             ttl_seconds: int = 900, execution_mode: str = "control-plane") -> dict[str, Any]:
        capability = str(capability or "").strip()
        target = str(target or "").strip()
        if not capability or not target:
            raise ValueError("effect_capability_target_required")
        if actor_type not in {"human", "bot", "service"}:
            raise ValueError("effect_actor_type_invalid")
        execution_mode = str(execution_mode or "control-plane").strip().lower()
        if execution_mode not in {"control-plane", "habitat"}:
            raise ValueError("effect_execution_mode_invalid")
        workspace_id = self.shared.active_workspace_id(principal_id)
        authority = self._authority_snapshot(principal_id, workspace_id)
        policy = self._policy_snapshot(principal_id, workspace_id)
        mission_id, mission_generation = self._mission_snapshot(principal_id, mission_id)
        args = arguments or {}
        args_json = canonical_json(args)
        args_hash = hashlib.sha256(args_json.encode("utf-8")).hexdigest()
        input_hashes = sorted(str(x) for x in (input_hashes or []))
        idem = str(idempotency_key or ("eff:" + hashlib.sha256((principal_id + "|" + execution_mode + "|" + capability + "|" + target + "|" + args_hash).encode()).hexdigest()[:32]))
        semantic = self._semantic_intent(
            workspace_id=workspace_id, mission_id=mission_id, mission_generation=mission_generation,
            principal_id=principal_id, actor_type=actor_type, actor_id=actor_id, bot_id=bot_id,
            capability=capability, target=target, args_hash=args_hash, input_hashes=input_hashes,
            authority_ref=authority["ref"], policy_ref=policy["ref"], risk_class=risk_class,
            idempotency_key=idem, execution_mode=execution_mode,
        )
        effect_hash = sha256_json(semantic)
        now = time.time(); created = now_iso(); expires = now + max(30, min(int(ttl_seconds), 3600))
        with self._lock, self._db() as c:
            existing = c.execute(
                "SELECT * FROM effect_intents_v23 WHERE principal_id=? AND workspace_id=? AND idempotency_key=?",
                (principal_id, workspace_id, idem),
            ).fetchone()
            if existing:
                if existing["effect_hash"] != effect_hash:
                    raise ValueError("effect_idempotency_conflict")
                return self._intent_map(existing)
            unresolved = self._unresolved_semantic_receipt(
                c,
                principal_id=principal_id,
                workspace_id=workspace_id,
                execution_mode=execution_mode,
                capability=capability,
                target=target,
                args_hash=args_hash,
            )
            if unresolved:
                raise ValueError("effect_uncertain_recovery_required")
            eid = "eff_" + uuid.uuid4().hex[:20]
            c.execute(
                """INSERT INTO effect_intents_v23(
                     id,workspace_id,mission_id,mission_generation,principal_id,actor_type,actor_id,bot_id,
                     capability,target,args_json,args_hash,input_hashes_json,authority_ref,policy_ref,risk_class,
                     idempotency_key,effect_hash,state,created_at,expires_at,execution_mode
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (eid, workspace_id, mission_id, mission_generation, principal_id, actor_type, actor_id, bot_id,
                 capability, target, args_json, args_hash, canonical_json(input_hashes), authority["ref"],
                 policy["ref"], risk_class, idem, effect_hash, "PROPOSED", created, expires, execution_mode),
            )
            c.commit()
            row = c.execute("SELECT * FROM effect_intents_v23 WHERE id=?", (eid,)).fetchone()
        return self._intent_map(row)

    def _intent_map(self, r: sqlite3.Row) -> dict[str, Any]:
        return {
            "contract": self.effect_contract,
            "id": r["id"], "workspaceId": r["workspace_id"], "missionId": r["mission_id"],
            "missionGeneration": r["mission_generation"], "principalId": r["principal_id"],
            "actorType": r["actor_type"], "actorId": r["actor_id"], "botId": r["bot_id"],
            "capability": r["capability"], "target": r["target"], "arguments": json.loads(r["args_json"]),
            "argumentsHash": r["args_hash"], "inputHashes": json.loads(r["input_hashes_json"]),
            "authorityRef": r["authority_ref"], "policyRef": r["policy_ref"], "riskClass": r["risk_class"],
            "idempotencyKey": r["idempotency_key"], "effectHash": r["effect_hash"], "state": r["state"],
            "executionMode": r["execution_mode"] if "execution_mode" in r.keys() else "control-plane",
            "createdAt": r["created_at"], "expiresAt": float(r["expires_at"]),
        }

    def effect_intent(self, principal_id: str, effect_intent_id: str) -> dict[str, Any]:
        with self._db() as c:
            r = c.execute("SELECT * FROM effect_intents_v23 WHERE id=? AND principal_id=?", (effect_intent_id, principal_id)).fetchone()
        if not r:
            raise ValueError("effect_intent_not_found")
        return self._intent_map(r)

    def intents(self, principal_id: str, limit: int = 100) -> list[dict[str, Any]]:
        workspace_id = self.shared.active_workspace_id(principal_id)
        with self._db() as c:
            rows = c.execute(
                "SELECT * FROM effect_intents_v23 WHERE principal_id=? AND workspace_id=? ORDER BY created_at DESC LIMIT ?",
                (principal_id, workspace_id, max(1, min(int(limit), 200))),
            ).fetchall()
        return [self._intent_map(r) for r in rows]

    def request_approval(self, principal_id: str, effect_intent_id: str, ttl_seconds: int = 600) -> dict[str, Any]:
        intent = self.effect_intent(principal_id, effect_intent_id)
        if time.time() >= intent["expiresAt"]:
            raise ValueError("effect_intent_expired")
        # Once execution authorization has been consumed or an effect has reached a terminal/attempt state,
        # the same EffectIntent can never be re-approved. A deliberate retry must be a new intent with
        # a new idempotency key so it cannot silently duplicate an uncertain real-world effect.
        if intent["state"] not in {"PROPOSED", "AWAITING_APPROVAL", "APPROVED"}:
            raise ValueError("effect_intent_not_approvable")
        now = time.time(); created = now_iso(); expires = min(intent["expiresAt"], now + max(30, min(int(ttl_seconds), 1800)))
        with self._lock, self._db() as c:
            existing = c.execute(
                "SELECT * FROM exact_approvals_v23 WHERE principal_id=? AND effect_intent_id=? AND status IN ('PENDING','APPROVED') ORDER BY created_at DESC LIMIT 1",
                (principal_id, effect_intent_id),
            ).fetchone()
            if existing:
                if float(existing["expires_at"]) > now:
                    return self._approval_map(existing, intent)
                c.execute("UPDATE exact_approvals_v23 SET status='EXPIRED',resolved_at=? WHERE id=?", (created, existing["id"]))
            aid = "xapr_" + uuid.uuid4().hex[:20]
            nonce_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
            c.execute(
                "INSERT INTO exact_approvals_v23 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid, principal_id, effect_intent_id, intent["effectHash"], intent["authorityRef"], intent["policyRef"],
                 nonce_hash, "PENDING", None, created, expires, None, None),
            )
            c.execute("UPDATE effect_intents_v23 SET state='AWAITING_APPROVAL' WHERE id=?", (effect_intent_id,))
            c.commit()
            row = c.execute("SELECT * FROM exact_approvals_v23 WHERE id=?", (aid,)).fetchone()
        return self._approval_map(row, intent)

    def _approval_map(self, r: sqlite3.Row, intent: dict[str, Any] | None = None) -> dict[str, Any]:
        if intent is None:
            intent = self.effect_intent(r["principal_id"], r["effect_intent_id"])
        mission_summary = None
        if intent.get("missionId"):
            try:
                mission = self.shared.mission(r["principal_id"], intent["missionId"])
                mission_summary = {
                    "id": mission.get("id"),
                    "title": mission.get("title"),
                    "objective": mission.get("objective"),
                    "state": mission.get("state"),
                    "generation": mission.get("generation"),
                }
            except (ValueError, PermissionError):
                mission_summary = {
                    "id": intent.get("missionId"),
                    "generation": intent.get("missionGeneration"),
                }
        arguments = intent.get("arguments") or {}
        return {
            "contract": self.approval_contract,
            "id": r["id"], "approvalId": r["id"], "principalId": r["principal_id"],
            "effectIntentId": r["effect_intent_id"], "effectHash": r["effect_hash"],
            "authorityRef": r["authority_ref"], "policyRef": r["policy_ref"],
            "status": r["status"], "decision": r["decision"], "createdAt": r["created_at"],
            "expiresAt": float(r["expires_at"]), "resolvedAt": r["resolved_at"], "consumedAt": r["consumed_at"],
            "workspaceId": intent.get("workspaceId"), "missionId": intent.get("missionId"),
            "missionGeneration": intent.get("missionGeneration"), "mission": mission_summary,
            "actorType": intent.get("actorType"), "actorId": intent.get("actorId"),
            "bot_id": intent.get("botId"), "botId": intent.get("botId"),
            "action": intent["capability"], "capability": intent["capability"], "target": intent["target"],
            "summary": arguments.get("summary") or f"Execute {intent['capability']} on {intent['target']}",
            "argumentPreview": approval_argument_preview(arguments),
            "argumentsHash": intent.get("argumentsHash"), "inputHashes": intent.get("inputHashes") or [],
            "riskClass": intent.get("riskClass"), "executionMode": intent.get("executionMode"),
            "effectState": intent.get("state"),
            "reversibility": None, "reversibilitySource": "not_declared_by_EffectIntent/v1",
            "exact": True,
        }

    def approval(self, principal_id: str, approval_id: str) -> dict[str, Any]:
        with self._db() as c:
            row = c.execute(
                "SELECT * FROM exact_approvals_v23 WHERE id=? AND principal_id=?",
                (approval_id, principal_id),
            ).fetchone()
        if not row:
            raise ValueError("exact_approval_not_found")
        return self._approval_map(row)

    def pending_approvals(self, principal_id: str) -> list[dict[str, Any]]:
        with self._db() as c:
            rows = c.execute(
                "SELECT * FROM exact_approvals_v23 WHERE principal_id=? AND status='PENDING' ORDER BY created_at DESC",
                (principal_id,),
            ).fetchall()
        return [self._approval_map(r) for r in rows if float(r["expires_at"]) > time.time()]

    def _validate_current_bindings(self, principal_id: str, intent: dict[str, Any]) -> None:
        if time.time() >= intent["expiresAt"]:
            raise ValueError("effect_intent_expired")
        authority = self._authority_snapshot(principal_id, intent["workspaceId"])
        if authority["ref"] != intent["authorityRef"]:
            raise PermissionError("effect_authority_changed")
        policy = self._policy_snapshot(principal_id, intent["workspaceId"])
        if policy["ref"] != intent["policyRef"]:
            raise PermissionError("effect_policy_changed")
        if intent.get("missionId"):
            mission = self.shared.mission(principal_id, intent["missionId"])
            if int(mission["generation"]) != int(intent.get("missionGeneration") or 0):
                raise PermissionError("effect_mission_generation_changed")

    def _invalidate_approval(self, principal_id: str, approval_id: str, effect_intent_id: str, reason: str) -> None:
        with self._lock, self._db() as c:
            c.execute("UPDATE exact_approvals_v23 SET status='INVALIDATED',resolved_at=? WHERE id=? AND principal_id=? AND status IN ('PENDING','APPROVED')", (now_iso(), approval_id, principal_id))
            c.execute("UPDATE effect_intents_v23 SET state='INVALIDATED' WHERE id=? AND principal_id=?", (effect_intent_id, principal_id))
            c.commit()

    def resolve_approval(self, principal_id: str, approval_id: str, choice: str) -> dict[str, Any]:
        if choice not in {"allow", "deny"}:
            raise ValueError("exact_approval_choice_invalid")
        with self._lock, self._db() as c:
            r = c.execute("SELECT * FROM exact_approvals_v23 WHERE id=? AND principal_id=?", (approval_id, principal_id)).fetchone()
            if not r:
                raise ValueError("exact_approval_not_found")
            if r["status"] != "PENDING":
                raise ValueError("exact_approval_already_resolved")
            if time.time() >= float(r["expires_at"]):
                c.execute("UPDATE exact_approvals_v23 SET status='EXPIRED',resolved_at=? WHERE id=?", (now_iso(), approval_id)); c.commit()
                raise ValueError("exact_approval_expired")
            intent = self.effect_intent(principal_id, r["effect_intent_id"])
            if r["effect_hash"] != intent["effectHash"]:
                self._invalidate_approval(principal_id, approval_id, intent["id"], "effect_hash_mismatch")
                raise PermissionError("exact_approval_effect_hash_mismatch")
            try:
                self._validate_current_bindings(principal_id, intent)
            except PermissionError:
                self._invalidate_approval(principal_id, approval_id, intent["id"], "binding_changed")
                raise
            if choice == "deny":
                c.execute("UPDATE exact_approvals_v23 SET status='DENIED',decision='deny',resolved_at=? WHERE id=?", (now_iso(), approval_id))
                c.execute("UPDATE effect_intents_v23 SET state='DENIED' WHERE id=?", (intent["id"],))
                c.commit()
                row = c.execute("SELECT * FROM exact_approvals_v23 WHERE id=?", (approval_id,)).fetchone()
                return self._approval_map(row, intent)
            c.execute("UPDATE exact_approvals_v23 SET status='APPROVED',decision='allow',resolved_at=? WHERE id=?", (now_iso(), approval_id))
            c.execute("UPDATE effect_intents_v23 SET state='APPROVED' WHERE id=?", (intent["id"],))
            c.commit()
            row = c.execute("SELECT * FROM exact_approvals_v23 WHERE id=?", (approval_id,)).fetchone()
        return self._approval_map(row, intent)

    def consume_approval(self, principal_id: str, approval_id: str, *, capability: str, target: str,
                         arguments: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        args_hash = hashlib.sha256(canonical_json(arguments or {}).encode("utf-8")).hexdigest()
        with self._lock, self._db() as c:
            r = c.execute("SELECT * FROM exact_approvals_v23 WHERE id=? AND principal_id=?", (approval_id, principal_id)).fetchone()
            if not r:
                raise ValueError("exact_approval_not_found")
            if r["status"] != "APPROVED" or r["consumed_at"]:
                raise ValueError("exact_approval_not_consumable")
            if time.time() >= float(r["expires_at"]):
                raise ValueError("exact_approval_expired")
            intent_row = c.execute("SELECT * FROM effect_intents_v23 WHERE id=? AND principal_id=?", (r["effect_intent_id"], principal_id)).fetchone()
            if not intent_row:
                raise ValueError("effect_intent_not_found")
            intent = self._intent_map(intent_row)
            if capability != intent["capability"] or target != intent["target"] or args_hash != intent["argumentsHash"]:
                raise PermissionError("exact_approval_request_mismatch")
            if r["effect_hash"] != intent["effectHash"]:
                self._invalidate_approval(principal_id, approval_id, intent["id"], "effect_hash_mismatch")
                raise PermissionError("exact_approval_effect_hash_mismatch")
            try:
                self._validate_current_bindings(principal_id, intent)
            except PermissionError:
                self._invalidate_approval(principal_id, approval_id, intent["id"], "binding_changed")
                raise
            consumed = now_iso()
            cur=c.execute("UPDATE exact_approvals_v23 SET status='CONSUMED',consumed_at=? WHERE id=? AND status='APPROVED' AND consumed_at IS NULL", (consumed, approval_id))
            if cur.rowcount != 1:
                raise ValueError("exact_approval_replay")
            c.execute("UPDATE effect_intents_v23 SET state='AUTHORIZED' WHERE id=?", (intent["id"],))
            c.commit()
            row = c.execute("SELECT * FROM exact_approvals_v23 WHERE id=?", (approval_id,)).fetchone()
        intent = dict(intent)
        intent["state"] = "AUTHORIZED"
        return intent, self._approval_map(row, intent)

    def issue_credential_grant(self, principal_id: str, intent: dict[str, Any], *, provider: str | None,
                               scopes: list[str] | None, secret_ref: str, runtime_identity: str = "control-plane",
                               ttl_seconds: int = 120) -> dict[str, Any]:
        # Domain-layer guard: callers cannot mint a credential grant merely because they
        # possess an EffectIntent object. Exact approval consumption is the only path that
        # moves an intent into AUTHORIZED.
        current = self.effect_intent(principal_id, intent["id"])
        if current["effectHash"] != intent["effectHash"] or current["state"] != "AUTHORIZED":
            raise PermissionError("effect_intent_not_authorized")
        self._validate_current_bindings(principal_id, current)
        intent = current
        now = time.time(); created = now_iso(); expires = min(intent["expiresAt"], now + max(15, min(int(ttl_seconds), 600)))
        gid = "cgrant_" + uuid.uuid4().hex[:20]
        with self._lock, self._db() as c:
            approval = c.execute(
                "SELECT consumed_at FROM exact_approvals_v23 WHERE principal_id=? AND effect_intent_id=? AND status='CONSUMED' ORDER BY consumed_at DESC LIMIT 1",
                (principal_id, current["id"]),
            ).fetchone()
            if not approval or not approval["consumed_at"]:
                raise PermissionError("execution_approval_not_consumed")
            self._assert_semantic_execution_safe(c, current, approval_consumed_at=approval["consumed_at"])
            c.execute(
                "INSERT INTO credential_grants_v23 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (gid, principal_id, intent["workspaceId"], intent.get("missionId"), intent["id"], intent["capability"],
                 intent["target"], provider, canonical_json(sorted(scopes or [])), runtime_identity, secret_ref,
                 "ACTIVE", created, expires, None),
            )
            c.commit()
            row = c.execute("SELECT * FROM credential_grants_v23 WHERE id=?", (gid,)).fetchone()
        return self._credential_map(row)

    def _credential_map(self, r: sqlite3.Row) -> dict[str, Any]:
        return {
            "contract": self.credential_contract,
            "id": r["id"], "principalId": r["principal_id"], "workspaceId": r["workspace_id"],
            "missionId": r["mission_id"], "effectIntentId": r["effect_intent_id"], "capability": r["capability"],
            "destination": r["destination"], "provider": r["provider"], "scopes": json.loads(r["scopes_json"]),
            "runtimeIdentity": r["runtime_identity"], "secretRef": r["secret_ref"], "status": r["status"],
            "createdAt": r["created_at"], "expiresAt": float(r["expires_at"]), "revokedAt": r["revoked_at"],
            "providerNativeEphemeral": False,
        }

    def validate_credential_grant(self, principal_id: str, grant_id: str, *, effect_intent_id: str,
                                  capability: str, destination: str, provider: str | None,
                                  runtime_identity: str | None = None) -> dict[str, Any]:
        with self._db() as c:
            r = c.execute("SELECT * FROM credential_grants_v23 WHERE id=? AND principal_id=?", (grant_id, principal_id)).fetchone()
        if not r:
            raise ValueError("credential_grant_not_found")
        grant = self._credential_map(r)
        if grant["status"] != "ACTIVE" or time.time() >= grant["expiresAt"]:
            raise PermissionError("credential_grant_expired_or_revoked")
        if grant["effectIntentId"] != effect_intent_id or grant["capability"] != capability or grant["destination"] != destination or grant["provider"] != provider:
            raise PermissionError("credential_grant_scope_mismatch")
        if runtime_identity is not None and grant["runtimeIdentity"] != runtime_identity:
            raise PermissionError("credential_grant_runtime_mismatch")
        return grant

    def revoke_credential_grant(self, principal_id: str, grant_id: str, *, reason: str = "revoked") -> dict[str, Any]:
        with self._lock, self._db() as c:
            r = c.execute("SELECT * FROM credential_grants_v23 WHERE id=? AND principal_id=?", (grant_id, principal_id)).fetchone()
            if not r:
                raise ValueError("credential_grant_not_found")
            if r["status"] == "REVOKED":
                return self._credential_map(r)
            c.execute("UPDATE credential_grants_v23 SET status='REVOKED',revoked_at=? WHERE id=?", (now_iso(), grant_id))
            c.commit()
            row = c.execute("SELECT * FROM credential_grants_v23 WHERE id=?", (grant_id,)).fetchone()
        out = self._credential_map(row)
        out["revocationReason"] = reason
        return out

    def revoke_runtime_grants(self, runtime_identity: str, *, reason: str = "runtime_revoked") -> int:
        with self._lock, self._db() as c:
            rows = c.execute("SELECT id FROM credential_grants_v23 WHERE runtime_identity=? AND status='ACTIVE'", (runtime_identity,)).fetchall()
            if rows:
                c.execute("UPDATE credential_grants_v23 SET status='REVOKED',revoked_at=? WHERE runtime_identity=? AND status='ACTIVE'", (now_iso(), runtime_identity))
                c.commit()
        return len(rows)

    def begin_execution(self, principal_id: str, intent: dict[str, Any], *, approval_id: str | None,
                        credential_grant_id: str | None) -> dict[str, Any]:
        # Enforce the trust chain again at the domain boundary instead of relying on
        # server.py call ordering. An internal caller cannot skip approval consumption
        # or use a grant belonging to another effect.
        current = self.effect_intent(principal_id, intent["id"])
        if current["effectHash"] != intent["effectHash"] or current["state"] != "AUTHORIZED":
            raise PermissionError("effect_intent_not_authorized")
        self._validate_current_bindings(principal_id, current)
        if not approval_id or not credential_grant_id:
            raise PermissionError("execution_trust_chain_incomplete")
        with self._db() as c:
            approval = c.execute(
                "SELECT * FROM exact_approvals_v23 WHERE id=? AND principal_id=? AND effect_intent_id=?",
                (approval_id, principal_id, current["id"]),
            ).fetchone()
            if not approval or approval["status"] != "CONSUMED" or not approval["consumed_at"]:
                raise PermissionError("execution_approval_not_consumed")
            grant_row = c.execute(
                "SELECT * FROM credential_grants_v23 WHERE id=? AND principal_id=? AND effect_intent_id=?",
                (credential_grant_id, principal_id, current["id"]),
            ).fetchone()
            if not grant_row:
                raise PermissionError("execution_credential_grant_missing")
            grant = self._credential_map(grant_row)
            if grant["status"] != "ACTIVE" or time.time() >= grant["expiresAt"]:
                raise PermissionError("credential_grant_expired_or_revoked")
            if grant["capability"] != current["capability"] or grant["destination"] != current["target"]:
                raise PermissionError("credential_grant_scope_mismatch")
            self._assert_semantic_execution_safe(c, current, approval_consumed_at=approval["consumed_at"])
            existing = c.execute(
                "SELECT id FROM execution_receipts_v23 WHERE principal_id=? AND effect_intent_id=? LIMIT 1",
                (principal_id, current["id"]),
            ).fetchone()
            if existing:
                raise ValueError("effect_execution_already_started")
        intent = current
        rid = "ercpt_" + uuid.uuid4().hex[:20]
        started = now_iso()
        input_hash = intent["argumentsHash"]
        with self._lock, self._db() as c:
            signing_status = self.signing.status()
            c.execute(
                """INSERT INTO execution_receipts_v23(
                     id,principal_id,workspace_id,mission_id,actor_id,effect_intent_id,approval_id,credential_grant_id,
                     capability,target,input_hash,output_hash,effect_state,observed_json,signing_mode,signature,started_at,completed_at,
                     signing_key_id,signing_key_version,public_key,signature_algorithm
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rid, principal_id, intent["workspaceId"], intent.get("missionId"), intent["actorId"], intent["id"],
                 approval_id, credential_grant_id, intent["capability"], intent["target"], input_hash, None,
                 "ATTEMPTED", None, signing_status.get("mode") or "UNAVAILABLE", None, started, None,
                 signing_status.get("keyId"), signing_status.get("keyVersion"), signing_status.get("publicKey"), signing_status.get("algorithm")),
            )
            c.execute("UPDATE effect_intents_v23 SET state='ATTEMPTED' WHERE id=? AND state='AUTHORIZED'", (intent["id"],))
            c.commit()
        return self.execution_receipt(principal_id, rid)

    def finish_execution(self, principal_id: str, receipt_id: str, *, effect_state: str, observed: Any) -> dict[str, Any]:
        if effect_state not in {"ACKNOWLEDGED", "OBSERVED", "VERIFIED", "FAILED", "UNKNOWN"}:
            raise ValueError("execution_effect_state_invalid")
        observed_json = canonical_json(observed)
        output_hash = hashlib.sha256(observed_json.encode("utf-8")).hexdigest()
        with self._lock, self._db() as c:
            r = c.execute("SELECT * FROM execution_receipts_v23 WHERE id=? AND principal_id=?", (receipt_id, principal_id)).fetchone()
            if not r:
                raise ValueError("execution_receipt_not_found")
            if r["completed_at"]:
                # Safe retry of the exact same completion is idempotent; attempts to
                # rewrite the observed outcome or effect state are rejected.
                if r["effect_state"] == effect_state and r["output_hash"] == output_hash:
                    return self.execution_receipt(principal_id, receipt_id)
                raise ValueError("execution_receipt_already_completed")
            signable = {
                "contract": self.receipt_contract,
                "id": r["id"], "principalId": r["principal_id"], "workspaceId": r["workspace_id"],
                "missionId": r["mission_id"], "actorId": r["actor_id"], "effectIntentId": r["effect_intent_id"],
                "approvalId": r["approval_id"], "credentialGrantId": r["credential_grant_id"],
                "capability": r["capability"], "target": r["target"], "inputHash": r["input_hash"],
                "outputHash": output_hash, "effectState": effect_state, "startedAt": r["started_at"],
            }
            envelope = self.signing.sign(canonical_json(signable).encode("utf-8"))
            completed = now_iso()
            c.execute(
                """UPDATE execution_receipts_v23
                   SET output_hash=?,effect_state=?,observed_json=?,signature=?,completed_at=?,signing_mode=?,
                       signing_key_id=?,signing_key_version=?,public_key=?,signature_algorithm=?
                   WHERE id=?""",
                (output_hash, effect_state, observed_json, envelope.signature, completed, envelope.mode,
                 envelope.key_id, envelope.key_version, envelope.public_key, envelope.algorithm, receipt_id),
            )
            c.execute("UPDATE effect_intents_v23 SET state=? WHERE id=?", (effect_state, r["effect_intent_id"]))
            c.commit()
        return self.execution_receipt(principal_id, receipt_id)

    def _recovery_signable(self, r: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        get = r.__getitem__ if isinstance(r, sqlite3.Row) else r.get
        return {
            "contract": self.recovery_contract,
            "id": get("id"),
            "principalId": get("principal_id") if isinstance(r, sqlite3.Row) else get("principalId"),
            "workspaceId": get("workspace_id") if isinstance(r, sqlite3.Row) else get("workspaceId"),
            "effectIntentId": get("effect_intent_id") if isinstance(r, sqlite3.Row) else get("effectIntentId"),
            "receiptId": get("receipt_id") if isinstance(r, sqlite3.Row) else get("receiptId"),
            "semanticKey": get("semantic_key") if isinstance(r, sqlite3.Row) else get("semanticKey"),
            "previousEffectState": get("previous_effect_state") if isinstance(r, sqlite3.Row) else get("previousEffectState"),
            "resolution": get("resolution"),
            "observedHash": get("observed_hash") if isinstance(r, sqlite3.Row) else get("observedHash"),
            "createdAt": get("created_at") if isinstance(r, sqlite3.Row) else get("createdAt"),
        }

    def _recovery_map(self, r: sqlite3.Row) -> dict[str, Any]:
        signable = self._recovery_signable(r)
        raw = canonical_json(signable).encode("utf-8")
        valid = False
        if r["signature"]:
            if (r["signature_algorithm"] or "").lower() == "ed25519" and r["public_key"]:
                valid = SigningProvider.verify_ed25519(raw, r["signature"], r["public_key"])
            elif r["signing_mode"] == "SERVER_HMAC_SHA256":
                exp = hmac.new(self.receipt_key, raw, hashlib.sha256).hexdigest()
                valid = hmac.compare_digest(exp, r["signature"])
        return {
            "contract": self.recovery_contract,
            "id": r["id"],
            "principalId": r["principal_id"],
            "workspaceId": r["workspace_id"],
            "effectIntentId": r["effect_intent_id"],
            "receiptId": r["receipt_id"],
            "semanticKey": r["semantic_key"],
            "previousEffectState": r["previous_effect_state"],
            "resolution": r["resolution"],
            "observed": json.loads(r["observed_json"]),
            "observedHash": r["observed_hash"],
            "signingMode": r["signing_mode"],
            "signature": r["signature"],
            "signingKeyId": r["signing_key_id"],
            "signingKeyVersion": r["signing_key_version"],
            "publicKey": r["public_key"],
            "signatureAlgorithm": r["signature_algorithm"],
            "signatureValid": valid,
            "createdAt": r["created_at"],
        }

    def recovery_candidates(self, principal_id: str, limit: int = 100) -> list[dict[str, Any]]:
        workspace_id = self.shared.active_workspace_id(principal_id)
        with self._db() as c:
            rows = c.execute(
                """
                SELECT r.*, i.execution_mode, i.args_hash
                  FROM execution_receipts_v23 r
                  JOIN effect_intents_v23 i ON i.id=r.effect_intent_id
             LEFT JOIN execution_recoveries_v23 x ON x.receipt_id=r.id
                 WHERE r.principal_id=? AND r.workspace_id=?
                   AND r.effect_state IN ('ATTEMPTED','UNKNOWN')
                   AND x.id IS NULL
              ORDER BY r.started_at DESC
                 LIMIT ?
                """,
                (principal_id, workspace_id, max(1, min(int(limit), 200))),
            ).fetchall()
        out = []
        for r in rows:
            semantic_key = self._effect_semantic_key(
                principal_id=r["principal_id"], workspace_id=r["workspace_id"], execution_mode=r["execution_mode"],
                capability=r["capability"], target=r["target"], args_hash=r["input_hash"],
            )
            out.append({
                "contract": self.recovery_contract,
                "receiptId": r["id"],
                "effectIntentId": r["effect_intent_id"],
                "workspaceId": r["workspace_id"],
                "capability": r["capability"],
                "target": r["target"],
                "executionMode": r["execution_mode"],
                "previousEffectState": r["effect_state"],
                "semanticKey": semantic_key,
                "startedAt": r["started_at"],
                "recoveryRequired": True,
                "autoRetryAllowed": False,
            })
        return out

    def resolve_execution_recovery(self, principal_id: str, receipt_id: str, *, resolution: str, observed: Any) -> dict[str, Any]:
        resolution = str(resolution or "").strip().upper()
        allowed = {"FAILED_BEFORE_EFFECT", "ACKNOWLEDGED", "OBSERVED", "VERIFIED"}
        if resolution not in allowed:
            raise ValueError("execution_recovery_resolution_invalid")
        observed_json = canonical_json(observed)
        observed_hash = hashlib.sha256(observed_json.encode("utf-8")).hexdigest()
        workspace_id = self.shared.active_workspace_id(principal_id)
        with self._lock, self._db() as c:
            existing = c.execute(
                "SELECT * FROM execution_recoveries_v23 WHERE receipt_id=? AND principal_id=?",
                (receipt_id, principal_id),
            ).fetchone()
            if existing:
                if existing["resolution"] == resolution and existing["observed_hash"] == observed_hash:
                    return self._recovery_map(existing)
                raise ValueError("execution_recovery_already_resolved")
            r = c.execute(
                """
                SELECT r.*, i.execution_mode, i.args_hash
                  FROM execution_receipts_v23 r
                  JOIN effect_intents_v23 i ON i.id=r.effect_intent_id
                 WHERE r.id=? AND r.principal_id=? AND r.workspace_id=?
                """,
                (receipt_id, principal_id, workspace_id),
            ).fetchone()
            if not r:
                raise ValueError("execution_receipt_not_found")
            if r["effect_state"] not in {"ATTEMPTED", "UNKNOWN"}:
                raise ValueError("execution_recovery_not_required")
            semantic_key = self._effect_semantic_key(
                principal_id=principal_id, workspace_id=workspace_id, execution_mode=r["execution_mode"],
                capability=r["capability"], target=r["target"], args_hash=r["args_hash"],
            )
            recovery_id = "erec_" + uuid.uuid4().hex[:20]
            created = now_iso()
            signable = {
                "contract": self.recovery_contract,
                "id": recovery_id,
                "principalId": principal_id,
                "workspaceId": workspace_id,
                "effectIntentId": r["effect_intent_id"],
                "receiptId": receipt_id,
                "semanticKey": semantic_key,
                "previousEffectState": r["effect_state"],
                "resolution": resolution,
                "observedHash": observed_hash,
                "createdAt": created,
            }
            envelope = self.signing.sign(canonical_json(signable).encode("utf-8"))
            c.execute(
                """
                INSERT INTO execution_recoveries_v23(
                  id,principal_id,workspace_id,effect_intent_id,receipt_id,semantic_key,previous_effect_state,resolution,
                  observed_json,observed_hash,signing_mode,signature,signing_key_id,signing_key_version,public_key,
                  signature_algorithm,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (recovery_id, principal_id, workspace_id, r["effect_intent_id"], receipt_id, semantic_key,
                 r["effect_state"], resolution, observed_json, observed_hash, envelope.mode, envelope.signature,
                 envelope.key_id, envelope.key_version, envelope.public_key, envelope.algorithm, created),
            )
            aggregate_state = "FAILED" if resolution == "FAILED_BEFORE_EFFECT" else resolution
            c.execute("UPDATE effect_intents_v23 SET state=? WHERE id=?", (aggregate_state, r["effect_intent_id"]))
            c.commit()
            saved = c.execute("SELECT * FROM execution_recoveries_v23 WHERE id=?", (recovery_id,)).fetchone()
        return self._recovery_map(saved)

    def execution_receipt(self, principal_id: str, receipt_id: str) -> dict[str, Any]:
        with self._db() as c:
            r = c.execute("SELECT * FROM execution_receipts_v23 WHERE id=? AND principal_id=?", (receipt_id, principal_id)).fetchone()
            recovery = c.execute(
                "SELECT * FROM execution_recoveries_v23 WHERE receipt_id=? AND principal_id=?",
                (receipt_id, principal_id),
            ).fetchone()
        if not r:
            raise ValueError("execution_receipt_not_found")
        valid = False
        if r["signature"] and r["completed_at"]:
            signable = {
                "contract": self.receipt_contract,
                "id": r["id"], "principalId": r["principal_id"], "workspaceId": r["workspace_id"],
                "missionId": r["mission_id"], "actorId": r["actor_id"], "effectIntentId": r["effect_intent_id"],
                "approvalId": r["approval_id"], "credentialGrantId": r["credential_grant_id"],
                "capability": r["capability"], "target": r["target"], "inputHash": r["input_hash"],
                "outputHash": r["output_hash"], "effectState": r["effect_state"], "startedAt": r["started_at"],
            }
            raw = canonical_json(signable).encode("utf-8")
            if (r["signature_algorithm"] or "").lower() == "ed25519" and r["public_key"]:
                valid = SigningProvider.verify_ed25519(raw, r["signature"], r["public_key"])
            elif r["signing_mode"] == "SERVER_HMAC_SHA256":
                exp = hmac.new(self.receipt_key, raw, hashlib.sha256).hexdigest()
                valid = hmac.compare_digest(exp, r["signature"])
        out = {
            "contract": self.receipt_contract,
            "id": r["id"], "principalId": r["principal_id"], "workspaceId": r["workspace_id"],
            "missionId": r["mission_id"], "actorId": r["actor_id"], "effectIntentId": r["effect_intent_id"],
            "approvalId": r["approval_id"], "credentialGrantId": r["credential_grant_id"],
            "capability": r["capability"], "target": r["target"], "inputHash": r["input_hash"],
            "outputHash": r["output_hash"], "effectState": r["effect_state"],
            "observed": json.loads(r["observed_json"]) if r["observed_json"] else None,
            "signingMode": r["signing_mode"], "signatureAlgorithm": r["signature_algorithm"],
            "signingKeyId": r["signing_key_id"], "signingKeyVersion": r["signing_key_version"],
            "publicKey": r["public_key"], "signature": r["signature"], "signatureValid": valid,
            "publiclyVerifiable": bool(r["public_key"] and (r["signature_algorithm"] or "").lower() == "ed25519"),
            "startedAt": r["started_at"], "completedAt": r["completed_at"],
            "independentAttestation": False,
        }
        out["recoveryRequired"] = r["effect_state"] in {"ATTEMPTED", "UNKNOWN"} and recovery is None
        out["autoRetryAllowed"] = False if out["recoveryRequired"] else None
        out["recovery"] = self._recovery_map(recovery) if recovery else None
        return out

    def receipts(self, principal_id: str, limit: int = 100) -> list[dict[str, Any]]:
        workspace_id = self.shared.active_workspace_id(principal_id)
        with self._db() as c:
            rows = c.execute(
                "SELECT id FROM execution_receipts_v23 WHERE principal_id=? AND workspace_id=? ORDER BY started_at DESC LIMIT ?",
                (principal_id, workspace_id, max(1, min(int(limit), 200))),
            ).fetchall()
        return [self.execution_receipt(principal_id, r["id"]) for r in rows]

    def status(self, principal_id: str | None = None) -> dict[str, Any]:
        result = {
            "contract": self.contract,
            "effectIntentContract": self.effect_contract,
            "approvalContract": self.approval_contract,
            "credentialGrantContract": self.credential_contract,
            "executionReceiptContract": self.receipt_contract,
            "executionRecoveryContract": self.recovery_contract,
            "exactEffectHashing": True,
            "principalBoundApprovals": True,
            "oneTimeApprovalConsumption": True,
            "changedArgumentReplayRejected": True,
            "uncertainEffectAutoRetry": False,
            "uncertainSemanticDuplicateFence": True,
            "uncertainExecutionBoundaryRecheck": True,
            "recoveryInvalidatesStaleApproval": True,
            "authorityPolicyRevalidation": True,
            "workspacePolicyEnforcementCompleteness": "PARTIAL",
            "missionGenerationBinding": True,
            "credentialGrantMode": "CONTROL_PLANE_REFERENCE_OR_HABITAT_BOUND",
            "habitatRuntimeBindingSupported": True,
            "providerNativeEphemeralCredentials": "BLOCKED",
            "signingProviderContract": self.signing.contract,
            "receiptSigning": self.signing.status().get("mode"),
            "receiptSignatureAlgorithm": self.signing.status().get("algorithm"),
            "publicReceiptVerification": bool(self.signing.status().get("publiclyVerifiable")),
            "managedKmsHsm": "REAL" if self.signing.status().get("managedKmsHsm") else "BLOCKED",
            "productionOidcBrowserFlow": "SEPARATE_IDENTITY_PLANE",
            "realFirecrackerHabitat": "BLOCKED",
            "hardwareAttestation": "BLOCKED",
            "truthStatus": "PARTIAL",
        }
        if principal_id:
            result["workspaceId"] = self.shared.active_workspace_id(principal_id)
            result["pendingApprovals"] = len(self.pending_approvals(principal_id))
            result["pendingExecutionRecoveries"] = len(self.recovery_candidates(principal_id))
        return result
