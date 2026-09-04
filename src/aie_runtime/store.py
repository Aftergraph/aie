from dataclasses import dataclass, field
from typing import Any


@dataclass
class InMemoryState:
    principals: dict[str, Any] = field(default_factory=dict)
    missions: dict[str, Any] = field(default_factory=dict)
    leases: dict[str, Any] = field(default_factory=dict)
    outcomes: dict[str, Any] = field(default_factory=dict)
    # ponytail: admissions tracks action_id -> ActionRequest so the executor can
    # call engine.revalidate(action_id) immediately before executing (TH-12 variant:
    # revocation/expiry between admission and execution must fail closed).
    admissions: dict[str, Any] = field(default_factory=dict)
    evidence: list[Any] = field(default_factory=list)
