# Evidence contract — AIE (Agentic Institution Engineering)

AIE is a standards/conformance repository — no web UI to capture. Honest
evidence instead:

## Real conformance test evidence (2026-09-06)

- `PYTHONPATH=src python -m pytest tests/ -q --no-header -p no:cacheprovider`
  → **272 passed** (41.95s) at exact HEAD 2533f66.
- Note: without `PYTHONPATH=src`, the host resolves `aie_runtime` to a
  different checkout (`C:\Users\empir\workspace\aie`) — environment
  collision, not a repo defect. Isolated run against this repo's own `src/`
  is fully green.

Full transcript: agent workspace `v2-audit/evidence/AIE-TEST-EVIDENCE.md`.

`product-main.webp` (a technical product visual rendered from repository
architecture, **not** a UI screenshot) was removed — no UI surface exists.

Generated or edited mock UI must never be presented as evidence of
implemented behavior.
