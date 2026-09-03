from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from aie_runtime.errors import AIEError


@dataclass(frozen=True)
class TransportIdentity:
    spiffe_id: str | None
    verified: bool
    source: str = "transport"


class VerifiedIdentityResolver:
    def resolve(self, context: TransportIdentity) -> str:
        if not context.verified or not context.spiffe_id:
            raise AIEError("AIE-IDENT-001")
        _validate_spiffe_leaf_id(context.spiffe_id)
        return context.spiffe_id


def _validate_spiffe_leaf_id(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "spiffe"
        or not parsed.netloc
        or parsed.path in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
    ):
        raise AIEError("AIE-IDENT-001")
    return value


def extract_spiffe_id_from_peer_certificate(cert: dict, *, verified: bool) -> str:
    """Resolve a SPIFFE leaf identity from a TLS peer certificate decoded by ssl.

    TLS chain verification is expected to have already succeeded. This function applies
    SPIFFE-specific URI SAN cardinality and leaf-ID syntax checks.
    """
    if not verified or not isinstance(cert, dict):
        raise AIEError("AIE-IDENT-001")
    sans = cert.get("subjectAltName") or ()
    uri_sans = [value for kind, value in sans if kind == "URI" and isinstance(value, str)]
    if len(uri_sans) != 1:
        raise AIEError("AIE-IDENT-001")
    return _validate_spiffe_leaf_id(uri_sans[0])


def validate_x509_svid_der(der_certificate: bytes, *, verified: bool) -> str:
    """Apply SPIFFE X.509 leaf constraints after the TLS stack has verified the chain."""
    if not verified or not der_certificate:
        raise AIEError("AIE-IDENT-001")
    try:
        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID

        cert = x509.load_der_x509_certificate(der_certificate)
        basic = cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value
        if basic.ca:
            raise AIEError("AIE-IDENT-001")
        key_usage = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
        if key_usage.key_cert_sign or key_usage.crl_sign or not key_usage.digital_signature:
            raise AIEError("AIE-IDENT-001")
        san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        uri_sans = san.get_values_for_type(x509.UniformResourceIdentifier)
        if len(uri_sans) != 1:
            raise AIEError("AIE-IDENT-001")
        return _validate_spiffe_leaf_id(uri_sans[0])
    except AIEError:
        raise
    except Exception as exc:
        raise AIEError("AIE-IDENT-001") from exc
