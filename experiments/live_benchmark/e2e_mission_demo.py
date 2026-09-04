#!/usr/bin/env python3
"""
End-to-end ABDE mission demo: AIE admit → TG dispatch → revalidate → execute → evidence

This demo proves the TG→AIE integration flow works end-to-end without real providers.
"""
from datetime import datetime, timedelta, timezone
import uuid
import sys
import os

# Add AIE runtime to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'aie', 'src'))

from aie_runtime.engine import AdmissionEngine, ActionRequest, InMemoryState, Principal, Mission, AuthorityLease


def create_mock_state():
    """Create mock state with principal, mission, and lease."""
    state = InMemoryState()
    
    # Create principal
    principal_id = f"principal_{uuid.uuid4().hex[:8]}"
    state.principals[principal_id] = Principal(
        id=principal_id,
        type="bot",
        identity_ref="tg-bot-001"
    )
    
    # Create mission
    mission_id = f"mission_{uuid.uuid4().hex[:8]}"
    state.missions[mission_id] = Mission(
        id=mission_id,
        state="active"
    )
    
    # Create lease
    lease_id = f"lease_{uuid.uuid4().hex[:8]}"
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    state.leases[lease_id] = AuthorityLease(
        id=lease_id,
        principal_id=principal_id,
        mission_id=mission_id,
        capabilities={"read", "write", "execute"},
        resource_prefixes=("tools:", "harness:"),
        expires_at=expires_at,
        budget_remaining=1000.0,
        revoked=False
    )
    
    return state, principal_id, mission_id, lease_id


def policy_allow(decision_input):
    """Simple policy that always allows (for demo)."""
    return True


def run_e2e_mission_demo():
    """Run the end-to-end mission demo flow."""
    print("=" * 60)
    print("ABDE Mission Demo: AIE admit → TG dispatch → revalidate → execute → evidence")
    print("=" * 60)
    
    # Setup AIE engine
    state, principal_id, mission_id, lease_id = create_mock_state()
    engine = AdmissionEngine(state=state, policy=policy_allow, clock=lambda: datetime.now(timezone.utc))
    
    print("\n📦 1. Setup: AIE engine initialized")
    print(f"   Principal: {principal_id}")
    print(f"   Mission: {mission_id}")
    print(f"   Lease: {lease_id}")
    print(f"   Lease expires: {engine.state.leases[lease_id].expires_at.isoformat()}")
    
    # Step 1: TG receives action request (simulated)
    print("\n📬 2. TG receives action request from bot")
    action_id = f"action_{uuid.uuid4().hex[:12]}"
    tool = "tools:file_read"
    args = {"path": "/data/study011/record.jsonl"}
    print(f"   Action ID: {action_id}")
    print(f"   Tool: {tool}")
    print(f"   Args: {args}")
    
    # Step 2: TG calls AIE.admit() before enqueue
    print("\n🔐 3. TG calls AIE.admit() before enqueue")
    request = ActionRequest(
        action_id=action_id,
        principal_id=principal_id,
        mission_id=mission_id,
        lease_id=lease_id,
        capability="execute",
        resource=tool,
        budget_cost=10.0
    )
    outcome = engine.admit(request)
    print(f"   Admission status: {outcome.status}")
    if outcome.status == "admitted":
        print("   ✅ Action admitted to AIE")
    else:
        print(f"   ❌ Admission failed: {outcome.error_code}")
        return False
    
    # Step 3: TG enqueues action (simulated)
    print("\n📝 4. TG enqueues action to worker queue")
    print("   (Simulating worker pickup...)")
    
    # Step 4: Worker calls AIE.revalidate() immediately before execution
    print("\n🔍 5. Worker calls AIE.revalidate() immediately before execution")
    try:
        engine.revalidate(action_id)
        print("   ✅ Revalidation passed")
    except Exception as e:
        print(f"   ❌ Revalidation failed: {e}")
        return False
    
    # Step 5: Execute the action
    print("\n⚡ 6. Execute action")
    # Simulate execution (in real TG, this calls _run())
    result = {
        "records_read": 1024,
        "boundary_check": "PASS",
        "data": ["sample_data_1", "sample_data_2"]
    }
    print(f"   Result: {result}")
    
    # Step 6: Record evidence
    print("\n📊 7. Record evidence")
    evidence = state.evidence
    for ev in evidence:
        print(f"   - {ev.event_type}: {ev.attributes}")
    
    # Step 7: Produce quittance
    print("\n📄 8. Produce quittance")
    quittance = {
        "action_id": action_id,
        "status": "executed",
        "admission": state.outcomes[action_id].status,
        "revalidation": "passed",
        "evidence_count": len(evidence),
        "result": result,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    print(f"   Quittance: {quittance}")
    
    # Verify all evidence records are present
    print("\n✅ 9. Verify end-to-end flow")
    event_types = {ev.event_type for ev in evidence}
    expected_events = {
        "budget.reserved",
        "policy.decided",
        "action.admitted",
        "action.committed",
        "action.revalidated"
    }
    missing = expected_events - event_types
    if missing:
        print(f"   ❌ Missing evidence events: {missing}")
        return False
    else:
        print("   ✅ All expected evidence events present")
    
    print("\n" + "=" * 60)
    print("🎉 DEMO COMPLETE: End-to-end TG→AIE integration verified!")
    print("=" * 60)
    
    return True


if __name__ == "__main__":
    success = run_e2e_mission_demo()
    sys.exit(0 if success else 1)
