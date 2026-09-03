import pytest

from aie_runtime.errors import AIEError
from aie_runtime.gateway.identity import TransportIdentity, VerifiedIdentityResolver


def test_verified_spiffe_identity_resolves():
    resolver = VerifiedIdentityResolver()
    identity = resolver.resolve(TransportIdentity(spiffe_id="spiffe://example.org/agent/refund", verified=True))
    assert identity == "spiffe://example.org/agent/refund"


def test_unverified_spiffe_identity_fails_closed():
    resolver = VerifiedIdentityResolver()
    with pytest.raises(AIEError) as exc:
        resolver.resolve(TransportIdentity(spiffe_id="spiffe://evil.invalid/agent", verified=False))
    assert exc.value.code == "AIE-IDENT-001"


def test_non_spiffe_identity_fails_closed():
    resolver = VerifiedIdentityResolver()
    with pytest.raises(AIEError) as exc:
        resolver.resolve(TransportIdentity(spiffe_id="https://example.org/agent", verified=True))
    assert exc.value.code == "AIE-IDENT-001"
