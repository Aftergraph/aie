"""AIE planning projection for Aftergraph Agent Harness execution policy.

AIE describes execution requirements after reasoning. It does not select an
executor, admit authority, or verify outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

EffectClass = Literal["read", "reversible", "consequential", "irreversible"]


@dataclass(frozen=True)
class ExecutionPolicyRequest:
    schema: str
    mission_id: str
    mission_node_id: str
    authority_ref: str
    environment: str
    effect_class: EffectClass
    capability: str
    uncertainty: float
    structured_state_available: bool
    vision_available: bool
    semantic_reasoning_required: bool
    latency_budget_ms: int | None = None
    authority_granted: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def compile_execution_policy_request(
    *,
    mission_id: str,
    mission_node_id: str,
    authority_ref: str,
    environment: str,
    effect_class: EffectClass,
    capability: str,
    uncertainty: float,
    structured_state_available: bool,
    vision_available: bool,
    semantic_reasoning_required: bool,
    latency_budget_ms: int | None = None,
) -> ExecutionPolicyRequest:
    """Compile planning facts into a runtime policy-selection request.

    The authority reference is carried as an opaque reference. This function
    never validates or grants authority; Trust Gateway admission remains
    separate and Runtime may only select an executor after admission.
    """
    if not mission_id.strip() or not mission_node_id.strip():
        raise ValueError("mission_id and mission_node_id are required")
    if not authority_ref.strip():
        raise ValueError("authority_ref is required")
    if not environment.strip() or not capability.strip():
        raise ValueError("environment and capability are required")
    if effect_class not in {"read", "reversible", "consequential", "irreversible"}:
        raise ValueError("invalid effect_class")
    if not 0.0 <= uncertainty <= 1.0:
        raise ValueError("uncertainty must be between 0 and 1")
    if latency_budget_ms is not None and latency_budget_ms <= 0:
        raise ValueError("latency_budget_ms must be positive")

    return ExecutionPolicyRequest(
        schema="aftergraph.execution-policy-request/v1",
        mission_id=mission_id,
        mission_node_id=mission_node_id,
        authority_ref=authority_ref,
        environment=environment,
        effect_class=effect_class,
        capability=capability,
        uncertainty=uncertainty,
        structured_state_available=structured_state_available,
        vision_available=vision_available,
        semantic_reasoning_required=semantic_reasoning_required,
        latency_budget_ms=latency_budget_ms,
    )
