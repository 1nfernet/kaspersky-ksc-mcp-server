"""Policy-Tools (nur lesend).

Hinweis: Policy.GetPolicyContents liefert nur ein SsContents-Handle
(keinen Inhalt) und braucht zum Auslesen einen zweiten Schritt über
SsContents.Ss_Read/Ss_Release — deshalb bewusst kein Tool dafür;
GetPolicyData deckt den lesenden Bedarf ab.
"""
from __future__ import annotations

from typing import Any

from ..ksc_client import KscClient, decode_value


async def list_policies(client: KscClient, group_id: int, effective: bool = False) -> dict[str, Any]:
    method = "Policy.GetEffectivePoliciesForGroup" if effective else "Policy.GetPoliciesForGroup"
    res = await client.call(method, {"nGroupId": int(group_id)})
    policies = decode_value(res.get("PxgRetVal", []))
    return {"policies": policies if isinstance(policies, list) else [policies]}


async def get_policy(client: KscClient, policy_id: int) -> dict[str, Any]:
    res = await client.call("Policy.GetPolicyData", {"nPolicy": int(policy_id)})
    return {"policy": decode_value(res.get("PxgRetVal", {}))}


async def get_outbreak_policies(client: KscClient) -> dict[str, Any]:
    res = await client.call("Policy.GetOutbreakPolicies", {})
    return {"policies": decode_value(res.get("PxgRetVal", {}))}
