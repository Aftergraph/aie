from datetime import datetime, timedelta, timezone

from aie_runtime.engine import AdmissionEngine, ActionRequest, AuthorityLease, Mission, Principal
from aie_runtime.store import InMemoryState

NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def test_successful_admission_emits_minimized_ordered_evidence():
    state = InMemoryState()
    state.principals['agent:a'] = Principal('agent:a', 'agent', 'spiffe://example.ai/a')
    state.missions['mission:m'] = Mission('mission:m', 'active')
    state.leases['lease:l'] = AuthorityLease(
        id='lease:l', principal_id='agent:a', mission_id='mission:m',
        capabilities={'repo.write'}, resource_prefixes=('repo://acme/',),
        expires_at=NOW + timedelta(minutes=5), budget_remaining=2,
    )
    e = AdmissionEngine(state, policy=lambda _: True, clock=lambda: NOW)
    e.admit(ActionRequest('a1','agent:a','mission:m','lease:l','repo.write','repo://acme/x',1))
    types = [r.event_type for r in state.evidence]
    assert types == ['budget.reserved', 'policy.decided', 'action.admitted', 'action.committed']
    assert all('payload' not in r.attributes for r in state.evidence)
