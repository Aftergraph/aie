# GitHub-hosted runner blocker

The repository accepted workflow-triggering events and created workflow runs, but the observed jobs terminated before runner allocation. The affected jobs reported `runner_id: 0` and no executed steps, including a reduced read-only verification workflow.

Observed run IDs:

- `33710282268`
- `33710353516`
- `33710465235`

This evidence is classified as an **execution-environment blocker**, not an AIE conformance failure and not an interoperability pass. S1.2 remains `BLOCKED_EXTERNAL_RUNTIME` until a runner actually executes the live SPIRE + official MCP gate.
