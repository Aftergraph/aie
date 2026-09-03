from __future__ import annotations

import ssl
from pathlib import Path


def build_server_ssl_context(
    *,
    certfile: str | Path,
    keyfile: str | Path,
    cafile: str | Path,
    require_client_cert: bool = True,
) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=str(certfile), keyfile=str(keyfile))
    context.load_verify_locations(cafile=str(cafile))
    context.verify_mode = ssl.CERT_REQUIRED if require_client_cert else ssl.CERT_OPTIONAL
    return context


def build_client_ssl_context(
    *,
    certfile: str | Path,
    keyfile: str | Path,
    cafile: str | Path,
) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(cafile))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=str(certfile), keyfile=str(keyfile))
    # SPIFFE authenticates workload identity using URI SAN, not DNS hostnames.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED
    return context
