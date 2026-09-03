# Gateway v0.3 — real trust and forwarding

v0.3 moves the gateway beyond trusted-header test mode.

- inbound HTTPS can require client certificates;
- the authenticated leaf is validated as a strict X.509-SVID workload identity;
- outbound HTTPS can pin an exact expected SPIFFE ID after CA validation;
- a Workload API client consumes `FetchX509SVID` streaming responses and materializes TLS contexts;
- admitted MCP/A2A requests are transparently forwarded;
- deterministic trust failures deny before dispatch and roll budget back;
- ambiguous post-dispatch transport failures become terminal `uncertain` and are replay protected;
- gateway federation propagates revocations over mTLS;
- OpenTelemetry decision spans inherit W3C trace context;
- evidence excludes sensitive request/response payload content by default.
