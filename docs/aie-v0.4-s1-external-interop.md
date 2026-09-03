# AIE v0.4-S1 External Interoperability

S1 asks a deliberately narrow question: can AIE sit between an official MCP client and server without changing valid protocol semantics, while still enforcing institutional authority when required?

The external harness measures three legs:

1. direct official MCP conformance → MCP server;
2. official MCP conformance → SPIFFE bridge → MCP server;
3. official MCP conformance → SPIFFE bridge → AIE gateway → SPIFFE bridge → MCP server.

Promotion requires the frozen MCP `2026-07-28` requirement set to pass on all three legs with identical check-ID sets. Local unit/integration tests do not satisfy this gate.
