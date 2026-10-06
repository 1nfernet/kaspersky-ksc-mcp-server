"""Event-Tools (nur lesend).

Freie Event-Abfragen ueber EventProcessingFactory-Iteratoren, gelesen per
EventProcessing.GetRecordCount/GetRecordRange. Loeschen (InitiateDelete)
ist nicht auf der Allowlist und damit unmoeglich.
"""
from __future__ import annotations

from typing import Any

from ..iterators import DEFAULT_LIFETIME, fetch_via_event_processing
from ..ksc_client import KscClient

DEFAULT_EVENT_FIELDS = [
    "event_db_id", "event_type", "event_type_display_name",
    "task_display_name", "task_new_state", "task_old_state",
    "rise_time", "registration_time",
    "hostname", "hostdn", "domain_name", "group_name",
    "GNRL_EA_SEVERITY", "GNRL_EA_DESCRIPTION",
]


async def _consume_iterator(
    client: KscClient, iterator_id: str, limit: int, offset: int
) -> dict[str, Any]:
    if not iterator_id:
        return {"total": 0, "items": [], "offset": max(0, offset), "limit": max(1, limit)}
    return await fetch_via_event_processing(client, iterator_id, limit, offset)


async def query_events(
    client: KscClient,
    event_filter: dict | None = None,
    fields: list[str] | None = None,
    order: list[dict] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Freie Event-Abfrage mit Filter (CreateEventProcessing2)."""
    res = await client.call("EventProcessingFactory.CreateEventProcessing2", {
        "pFilter": event_filter or {},
        "vecFieldsToReturn": fields or DEFAULT_EVENT_FIELDS,
        "vecFieldsToOrder": order or [],
        "lifetimeSec": DEFAULT_LIFETIME,
    })
    return await _consume_iterator(client, str(res.get("strIteratorId", "")), limit, offset)


async def query_host_events(
    client: KscClient,
    hostname: str,
    product: str = "",
    version: str = "",
    event_filter: dict | None = None,
    fields: list[str] | None = None,
    order: list[dict] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Events eines Hosts mit Filter (CreateEventProcessingForHost2)."""
    res = await client.call("EventProcessingFactory.CreateEventProcessingForHost2", {
        "strHostName": hostname,
        "strProduct": product or "",
        "strVersion": version or "",
        "pFilter": event_filter or {},
        "vecFieldsToReturn": fields or DEFAULT_EVENT_FIELDS,
        "vecFieldsToOrder": order or [],
        "lifetimeSec": DEFAULT_LIFETIME,
    })
    return await _consume_iterator(client, str(res.get("strIteratorId", "")), limit, offset)
