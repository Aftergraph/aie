from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Protocol

from aie_runtime.errors import AIEError


class PolicyAdapter(Protocol):
    def evaluate(self, decision_input: dict[str, Any]) -> bool: ...


class LocalPolicyAdapter:
    def __init__(self, fn: Callable[[dict[str, Any]], bool]):
        self.fn = fn

    def evaluate(self, decision_input: dict[str, Any]) -> bool:
        try:
            return bool(self.fn(decision_input))
        except Exception as exc:
            raise AIEError("AIE-POLICY-002") from exc


def _default_http_post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class OPADataAPIAdapter:
    def __init__(
        self,
        url: str,
        *,
        timeout: float = 2.0,
        http_post: Callable[[str, dict[str, Any], float], dict[str, Any]] | None = None,
    ):
        self.url = url
        self.timeout = timeout
        self.http_post = http_post or _default_http_post

    def evaluate(self, decision_input: dict[str, Any]) -> bool:
        try:
            payload = self.http_post(self.url, {"input": decision_input}, self.timeout)
            result = payload["result"]
            if isinstance(result, bool):
                return result
            if isinstance(result, dict) and isinstance(result.get("allow"), bool):
                return result["allow"]
        except AIEError:
            raise
        except Exception as exc:
            raise AIEError("AIE-POLICY-002") from exc
        raise AIEError("AIE-POLICY-002")
