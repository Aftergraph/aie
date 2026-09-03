# Gateway standards basis

The AIE reference gateway composes with existing protocol and trust layers rather than replacing them.

- MCP: tool/data protocol surface.
- A2A: agent-to-agent task/message surface.
- SPIFFE/X.509-SVID: workload identity and trust-domain semantics.
- OPA/Cedar: policy evaluation candidates.
- OpenTelemetry: trace/evidence correlation.

AIE remains wire-format neutral at the semantic layer: it resolves principal, mission, authority, capability, resource, budget, revocation, policy, and evidence obligations before a consequential action is admitted.
