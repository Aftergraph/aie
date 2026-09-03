from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bridge import SPIFFEBridgeServer, create_spiffe_bridge
from .tls import build_client_ssl_context, build_server_ssl_context
from .workload_api import RotatingTLSContextProvider, WorkloadAPIClient, WorkloadAPISVIDWatcher, build_ssl_contexts_from_svid


@dataclass
class BuiltBridge:
    server: SPIFFEBridgeServer
    watcher: WorkloadAPISVIDWatcher | None = None


def _resolve(base: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def build_bridge_from_config(config_path: str | Path) -> BuiltBridge:
    path = Path(config_path)
    config: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    listen = config.get("listen") or {}
    upstream = config["upstream"]

    workload_provider = None
    watcher = None
    material = None
    workload = config.get("workload_api")
    if workload:
        endpoint = str(workload.get("endpoint") or os.environ.get("SPIFFE_ENDPOINT_SOCKET") or "")
        if not endpoint:
            raise ValueError("workload_api endpoint or SPIFFE_ENDPOINT_SOCKET is required")
        client = WorkloadAPIClient(endpoint)
        material = client.fetch_x509_svid(timeout=float(workload.get("timeout", 5.0)), hint=workload.get("hint"))
        if bool(workload.get("watch", False)):
            workload_provider = RotatingTLSContextProvider(material, require_client_cert=True)
            watcher = WorkloadAPISVIDWatcher(
                client,
                workload_provider,
                hint=workload.get("hint"),
                reconnect_delay=float(workload.get("reconnect_delay", 0.5)),
            )

    inbound_context = None
    inbound_provider = None
    listen_tls = listen.get("tls")
    if listen_tls:
        if listen_tls.get("source") == "workload_api":
            if workload_provider is not None:
                inbound_provider = workload_provider
            elif material is not None:
                inbound_context, _ = build_ssl_contexts_from_svid(material, require_client_cert=True)
            else:
                raise ValueError("workload_api listen TLS requires workload_api configuration")
        else:
            inbound_context = build_server_ssl_context(
                certfile=_resolve(base, listen_tls["certfile"]),
                keyfile=_resolve(base, listen_tls["keyfile"]),
                cafile=_resolve(base, listen_tls["cafile"]),
                require_client_cert=bool(listen_tls.get("require_client_cert", True)),
            )

    outbound_context = None
    outbound_provider = None
    upstream_tls = upstream.get("tls")
    if upstream_tls:
        if upstream_tls.get("source") == "workload_api":
            if workload_provider is not None:
                outbound_provider = workload_provider.client_context
            elif material is not None:
                _, outbound_context = build_ssl_contexts_from_svid(material, require_client_cert=True)
            else:
                raise ValueError("workload_api upstream TLS requires workload_api configuration")
        else:
            outbound_context = build_client_ssl_context(
                certfile=_resolve(base, upstream_tls["certfile"]),
                keyfile=_resolve(base, upstream_tls["keyfile"]),
                cafile=_resolve(base, upstream_tls["cafile"]),
            )

    server = create_spiffe_bridge(
        upstream_base_url=str(upstream["url"]),
        host=str(listen.get("host", "127.0.0.1")),
        port=int(listen.get("port", 0)),
        timeout=float(upstream.get("timeout", 5.0)),
        inbound_ssl_context=inbound_context,
        inbound_tls_context_provider=inbound_provider,
        expected_client_spiffe_ids=set(config.get("expected_client_spiffe_ids", [])),
        outbound_ssl_context=outbound_context,
        outbound_ssl_context_provider=outbound_provider,
        expected_upstream_spiffe_id=upstream.get("expected_spiffe_id"),
    )
    return BuiltBridge(server=server, watcher=watcher)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AIE SPIFFE transport bridge")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    built = build_bridge_from_config(args.config)
    if built.watcher is not None:
        built.watcher.start()
    try:
        built.server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if built.watcher is not None:
            built.watcher.stop()
            built.watcher.join(timeout=2.0)
        built.server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
