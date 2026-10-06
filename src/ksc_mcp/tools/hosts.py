"""Hosts- & Gruppen-Tools (nur lesend)."""
from __future__ import annotations

from typing import Any

from ..iterators import DEFAULT_LIFETIME, fetch_via_chunk_accessor
from ..ksc_client import KscClient, decode_value

DEFAULT_GROUP_FIELDS = ["id", "name", "grp_full_name", "parentId", "level"]
DEFAULT_HOST_FIELDS = [
    "KLHST_WKS_HOSTNAME", "KLHST_WKS_FQDN", "KLHST_WKS_IP",
    "KLHST_WKS_OS_NAME", "KLHST_WKS_OS_VER",
    "KLHST_LAST_VISIBLE", "KLHST_WKS_STATUS",
]


async def list_groups(
    client: KscClient,
    group_filter: str = "",
    fields: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    res = await fetch_via_chunk_accessor(
        client,
        "HostGroup.FindGroups",
        {
            "wstrFilter": group_filter or "",
            "vecFieldsToReturn": fields or DEFAULT_GROUP_FIELDS,
            "vecFieldsToOrder": [],
            "pParams": {"KLGRP_FIND_FROM_CUR_VS_ONLY": True},
            "lMaxLifeTime": DEFAULT_LIFETIME,
        },
        limit=limit,
        offset=offset,
    )
    return res


async def get_group(client: KscClient, group_id: int) -> dict[str, Any]:
    info = await client.call("HostGroup.GetGroupInfo", {"nGroupId": int(group_id)})
    subs = await client.call("HostGroup.GetSubgroups", {"nGroupId": int(group_id), "nDepth": 1})
    return {
        "info": decode_value(info.get("PxgRetVal", info)),
        "subgroups": decode_value(subs.get("PxgRetVal", [])),
    }


async def find_hosts(
    client: KscClient,
    host_filter: str = "",
    fields: list[str] | None = None,
    order: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    return await fetch_via_chunk_accessor(
        client,
        "HostGroup.FindHosts",
        {
            "wstrFilter": host_filter or "",
            "vecFieldsToReturn": fields or DEFAULT_HOST_FIELDS,
            "vecFieldsToOrder": order or [],
            "pParams": {},
            "lMaxLifeTime": DEFAULT_LIFETIME,
        },
        limit=limit,
        offset=offset,
    )


async def get_host(client: KscClient, hostname: str, fields: list[str] | None = None) -> dict[str, Any]:
    res = await client.call("HostGroup.GetHostInfo", {
        "strHostName": hostname,
        "pFields2Return": fields or DEFAULT_HOST_FIELDS,
    })
    return {"host": decode_value(res.get("PxgRetVal", {}))}


async def get_host_products(client: KscClient, hostname: str) -> dict[str, Any]:
    res = await client.call("HostGroup.GetHostProducts", {"strHostName": hostname})
    return {"products": decode_value(res.get("PxgRetVal", {}))}
