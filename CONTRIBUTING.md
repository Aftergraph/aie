# Contributing

Contributions are welcome, especially independent implementations and interoperability evidence.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,otel]'
pytest -q
```

## Change rules

- Write or update tests before implementation changes.
- Changes to `spec/` must describe normative impact and update conformance material where behavior changes.
- Do not weaken fail-closed authority, replay, revocation, or budget semantics merely to satisfy an upstream test.
- Do not claim external interoperability from synthetic/local tests.
- Keep protocol adapters separate from AIE authority semantics.

## Pull requests

Include: problem, scope, normative impact, verification commands/results, security/privacy impact, and compatibility notes.
