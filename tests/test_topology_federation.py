from datetime import datetime, timedelta, timezone

import pytest

from aie_runtime.engine import AdmissionEngine
from aie_runtime.errors import AIEError
from aie_runtime.store import InMemoryState

NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def test_t1_topology_mutation_requires_policy_allow():
    e = AdmissionEngine(InMemoryState(), policy=lambda _: False, clock=lambda: NOW)
    with pytest.raises(AIEError) as exc:
        e.authorize_topology_mutation(actor="agent:x", mutation="spawn", target="agent:y")
    assert exc.value.code == "AIE-TOPO-001"


def test_f1_rejects_unknown_remote_issuer():
    e = AdmissionEngine(InMemoryState(), policy=lambda _: True, clock=lambda: NOW, trusted_issuers={"https://issuer.example"})
    with pytest.raises(AIEError) as exc:
        e.verify_federated_identity(issuer="https://evil.example", clock_skew=timedelta(seconds=0), max_clock_skew=timedelta(seconds=30), revocation_fresh=True)
    assert exc.value.code == "AIE-FED-001"


def test_f1_rejects_clock_skew_above_bound():
    e = AdmissionEngine(InMemoryState(), policy=lambda _: True, clock=lambda: NOW, trusted_issuers={"https://issuer.example"})
    with pytest.raises(AIEError) as exc:
        e.verify_federated_identity(issuer="https://issuer.example", clock_skew=timedelta(seconds=31), max_clock_skew=timedelta(seconds=30), revocation_fresh=True)
    assert exc.value.code == "AIE-FED-002"


def test_f1_rejects_unknown_revocation_freshness():
    e = AdmissionEngine(InMemoryState(), policy=lambda _: True, clock=lambda: NOW, trusted_issuers={"https://issuer.example"})
    with pytest.raises(AIEError) as exc:
        e.verify_federated_identity(issuer="https://issuer.example", clock_skew=timedelta(seconds=1), max_clock_skew=timedelta(seconds=30), revocation_fresh=False)
    assert exc.value.code == "AIE-FRESH-001"
