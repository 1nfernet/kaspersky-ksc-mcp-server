"""Tests für Policy-Tools (gemocktes httpx)."""
from __future__ import annotations

import httpx
import pytest

from ksc_mcp.config import KscConfig
from ksc_mcp.ksc_client import KscClient, KscError
from ksc_mcp.tools import policies as policies_tools


def _cfg() -> KscConfig:
    return KscConfig(host="ksc.test", user="u", password="p")


def _handler(request: httpx.Request) -> httpx.Response:
    m = request.url.path.rsplit("/", 1)[-1]
    if m == "Session.StartSession":
        return httpx.Response(200, json={"PxgRetVal": "SID"})
    if m == "Policy.GetPoliciesForGroup":
        return httpx.Response(200, json={"PxgRetVal": [10, 11]})
    if m == "Policy.GetEffectivePoliciesForGroup":
        return httpx.Response(200, json={"PxgRetVal": [10, 11, 12]})
    if m == "Policy.GetPolicyData":
        return httpx.Response(200, json={"PxgRetVal": {"POL_NAME": "Base"}})
    if m == "Policy.GetOutbreakPolicies":
        return httpx.Response(200, json={"PxgRetVal": {"policies": []}})
    return httpx.Response(404, text="x")


async def test_list_policies_direct():
    seen: list[str] = []

    def rec(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path.rsplit("/", 1)[-1])
        return _handler(request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(rec)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await policies_tools.list_policies(c, group_id=5, effective=False)
        assert out == {"policies": [10, 11]}
        assert "Policy.GetPoliciesForGroup" in seen
        assert "Policy.GetEffectivePoliciesForGroup" not in seen


async def test_list_policies_effective():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await policies_tools.list_policies(c, group_id=5, effective=True)
        assert out == {"policies": [10, 11, 12]}


async def test_get_policy():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await policies_tools.get_policy(c, 10)
        assert out == {"policy": {"POL_NAME": "Base"}}


async def test_get_outbreak_policies():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await policies_tools.get_outbreak_policies(c)
        assert out == {"policies": {"policies": []}}


async def test_policy_write_methods_still_blocked():
    c = KscClient(_cfg(), http=httpx.AsyncClient())
    for m in ["Policy.AddPolicy", "Policy.UpdatePolicyData", "Policy.DeletePolicy",
              "Policy.MakePolicyActive", "Policy.CopyOrMovePolicy"]:
        with pytest.raises(KscError):
            await c.call(m, {})
    await c.aclose()
