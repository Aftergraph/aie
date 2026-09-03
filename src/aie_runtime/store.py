from dataclasses import dataclass, field
from typing import Any


@dataclass
class InMemoryState:
    principals: dict[str, Any] = field(default_factory=dict)
    missions: dict[str, Any] = field(default_factory=dict)
    leases: dict[str, Any] = field(default_factory=dict)
    outcomes: dict[str, Any] = field(default_factory=dict)
    evidence: list[Any] = field(default_factory=list)
