from __future__ import annotations

from tests.gateway.test_gateway_core import identity, make_gateway, mcp_body, mcp_headers


def test_gateway_fails_closed_when_revocation_view_is_stale(tmp_path) -> None:
    """A worker must not admit fresh effects from a stale revocation view.

    The freshness detector is intentionally injected independently of the
    authority decision. This keeps the admission invariant testable without
    pretending that a push-only revocation channel can detect its own partition.
    """
    gateway, store = make_gateway(tmp_path)
    gateway.revocation_freshness_check = lambda: False

    decision = gateway.handle(
        "mcp",
        mcp_headers(),
        mcp_body("mcp-stale-revocation-view"),
        identity(),
    )

    assert decision.status == "denied"
    assert decision.error_code == "AIE-FRESH-001"
    assert store.remaining_budget("lease:refund") == 10.0
    assert store.reservation_state("mcp-stale-revocation-view") is None


def test_gateway_fails_closed_when_revocation_freshness_check_errors(tmp_path) -> None:
    gateway, store = make_gateway(tmp_path)

    def unavailable() -> bool:
        raise RuntimeError("freshness source unavailable")

    gateway.revocation_freshness_check = unavailable
    decision = gateway.handle(
        "mcp",
        mcp_headers(),
        mcp_body("mcp-freshness-error"),
        identity(),
    )

    assert decision.status == "denied"
    assert decision.error_code == "AIE-FRESH-001"
    assert store.remaining_budget("lease:refund") == 10.0
    assert store.reservation_state("mcp-freshness-error") is None


def test_gateway_forward_never_calls_upstream_with_stale_revocation_view(tmp_path) -> None:
    gateway, store = make_gateway(tmp_path)
    gateway.revocation_freshness_check = lambda: False

    class MustNotForward:
        def forward(self, **_kwargs):
            raise AssertionError("stale revocation view reached upstream")

    result = gateway.forward(
        "mcp",
        mcp_headers(),
        mcp_body("mcp-stale-forward"),
        identity(),
        MustNotForward(),
    )

    assert result.decision.status == "denied"
    assert result.decision.error_code == "AIE-FRESH-001"
    assert store.remaining_budget("lease:refund") == 10.0
    assert store.reservation_state("mcp-stale-forward") is None


def test_gateway_preserves_existing_authority_path_when_revocation_view_is_fresh(tmp_path) -> None:
    gateway, store = make_gateway(tmp_path)
    gateway.revocation_freshness_check = lambda: True

    decision = gateway.handle(
        "mcp",
        mcp_headers(),
        mcp_body("mcp-fresh-revocation-view"),
        identity(),
    )

    assert decision.status == "admitted"
    assert decision.error_code is None
    assert store.remaining_budget("lease:refund") == 7.0
