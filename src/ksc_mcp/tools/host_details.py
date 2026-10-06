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
    host = await hosts_tools.get_host(client, hostname, fields)

    products: Any = None
    if include_products:
        products = (await hosts_tools.get_host_products(client, hostname)).get("products")

    tags: Any = None
    host_id: str | None = None
    if include_tags:
        tag_res = await tags_tools.get_host_tags(client, hostname=hostname)
        tags = tag_res.get("tags")
        host_id = tag_res.get("host_id")

    out: dict[str, Any] = {"host": host.get("host")}
    if host_id:
        out["host_id"] = host_id
    if include_products:
        out["products"] = products
    if include_tags:
        out["tags"] = tags
    return out
