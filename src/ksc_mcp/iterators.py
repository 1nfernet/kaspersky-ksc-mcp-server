"""Pagination-Helper für ChunkAccessor- und SrvView-Iteratoren."""
from __future__ import annotations

import logging
from typing import Any

from .ksc_client import KscClient, decode_value

log = logging.getLogger(__name__)

DEFAULT_LIFETIME = 100
MAX_PAGE = 5000


async def fetch_via_chunk_accessor(
    client: KscClient,
    find_method: str,
    find_params: dict,
    accessor_field: str = "strAccessor",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Find* -> strAccessor -> GetItemsCount/GetItemsChunk/Release."""
    limit = max(1, min(limit, MAX_PAGE))
    offset = max(0, offset)
    res = await client.call(find_method, find_params)
    accessor = res.get(accessor_field)
    if not accessor:
        # manche Calls liefern direkt ohne Accessor
        return {"total": client.retval(res, 0), "items": [], "offset": offset, "limit": limit}
    accessor = str(accessor)
    try:
        cnt = await client.call("ChunkAccessor.GetItemsCount", {"strAccessor": accessor})
        total = int(cnt.get("PxgRetVal", 0) or 0)
        if total <= 0 or offset >= total:
            return {"total": total, "items": [], "offset": offset, "limit": limit}
        end = min(offset + limit, total)
        chunk = await client.call(
            "ChunkAccessor.GetItemsChunk",
            {"strAccessor": accessor, "nStart": offset, "nCount": end - offset},
        )
        raw = chunk.get("pChunk", {})
        raw = decode_value(raw)
        if isinstance(raw, dict):
            items = raw.get("KLCSP_ITERATOR_ARRAY", [])
        elif isinstance(raw, list):
            items = raw
        else:
            items = []
        return {"total": total, "items": items, "offset": offset, "limit": limit}
    finally:
        try:
            await client.call("ChunkAccessor.Release", {"strAccessor": accessor})
        except Exception:
            log.debug("ChunkAccessor.Release fehlgeschlagen", exc_info=True)


async def fetch_via_srvview(
    client: KscClient,
    view: str,
    view_filter: str = "",
    fields: list[str] | None = None,
    order: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
    lifetime: int = DEFAULT_LIFETIME,
) -> dict[str, Any]:
    """SrvView.ResetIterator -> GetRecordCount -> GetRecordRange -> Release."""
    limit = max(1, min(limit, MAX_PAGE))
    offset = max(0, offset)
    res = await client.call("SrvView.ResetIterator", {
        "wstrViewName": view,
        "wstrFilter": view_filter or "",
        "vecFieldsToReturn": fields or [],
        "vecFieldsToOrder": order or [],
        "pParams": {},
        "lifetimeSec": lifetime,
    })
    iterator_id = res.get("wstrIteratorId")
    if not iterator_id:
        return {"total": 0, "items": [], "offset": offset, "limit": limit}
    iterator_id = str(iterator_id)
    try:
        cnt = await client.call("SrvView.GetRecordCount", {"wstrIteratorId": iterator_id})
        total = int(cnt.get("PxgRetVal", 0) or 0)
        if total <= 0 or offset >= total:
            return {"total": total, "items": [], "offset": offset, "limit": limit}
        end = min(offset + limit, total)
        rng = await client.call("SrvView.GetRecordRange", {
            "wstrIteratorId": iterator_id, "nStart": offset, "nEnd": end,
        })
        records = decode_value(rng.get("pRecords", {}))
        if isinstance(records, dict):
            items = records.get("KLCSP_ITERATOR_ARRAY", [])
        elif isinstance(records, list):
            items = records
        else:
            items = []
        return {"total": total, "items": items, "offset": offset, "limit": limit}
    finally:
        try:
            await client.call("SrvView.ReleaseIterator", {"wstrIteratorId": iterator_id})
        except Exception:
            log.debug("SrvView.ReleaseIterator fehlgeschlagen", exc_info=True)


async def fetch_via_task_list(
    client: KscClient,
    reset_params: dict,
    limit: int = 50,
    offset: int = 0,
    max_scan: int = MAX_PAGE,
) -> dict[str, Any]:
    """Tasks.ResetTasksIterator -> GetNextTask-Schleife -> ReleaseTasksIterator.

    Die Schleife endet laut Doku, sobald pTaskData leer ist. Es wird nur so
    weit gelesen wie fuer offset+limit noetig (max. max_scan Eintraege).
    """
    limit = max(1, min(limit, MAX_PAGE))
    offset = max(0, offset)
    res = await client.call("Tasks.ResetTasksIterator", reset_params)
    iterator_id = res.get("strTaskIteratorId")
    if not iterator_id:
        return {"total": 0, "tasks": [], "offset": offset, "limit": limit}
    iterator_id = str(iterator_id)
    try:
        collected: list[Any] = []
        need = offset + limit
        truncated = False
        while len(collected) < min(need, max_scan):
            nxt = await client.call("Tasks.GetNextTask", {"strTaskIteratorId": iterator_id})
            data = decode_value(nxt.get("pTaskData", {}))
            if not data:
                break
            collected.append(data)
        else:
            # Schleife lief bis ans Cap -> ggf. existieren weitere Eintraege
            truncated = True
        total = len(collected)
        # Falls ohne Abbruch das Ende erreicht wurde, ist total exakt
        return {
            "total": total,
            "truncated": truncated,
            "tasks": collected[offset:offset + limit],
            "offset": offset,
            "limit": limit,
        }
    finally:
        try:
            await client.call("Tasks.ReleaseTasksIterator", {"strTaskIteratorId": iterator_id})
        except Exception:
            log.debug("Tasks.ReleaseTasksIterator fehlgeschlagen", exc_info=True)


async def fetch_via_event_processing(
    client: KscClient,
    iterator_id: str,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """EventProcessing.GetRecordCount -> GetRecordRange -> ReleaseIterator."""
    limit = max(1, min(limit, MAX_PAGE))
    offset = max(0, offset)
    try:
        cnt = await client.call("EventProcessing.GetRecordCount", {"strIteratorId": iterator_id})
        total = int(cnt.get("PxgRetVal", 0) or 0)
        if total <= 0 or offset >= total:
            return {"total": total, "items": [], "offset": offset, "limit": limit}
        end = min(offset + limit, total)
        rng = await client.call("EventProcessing.GetRecordRange", {
            "strIteratorId": iterator_id, "nStart": offset, "nEnd": end,
        })
        events = decode_value(rng.get("pParamsEvents", {}))
        if isinstance(events, dict):
            items = events.get("KLCSP_ITERATOR_ARRAY", [])
        elif isinstance(events, list):
            items = events
        else:
            items = [events] if events else []
        return {"total": total, "items": items, "offset": offset, "limit": limit}
    finally:
        try:
            await client.call("EventProcessing.ReleaseIterator", {"strIteratorId": iterator_id})
        except Exception:
            log.debug("EventProcessing.ReleaseIterator fehlgeschlagen", exc_info=True)
