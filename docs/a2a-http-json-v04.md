# AIE v0.4 A2A HTTP+JSON transport

This transport composes AIE admission with the A2A 1.0 HTTP+JSON binding without translating the upstream wire request into JSON-RPC. A temporary internal admission envelope is used only for authority/policy/budget/evidence resolution; the original HTTP method, path, query, headers and body are forwarded upstream.

Implemented operations:

- `POST /message:send`
- `POST /message:stream` using SSE
- `GET /tasks`
- `GET /tasks/{id}`
- `POST /tasks/{id}:cancel`
- `POST /tasks/{id}:subscribe` using SSE

Tenant-prefixed paths are supported when a single tenant is configured. Tenant identity is included in the AIE resource URI, so equal task/message IDs in different tenants do not share authority scope.

Streaming semantics are conservative: the AIE outcome is not committed until the upstream stream terminates. If the downstream peer closes after dispatch, the action becomes terminal `uncertain` with `AIE-UPSTREAM-002`; the gateway does not blindly replay it.

TLS may use static certificate files or the SPIFFE Workload API. With `workload_api.watch=true`, new inbound and outbound connections use atomically rotated TLS context snapshots without restarting the process.

Still outside this slice: gRPC binding, push-notification configuration resources, extended Agent Card endpoint, and external official A2A TCK promotion evidence. S2 remains blocked by the canonical S1.2 external promotion gate.
