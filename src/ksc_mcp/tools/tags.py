"""Tag-Tools (nur lesend).

Hintergrund: KSC-Tags laufen nicht über Host-Attribute, sondern über
eigene Schnittstellen:
- HostTagsApi.GetHostTags(szwHostId=GUID) -> Tags eines Hosts
- ListTags (Instanz "HostsTags").GetAllTags -> Tag-Katalog
"""
from __future__ import annotations

from typing import Any

from ..ksc_client import KscClient, KscError, decode_value

HOST_ID_FIELDS = ["KLHST_INSTANCEID", "KLHST_WKS_HOSTNAME"]


async def resolve_host_id(client: KscClient, hostname: str) -> str:
    """Ermittelt die Host-GUID (KLHST_INSTANCEID) anhand des Hostnamens."""
    res = await client.call("HostGroup.GetHostInfo", {
        "strHostName": hostname,
        "pFields2Return": HOST_ID_FIELDS,
    })
    info = decode_value(res.get("PxgRetVal", {}))
    host_id = (info.get("KLHST_INSTANCEID") or "").strip() if isinstance(info, dict) else ""
    if not host_id:
        raise KscError(message=f"Keine Host-ID (KLHST_INSTANCEID) für Host {hostname!r} gefunden")
    return host_id


async def get_host_tags(
    client: KscClient,
    hostname: str | None = None,
    host_id: str | None = None,
) -> dict[str, Any]:
    """Tags eines Hosts lesen. Entweder hostname oder host_id (GUID) angeben."""
    hid = (host_id or "").strip() if host_id else ""
    if not hid:
        if not (hostname or "").strip():
            raise KscError(message="hostname oder host_id muss angegeben werden")
        hid = await resolve_host_id(client, hostname.strip())
    res = await client.call("HostTagsApi.GetHostTags", {"szwHostId": hid})
    tags = decode_value(res.get("PxgRetVal", []))
    return {"host_id": hid, "tags": tags if isinstance(tags, list) else []}


async def list_tags(client: KscClient) -> dict[str, Any]:
    """Alle vergebenen Tag-Werte lesen (Tag-Katalog, Instanz HostsTags)."""
    res = await client.call("HostsTags.ListTags.GetAllTags", {})
    tags = decode_value(res.get("PxgRetVal", []))
    return {"tags": tags if isinstance(tags, list) else []}
