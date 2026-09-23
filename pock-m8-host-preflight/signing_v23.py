from __future__ import annotations

import base64
import hashlib
import os
import json
import urllib.request
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


@dataclass(frozen=True)
class SignatureEnvelope:
    algorithm: str
    mode: str
    key_id: str
    key_version: str
    signature: str
    public_key: str | None
    independent_attestation: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "mode": self.mode,
            "keyId": self.key_id,
            "keyVersion": self.key_version,
            "signature": self.signature,
            "publicKey": self.public_key,
            "independentAttestation": self.independent_attestation,
        }


class SigningProvider:
    """Canonical v23 signing-provider boundary.

    Implementations may hold a local software key or delegate to a managed KMS/HSM.
    The provider contract deliberately distinguishes public verifiability from
    independent/externally-held attestation.
    """

    contract = "SigningProvider/v1"

    def sign(self, payload: bytes) -> SignatureEnvelope:  # pragma: no cover - interface
        raise NotImplementedError

    def status(self) -> dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError

    @staticmethod
    def verify_ed25519(payload: bytes, signature_b64: str, public_key_b64: str) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64)).verify(
                base64.b64decode(signature_b64), payload
            )
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False


class LocalEd25519SigningProvider(SigningProvider):
    def __init__(self, private_key: Ed25519PrivateKey, *, mode: str, key_version: str = "1"):
        self._private_key = private_key
        self._public_raw = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self._public_b64 = base64.b64encode(self._public_raw).decode("ascii")
        self._key_id = "ed25519:" + hashlib.sha256(self._public_raw).hexdigest()[:24]
        self._mode = mode
        self._key_version = str(key_version or "1")

    def sign(self, payload: bytes) -> SignatureEnvelope:
        sig = self._private_key.sign(payload)
        return SignatureEnvelope(
            algorithm="Ed25519",
            mode=self._mode,
            key_id=self._key_id,
            key_version=self._key_version,
            signature=base64.b64encode(sig).decode("ascii"),
            public_key=self._public_b64,
            independent_attestation=False,
        )

    def status(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "configured": True,
            "mode": self._mode,
            "algorithm": "Ed25519",
            "keyId": self._key_id,
            "keyVersion": self._key_version,
            "publicKey": self._public_b64,
            "publiclyVerifiable": True,
            "managedKmsHsm": False,
            "independentAttestation": False,
        }




class HTTPManagedSigningProvider(SigningProvider):
    """Provider-neutral remote signing adapter.

    The remote service owns private-key custody. POCK only sends the canonical
    payload and receives an Ed25519 signature/public key. This proves the adapter
    boundary but does not by itself prove that the remote service is backed by a
    specific cloud KMS or hardware HSM.
    """

    def __init__(self, base_url: str, token: str, key_id: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.key_id = key_id

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token and self.key_id)

    def sign(self, payload: bytes) -> SignatureEnvelope:
        if not self.configured:
            raise RuntimeError("managed_signing_provider_unavailable")
        body = json.dumps({
            "keyId": self.key_id,
            "payload": base64.b64encode(payload).decode("ascii"),
            "algorithm": "Ed25519",
        }, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/v1/sign",
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                out = json.loads(r.read().decode("utf-8") or "{}")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("managed_signing_request_failed") from exc
        if out.get("algorithm") != "Ed25519" or not out.get("signature") or not out.get("publicKey"):
            raise RuntimeError("managed_signing_response_invalid")
        if not self.verify_ed25519(payload, out["signature"], out["publicKey"]):
            raise RuntimeError("managed_signing_response_verification_failed")
        return SignatureEnvelope(
            algorithm="Ed25519",
            mode="HTTP_MANAGED_ED25519",
            key_id=str(out.get("keyId") or self.key_id),
            key_version=str(out.get("keyVersion") or "unknown"),
            signature=str(out["signature"]),
            public_key=str(out["publicKey"]),
            independent_attestation=False,
        )

    def status(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "configured": self.configured,
            "mode": "HTTP_MANAGED_ED25519",
            "algorithm": "Ed25519",
            "keyId": self.key_id or None,
            "keyVersion": None,
            "publicKey": None,
            "publiclyVerifiable": True if self.configured else False,
            "managedSigningAdapter": True,
            "managedKmsHsm": False,
            "privateKeyInPockProcess": False,
            "independentAttestation": False,
            "productionHardwareProviderVerified": False,
        }


class BlockedManagedSigningProvider(SigningProvider):
    def __init__(self, *, provider_name: str = "managed-kms"):
        self.provider_name = provider_name

    def sign(self, payload: bytes) -> SignatureEnvelope:
        raise RuntimeError("managed_signing_provider_unavailable")

    def status(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "configured": False,
            "mode": self.provider_name,
            "algorithm": None,
            "keyId": None,
            "keyVersion": None,
            "publicKey": None,
            "publiclyVerifiable": False,
            "managedKmsHsm": False,
            "independentAttestation": False,
            "blockedReason": "managed_signing_provider_unavailable",
        }


def _private_key_from_env() -> Ed25519PrivateKey | None:
    raw = os.environ.get("POCK_SIGNING_PRIVATE_KEY_B64", "").strip()
    if not raw:
        return None
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("signing_private_key_invalid_base64") from exc
    if len(decoded) != 32:
        raise RuntimeError("signing_private_key_invalid_length")
    return Ed25519PrivateKey.from_private_bytes(decoded)


def build_signing_provider(environment: str, fallback_secret: bytes) -> SigningProvider:
    requested = os.environ.get("POCK_SIGNING_PROVIDER", "local-ed25519").strip().lower()
    version = os.environ.get("POCK_SIGNING_KEY_VERSION", "1")
    if requested in {"http-kms", "managed-http", "remote-signing"}:
        return HTTPManagedSigningProvider(
            os.environ.get("POCK_SIGNING_URL", os.environ.get("POCK_KMS_URL", "")),
            os.environ.get("POCK_SIGNING_TOKEN", os.environ.get("POCK_KMS_TOKEN", "")),
            os.environ.get("POCK_SIGNING_KEY_ID", os.environ.get("POCK_KMS_KEY_ID", "")),
        )
    if requested in {"managed-kms", "kms", "hsm"}:
        # A named managed provider without an implemented adapter remains blocked.
        return BlockedManagedSigningProvider(provider_name=requested)

    explicit = _private_key_from_env()
    if explicit is not None:
        return LocalEd25519SigningProvider(explicit, mode="CONFIGURED_ED25519", key_version=version)

    if environment == "production":
        return BlockedManagedSigningProvider(provider_name="production-signing-key-required")

    seed = hashlib.sha256(b"pock-v23-signing-provider|" + bytes(fallback_secret)).digest()
    return LocalEd25519SigningProvider(
        Ed25519PrivateKey.from_private_bytes(seed),
        mode="DEVELOPMENT_DERIVED_ED25519",
        key_version=version,
    )
