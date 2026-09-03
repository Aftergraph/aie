from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Iterator
from urllib.parse import urlparse

import grpc


FETCH_X509_SVID_METHOD = "/SpiffeWorkloadAPI/FetchX509SVID"
SECURITY_METADATA = (("workload.spiffe.io", "true"),)


@dataclass(frozen=True)
class WorkloadAPISVID:
    spiffe_id: str
    x509_svid: bytes
    x509_svid_key: bytes
    bundle: bytes
    hint: str = ""


def parse_workload_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme == "unix":
        if not parsed.path or not parsed.path.startswith("/"):
            raise ValueError("unix SPIFFE endpoint must use an absolute path")
        return f"unix:{parsed.path}"
    if parsed.scheme == "tcp":
        if not parsed.hostname or parsed.port is None:
            raise ValueError("tcp SPIFFE endpoint requires host and port")
        return f"{parsed.hostname}:{parsed.port}"
    raise ValueError("SPIFFE endpoint must use unix:// or tcp://")


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(data) or shift >= 70:
            raise ValueError("invalid protobuf varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7


def _fields(data: bytes):
    offset = 0
    while offset < len(data):
        tag, offset = _read_varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if number == 0:
            raise ValueError("invalid protobuf field number")
        if wire == 0:
            _, offset = _read_varint(data, offset)
            yield number, wire, None
        elif wire == 1:
            end = offset + 8
            if end > len(data):
                raise ValueError("truncated protobuf fixed64")
            yield number, wire, data[offset:end]
            offset = end
        elif wire == 2:
            length, offset = _read_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ValueError("truncated protobuf bytes")
            yield number, wire, data[offset:end]
            offset = end
        elif wire == 5:
            end = offset + 4
            if end > len(data):
                raise ValueError("truncated protobuf fixed32")
            yield number, wire, data[offset:end]
            offset = end
        else:
            raise ValueError(f"unsupported protobuf wire type: {wire}")


def _parse_x509_svid(data: bytes) -> WorkloadAPISVID:
    values: dict[int, bytes] = {}
    for number, wire, payload in _fields(data):
        if wire == 2 and payload is not None and number in {1, 2, 3, 4, 5}:
            values[number] = payload
    required = (1, 2, 3, 4)
    if any(number not in values for number in required):
        raise ValueError("SPIFFE Workload API returned an incomplete X509SVID")
    return WorkloadAPISVID(
        spiffe_id=values[1].decode("utf-8"),
        x509_svid=values[2],
        x509_svid_key=values[3],
        bundle=values[4],
        hint=values.get(5, b"").decode("utf-8"),
    )


def _parse_x509_svid_response(data: bytes) -> list[WorkloadAPISVID]:
    svids: list[WorkloadAPISVID] = []
    for number, wire, payload in _fields(data):
        if number == 1 and wire == 2 and payload is not None:
            svids.append(_parse_x509_svid(payload))
    if not svids:
        raise ValueError("SPIFFE Workload API returned no X509SVID entries")
    return svids


class X509SVIDSubscription:
    def __init__(self, channel, call, *, hint: str | None):
        self._channel = channel
        self._call = call
        self._hint = hint
        self._closed = False

    def __iter__(self) -> Iterator[WorkloadAPISVID]:
        for response in self._call:
            svids = _parse_x509_svid_response(response)
            if self._hint:
                for svid in svids:
                    if svid.hint == self._hint:
                        yield svid
                        break
                else:
                    raise ValueError(f"no X509SVID matches hint {self._hint!r}")
            else:
                yield svids[0]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._call.cancel()
        finally:
            self._channel.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class WorkloadAPIClient:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.target = parse_workload_endpoint(endpoint)

    def subscribe_x509_svid(
        self, *, timeout: float | None = None, hint: str | None = None
    ) -> X509SVIDSubscription:
        channel = grpc.insecure_channel(self.target)
        rpc = channel.unary_stream(
            FETCH_X509_SVID_METHOD,
            request_serializer=lambda raw: raw,
            response_deserializer=lambda raw: raw,
        )
        kwargs = {"metadata": SECURITY_METADATA}
        if timeout is not None:
            kwargs["timeout"] = timeout
        call = rpc(b"", **kwargs)
        return X509SVIDSubscription(channel, call, hint=hint)

    def stream_x509_svid(
        self, *, timeout: float | None = None, hint: str | None = None
    ) -> Iterator[WorkloadAPISVID]:
        subscription = self.subscribe_x509_svid(timeout=timeout, hint=hint)
        try:
            yield from subscription
        finally:
            subscription.close()

    def fetch_x509_svid(self, *, timeout: float = 5.0, hint: str | None = None) -> WorkloadAPISVID:
        subscription = self.subscribe_x509_svid(timeout=timeout, hint=hint)
        try:
            return next(iter(subscription))
        finally:
            subscription.close()


def _split_der_objects(data: bytes) -> list[bytes]:
    objects: list[bytes] = []
    offset = 0
    while offset < len(data):
        if data[offset] != 0x30:
            raise ValueError("expected DER SEQUENCE")
        if offset + 2 > len(data):
            raise ValueError("truncated DER object")
        first_len = data[offset + 1]
        if first_len < 0x80:
            header_len = 2
            content_len = first_len
        else:
            length_octets = first_len & 0x7F
            if length_octets == 0 or length_octets > 4 or offset + 2 + length_octets > len(data):
                raise ValueError("invalid DER length")
            header_len = 2 + length_octets
            content_len = int.from_bytes(data[offset + 2:offset + 2 + length_octets], "big")
        end = offset + header_len + content_len
        if end > len(data):
            raise ValueError("truncated DER object")
        objects.append(data[offset:end])
        offset = end
    if not objects:
        raise ValueError("empty DER sequence set")
    return objects


def build_ssl_contexts_from_svid(
    material: WorkloadAPISVID,
    *,
    require_client_cert: bool = True,
):
    """Build server/client SSL contexts from a Workload API X509-SVID snapshot.

    The returned contexts have loaded their credentials already. Temporary PEM files
    are removed before this function returns. Credential rotation is intentionally
    outside this v0.3 helper and requires rebuilding/replacing the contexts.
    """
    import tempfile
    from pathlib import Path
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from .tls import build_client_ssl_context, build_server_ssl_context

    cert_pem = b"".join(
        x509.load_der_x509_certificate(part).public_bytes(serialization.Encoding.PEM)
        for part in _split_der_objects(material.x509_svid)
    )
    bundle_pem = b"".join(
        x509.load_der_x509_certificate(part).public_bytes(serialization.Encoding.PEM)
        for part in _split_der_objects(material.bundle)
    )
    key = serialization.load_der_private_key(material.x509_svid_key, password=None)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with tempfile.TemporaryDirectory(prefix="aie-spiffe-") as tmp:
        root = Path(tmp)
        certfile = root / "svid-chain.pem"
        keyfile = root / "svid-key.pem"
        cafile = root / "bundle.pem"
        certfile.write_bytes(cert_pem)
        keyfile.write_bytes(key_pem)
        cafile.write_bytes(bundle_pem)
        server_context = build_server_ssl_context(
            certfile=certfile,
            keyfile=keyfile,
            cafile=cafile,
            require_client_cert=require_client_cert,
        )
        client_context = build_client_ssl_context(
            certfile=certfile,
            keyfile=keyfile,
            cafile=cafile,
        )
    return server_context, client_context

class RotatingTLSContextProvider:
    """Atomically swaps complete server/client TLS context snapshots.

    New inbound connections and outbound requests obtain the current context;
    existing connections are allowed to finish on the snapshot they accepted with.
    """

    def __init__(self, material: WorkloadAPISVID, *, require_client_cert: bool = True):
        self._lock = threading.RLock()
        self._require_client_cert = require_client_cert
        self._server_context = None
        self._client_context = None
        self._spiffe_id = ""
        self._generation = 0
        self.update(material)

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def spiffe_id(self) -> str:
        with self._lock:
            return self._spiffe_id

    def update(self, material: WorkloadAPISVID) -> int:
        server_context, client_context = build_ssl_contexts_from_svid(
            material, require_client_cert=self._require_client_cert
        )
        with self._lock:
            self._server_context = server_context
            self._client_context = client_context
            self._spiffe_id = material.spiffe_id
            self._generation += 1
            return self._generation

    def server_context(self):
        with self._lock:
            return self._server_context

    def client_context(self):
        with self._lock:
            return self._client_context


class WorkloadAPISVIDWatcher:
    def __init__(
        self,
        client: WorkloadAPIClient,
        provider: RotatingTLSContextProvider,
        *,
        hint: str | None = None,
        reconnect_delay: float = 0.5,
    ):
        self.client = client
        self.provider = provider
        self.hint = hint
        self.reconnect_delay = reconnect_delay
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._subscription: X509SVIDSubscription | None = None
        self.last_error: Exception | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="aie-spiffe-svid-watcher", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                subscription = self.client.subscribe_x509_svid(hint=self.hint)
                self._subscription = subscription
                with subscription:
                    for material in subscription:
                        if self._stop.is_set():
                            break
                        self.provider.update(material)
                self.last_error = None
            except grpc.RpcError as exc:
                if not self._stop.is_set():
                    self.last_error = exc
            except Exception as exc:
                if not self._stop.is_set():
                    self.last_error = exc
            finally:
                self._subscription = None
            if not self._stop.is_set():
                self._stop.wait(self.reconnect_delay)

    def stop(self) -> None:
        self._stop.set()
        subscription = self._subscription
        if subscription is not None:
            subscription.close()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

