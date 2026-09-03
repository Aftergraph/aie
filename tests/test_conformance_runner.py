from pathlib import Path

from aie_runtime.conformance import run_suite


def test_conformance_suite_produces_same_outcomes_for_both_runtimes():
    vectors = Path(__file__).parent.parent / "conformance" / "vectors.yaml"
    report = run_suite(vectors, runtimes=("object", "functional"))
    assert report["summary"]["failed"] == 0
    assert report["summary"]["passed"] >= 10
    assert {r["runtime"] for r in report["results"]} == {"object", "functional"}


def test_conformance_suite_covers_delegation_and_revocation_for_both_runtimes():
    vectors = Path(__file__).parent.parent / "conformance" / "vectors.yaml"
    report = run_suite(vectors, runtimes=("object", "functional"))
    required = {"D1-ATTEN-001", "D1-DEPTH-002", "D1-BUDGET-003", "D1-REVOKE-004"}
    for runtime in {"object", "functional"}:
        seen = {r["vector"] for r in report["results"] if r["runtime"] == runtime and r["passed"]}
        assert required.issubset(seen)
