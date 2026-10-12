"""Buendel-Tool: kompletter Asset-Datensatz in einem Call (nur lesend)."""
from __future__ import annotations

from typing import Any

from ..ksc_client import KscClient
from . import hosts as hosts_tools
from . import tags as tags_tools


async def get_host_details(
    client: KscClient,
    hostname: str,
    fields: list[str] | None = None,
    include_products: bool = True,
    include_tags: bool = True,
) -> dict[str, Any]:
    """Attribute + Produkte + Tags eines Hosts in einer Antwort buendeln."""
    # INSTANCEID nur dann mitladen, wenn der Aufrufer sie nicht selbst will —
    # sie wird danach wieder entfernt, damit die Antwort stabil bleibt.
    # Hinweis: szwHostId=KLHST_INSTANCEID ist doku-belegt, aber noch nie gegen
    # einen echten KSC verifiziert (Live-Smoke ausstehend).
    added_id = include_tags and (fields is None or "KLHST_INSTANCEID" not in fields)
    info_fields = list(fields) if fields else list(hosts_tools.DEFAULT_HOST_FIELDS)
    if added_id and "KLHST_INSTANCEID" not in info_fields:
        info_fields.append("KLHST_INSTANCEID")
    host = (await hosts_tools.get_host(client, hostname, info_fields)).get("host", {})

    products: Any = None
    if include_products:
        products = (await hosts_tools.get_host_products(client, hostname)).get("products")

    tags: Any = None
    host_id: str | None = None
    if include_tags:
        hid = host.pop("KLHST_INSTANCEID", None) if added_id else host.get("KLHST_INSTANCEID")
        if hid:
            tag_res = await tags_tools.get_host_tags(client, host_id=str(hid))
        else:
            tag_res = await tags_tools.get_host_tags(client, hostname=hostname)
        tags = tag_res.get("tags")
        host_id = tag_res.get("host_id")

    out: dict[str, Any] = {"host": host}
    if host_id:
        out["host_id"] = host_id
    if include_products:
        out["products"] = products
    if include_tags:
        out["tags"] = tags
    return out
