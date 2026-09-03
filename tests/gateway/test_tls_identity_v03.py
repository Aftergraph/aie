import ssl

import pytest

from aie_runtime.errors import AIEError
from aie_runtime.gateway.identity import extract_spiffe_id_from_peer_certificate


def test_extracts_single_spiffe_uri_san_from_verified_peer_certificate():
    cert = {"subjectAltName": (("URI", "spiffe://example.org/agent/refund"),)}
    assert extract_spiffe_id_from_peer_certificate(cert, verified=True) == "spiffe://example.org/agent/refund"


def test_rejects_peer_certificate_without_spiffe_uri_san():
    with pytest.raises(AIEError) as exc:
        extract_spiffe_id_from_peer_certificate({"subjectAltName": (("DNS", "agent.example.org"),)}, verified=True)
    assert exc.value.code == "AIE-IDENT-001"


def test_rejects_unverified_peer_even_when_spiffe_san_is_present():
    cert = {"subjectAltName": (("URI", "spiffe://example.org/agent/refund"),)}
    with pytest.raises(AIEError) as exc:
        extract_spiffe_id_from_peer_certificate(cert, verified=False)
    assert exc.value.code == "AIE-IDENT-001"


def test_rejects_ambiguous_multiple_spiffe_uri_sans():
    cert = {
        "subjectAltName": (
            ("URI", "spiffe://example.org/agent/a"),
            ("URI", "spiffe://example.org/agent/b"),
        )
    }
    with pytest.raises(AIEError) as exc:
        extract_spiffe_id_from_peer_certificate(cert, verified=True)
    assert exc.value.code == "AIE-IDENT-001"


def test_rejects_certificate_with_extra_non_spiffe_uri_san():
    cert = {
        "subjectAltName": (
            ("URI", "spiffe://example.org/agent/refund"),
            ("URI", "https://example.org/other"),
        )
    }
    with pytest.raises(AIEError) as exc:
        extract_spiffe_id_from_peer_certificate(cert, verified=True)
    assert exc.value.code == "AIE-IDENT-001"


def test_rejects_spiffe_leaf_identity_without_non_root_path():
    cert = {"subjectAltName": (("URI", "spiffe://example.org"),)}
    with pytest.raises(AIEError) as exc:
        extract_spiffe_id_from_peer_certificate(cert, verified=True)
    assert exc.value.code == "AIE-IDENT-001"
