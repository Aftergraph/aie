from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Any

from aie_runtime.engine import AuthorityLease, Mission, Principal
from aie_runtime.store import InMemoryState

from .core import AIEGateway
from .durable import SQLiteGatewayStore
from .federation import RevocationReplicator
from .forwarding import HTTPUpstreamForwarder
from .http import create_http_server
from .policy import LocalPolicyAdapter, OPADataAPIAdapter
from .tls import build_client_ssl_context, build_server_ssl_context
from .workload_api import (
    RotatingTLSContextProvider,
    WorkloadAPIClient,
    WorkloadAPISVIDWatcher,
    build_ssl_contexts_from_svid,
)


def _load_config(config_path: str | Path) -> tuple[Path, dict[str, Any]]:
    path = Path(config_path)
    return path, json.loads(path.read_text(encoding="utf-8"))


def _resolve(base: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def _client_tls_context(
    base: Path,
    config: dict[str, Any] | None,
    *,
    workload_client_context=None,
):
    if not config:
        return None
    if config.get("source") == "workload_api":
        if workload_client_context is None:
            raise ValueError("workload_api TLS source requires top-level workload_api configuration")
        return workload_client_context
    return build_client_ssl_context(
        certfile=_resolve(base, config["certfile"]),
        keyfile=_resolve(base, config["keyfile"]),
        cafile=_resolve(base, config["cafile"]),
    )


def build_gateway_from_config(
    config_path: str | Path,
    *,
    clock: Callable[[], datetime] | None = None,
) -> AIEGateway:
    path, config = _load_config(config_path)
    state = InMemoryState()

    for value in config.get("principals", []):
        principal = Principal(value["id"], value["type"], value["identity_ref"])
        state.principals[principal.id] = principal
    for value in config.get("missions", []):
        mission = Mission(value["id"], value["state"])
        state.missions[mission.id] = mission
    for value in config.get("leases", []):
        lease = AuthorityLease(
            id=value["id"],
            principal_id=value["principal_id"],
            mission_id=value["mission_id"],
            capabilities=set(value.get("capabilities", [])),
            resource_prefixes=tuple(value.get("resource_prefixes", [])),
            expires_at=datetime.fromisoformat(value["expires_at"]),
            budget_remaining=float(value.get("budget_remaining", 0)),
            revoked=bool(value.get("revoked", False)),
            parent_lease_id=value.get("parent_lease_id"),
            depth=int(value.get("depth", 0)),
            max_delegation_depth=int(value.get("max_delegation_depth", 0)),
        )
        state.leases[lease.id] = lease

    policy_config = config.get("policy", {"type": "local", "decision": "deny"})
    if policy_config.get("type") == "opa":
        policy = OPADataAPIAdapter(str(policy_config["url"]), timeout=float(policy_config.get("timeout", 2.0)))
    else:
        decision = policy_config.get("decision", "deny") == "allow"
        policy = LocalPolicyAdapter(lambda _: decision)

    store_path = Path(config.get("store", path.with_suffix(".db")))
    if not store_path.is_absolute():
        store_path = path.parent / store_path
    authority_bindings = {
        str(value["spiffe_id"]): (str(value["mission_id"]), str(value["lease_id"]))
        for value in config.get("authority_bindings", [])
    }
    return AIEGateway(
        state=state,
        store=SQLiteGatewayStore(store_path),
        policy=policy,
        clock=clock or (lambda: datetime.now(timezone.utc)),
        authority_bindings=authority_bindings,
        protocol_passthrough_on_parse_error=bool(config.get("protocol_passthrough_on_parse_error", False)),
    )


def build_server_options_from_config(config_path: str | Path) -> dict[str, Any]:
    path, config = _load_config(config_path)
    base = path.parent
    options: dict[str, Any] = {
        "ssl_context": None,
        "tls_context_provider": None,
        "forwarders": {},
        "federation_trust": set(),
        "revocation_replicator": None,
        "workload_spiffe_id": None,
        "_svid_watcher": None,
    }

    workload_server_context = None
    workload_client_context = None
    workload_tls_provider = None
    workload_config = config.get("workload_api")
    if workload_config:
        endpoint = str(workload_config.get("endpoint") or os.environ.get("SPIFFE_ENDPOINT_SOCKET") or "")
        if not endpoint:
            raise ValueError("workload_api endpoint or SPIFFE_ENDPOINT_SOCKET is required")
        workload_client = WorkloadAPIClient(endpoint)
        material = workload_client.fetch_x509_svid(
            timeout=float(workload_config.get("timeout", 5.0)),
            hint=workload_config.get("hint"),
        )
        if bool(workload_config.get("watch", False)):
            workload_tls_provider = RotatingTLSContextProvider(
                material,
                require_client_cert=bool((config.get("tls") or {}).get("require_client_cert", True)),
            )
            options["tls_context_provider"] = workload_tls_provider
            options["_svid_watcher"] = WorkloadAPISVIDWatcher(
                workload_client,
                workload_tls_provider,
                hint=workload_config.get("hint"),
                reconnect_delay=float(workload_config.get("reconnect_delay", 0.5)),
            )
        else:
            workload_server_context, workload_client_context = build_ssl_contexts_from_svid(
                material, require_client_cert=True
            )
        options["workload_spiffe_id"] = material.spiffe_id

    tls = config.get("tls")
    if tls:
        if tls.get("source") == "workload_api":
            if workload_tls_provider is not None:
                options["ssl_context"] = None
                options["tls_context_provider"] = workload_tls_provider
            elif workload_server_context is not None:
                options["ssl_context"] = workload_server_context
            else:
                raise ValueError("workload_api TLS source requires top-level workload_api configuration")
        else:
            options["ssl_context"] = build_server_ssl_context(
                certfile=_resolve(base, tls["certfile"]),
                keyfile=_resolve(base, tls["keyfile"]),
                cafile=_resolve(base, tls["cafile"]),
                require_client_cert=bool(tls.get("require_client_cert", True)),
            )

    for protocol, upstream in config.get("upstreams", {}).items():
        if protocol not in {"mcp", "a2a"}:
            raise ValueError(f"unsupported upstream protocol: {protocol}")
        upstream_tls = upstream.get("tls")
        dynamic_tls = bool(upstream_tls and upstream_tls.get("source") == "workload_api" and workload_tls_provider is not None)
        context = None if dynamic_tls else _client_tls_context(
            base, upstream_tls, workload_client_context=workload_client_context
        )
        options["forwarders"][protocol] = HTTPUpstreamForwarder(
            str(upstream["url"]),
            timeout=float(upstream.get("timeout", 5.0)),
            ssl_context=context,
            ssl_context_provider=workload_tls_provider.client_context if dynamic_tls else None,
            fixed_headers=upstream.get("headers", {}),
            expected_peer_spiffe_id=upstream.get("expected_spiffe_id"),
        )

    federation = config.get("federation") or {}
    options["federation_trust"] = set(federation.get("trusted_peers", []))
    peers = federation.get("peers", [])
    if peers:
        peer_urls = [str(peer["url"]) for peer in peers]
        expected = {
            str(peer["url"]): str(peer["expected_spiffe_id"])
            for peer in peers
            if peer.get("expected_spiffe_id")
        }
        options["revocation_replicator"] = RevocationReplicator(
            peer_urls,
            source_gateway=str(federation["source_gateway"]),
            timeout=float(federation.get("timeout", 3.0)),
            ssl_context=_client_tls_context(base, federation.get("client_tls"), workload_client_context=workload_client_context),
            expected_peer_spiffe_ids=expected,
        )
    return options


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AIE Reference Gateway v0.3")
    parser.add_argument("--config", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--admin-token-env", default="AIE_GATEWAY_ADMIN_TOKEN")
    parser.add_argument(
        "--trust-header-identity",
        action="store_true",
        help="TEST/REFERENCE ONLY: trust X-AIE-Verified-Spiffe-ID when X-AIE-Identity-Verified=true",
    )
    args = parser.parse_args(argv)

    admin_token = os.environ.get(args.admin_token_env, "")
    if not admin_token:
        parser.error(f"environment variable {args.admin_token_env} must contain an admin token")
    gateway = build_gateway_from_config(args.config)
    options = build_server_options_from_config(args.config)
    svid_watcher = options.pop("_svid_watcher", None)
    options.pop("workload_spiffe_id", None)
    server = create_http_server(
        gateway,
        host=args.host,
        port=args.port,
        admin_token=admin_token,
        trust_header_identity=args.trust_header_identity,
        **options,
    )
    if svid_watcher is not None:
        svid_watcher.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if svid_watcher is not None:
            svid_watcher.stop()
            svid_watcher.join(timeout=2.0)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
