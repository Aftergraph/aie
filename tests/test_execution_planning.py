import pytest

from aie_runtime.execution_planning import compile_execution_policy_request


def test_compiles_policy_request_without_executor_selection():
    request = compile_execution_policy_request(
        mission_id="mis_1",
        mission_node_id="node_1",
        authority_ref="grant://1",
        environment="windows",
        effect_class="reversible",
        capability="computer.click",
        uncertainty=0.04,
        structured_state_available=True,
        vision_available=False,
        semantic_reasoning_required=False,
        latency_budget_ms=20,
    )
    payload = request.to_dict()
    assert payload["schema"] == "aftergraph.execution-policy-request/v1"
    assert "executor" not in payload
    assert payload["authority_ref"] == "grant://1"


@pytest.mark.parametrize("uncertainty", [-0.1, 1.1])
def test_rejects_invalid_uncertainty(uncertainty):
    with pytest.raises(ValueError, match="uncertainty"):
        compile_execution_policy_request(
            mission_id="mis_1",
            mission_node_id="node_1",
            authority_ref="grant://1",
            environment="windows",
            effect_class="read",
            capability="computer.inspect",
            uncertainty=uncertainty,
            structured_state_available=True,
            vision_available=False,
            semantic_reasoning_required=False,
        )
