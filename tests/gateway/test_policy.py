import pytest

from aie_runtime.errors import AIEError
from aie_runtime.gateway.policy import LocalPolicyAdapter, OPADataAPIAdapter


def test_local_policy_adapter_returns_boolean():
    adapter = LocalPolicyAdapter(lambda value: value["capability"] == "ok")
    assert adapter.evaluate({"capability": "ok"}) is True
    assert adapter.evaluate({"capability": "no"}) is False


def test_opa_adapter_accepts_boolean_result():
    adapter = OPADataAPIAdapter("http://opa/v1/data/aie/allow", http_post=lambda url, payload, timeout: {"result": True})
    assert adapter.evaluate({"capability": "x"}) is True


def test_opa_adapter_accepts_object_allow_result():
    adapter = OPADataAPIAdapter("http://opa/v1/data/aie", http_post=lambda url, payload, timeout: {"result": {"allow": False}})
    assert adapter.evaluate({"capability": "x"}) is False


def test_opa_adapter_fails_closed_on_backend_error():
    def broken(url, payload, timeout):
        raise OSError("down")

    adapter = OPADataAPIAdapter("http://opa/v1/data/aie", http_post=broken)
    with pytest.raises(AIEError) as exc:
        adapter.evaluate({"capability": "x"})
    assert exc.value.code == "AIE-POLICY-002"


def test_opa_adapter_fails_closed_on_unknown_shape():
    adapter = OPADataAPIAdapter("http://opa/v1/data/aie", http_post=lambda url, payload, timeout: {"result": {"decision": "maybe"}})
    with pytest.raises(AIEError) as exc:
        adapter.evaluate({"capability": "x"})
    assert exc.value.code == "AIE-POLICY-002"
