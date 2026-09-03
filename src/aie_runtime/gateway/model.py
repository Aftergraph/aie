from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ProtocolError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NormalizedAction:
    protocol: str
    protocol_version: str
    action_id: str
    capability: str
    resource: str
    operation: str
    subject_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class GatewayDecision:
    status: str
    action_id: str
    protocol: str
    error_code: str | None = None
    prior: bool = False
