"""Task-Tools (nur lesend)."""
from __future__ import annotations

import logging
from typing import Any

from ..iterators import DEFAULT_LIFETIME, fetch_via_event_processing, fetch_via_task_list
from ..ksc_client import KscClient, decode_value

log = logging.getLogger(__name__)

# Alle Bits aus "Bitmasks of host task states" (a00179):
# 0x01 Pending, 0x02 Running, 0x04 OK, 0x08 Warning, 0x10 Failed,
# 0x20 Scheduled, 0x40 Paused
ALL_HOST_STATES = 0x7F

DEFAULT_TASK_STATUS_FIELDS = [
    "domain_name", "hostname", "hostdn", "state_code",
    "try_count", "state_descr", "start_time", "finish_time",
    "completed_percent", "src_event_id",
]

DEFAULT_HISTORY_FIELDS = [
    "event_db_id", "event_type", "event_type_display_name",
    "task_new_state", "task_old_state",
    "rise_time", "registration_time",
    "hostname", "hostdn",
    "GNRL_EA_SEVERITY", "GNRL_EA_DESCRIPTION",
]


async def list_tasks(
    client: KscClient,
    group_id: int = 0,
    group_significant: bool = True,
    product: str = "",
    version: str = "",
    component: str = "",
    instance: str = "",
    task_name: str = "",
    include_supergroups: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    return await fetch_via_task_list(
        client,
        {
            "nGroupId": int(group_id),
            "bGroupIdSignificant": bool(group_significant),
            "strProductName": product or "",
            "strVersion": version or "",
            "strComponentName": component or "",
            "strInstanceId": instance or "",
            "strTaskName": task_name or "",
            "bIncludeSupergroups": bool(include_supergroups),
        },
        limit=limit,
        offset=offset,
    )


async def get_task(client: KscClient, task_id: str) -> dict[str, Any]:
    attrs = await client.call("Tasks.GetTask", {"strTask": str(task_id)})
    data = await client.call("Tasks.GetTaskData", {"strTask": str(task_id)})
    start_event = await client.call("Tasks.GetTaskStartEvent", {"strTask": str(task_id)})
    return {
        "attributes": decode_value(attrs.get("PxgRetVal", {})),
        "settings": decode_value(data.get("PxgRetVal", {})),
        "start_event": decode_value(start_event.get("PxgRetVal", {})),
    }


async def get_task_statistics(client: KscClient, task_id: str) -> dict[str, Any]:
    res = await client.call("Tasks.GetTaskStatistics2", {"strTask": str(task_id)})
    return {"statistics": decode_value(res.get("PxgRetVal", {}))}


async def get_task_host_status(
    client: KscClient,
    task_id: str,
    fields: list[str] | None = None,
    order: list[str] | None = None,
    state_mask: int = ALL_HOST_STATES,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(limit, 5000))
    offset = max(0, offset)
    res = await client.call("Tasks.ResetHostIteratorForTaskStatusEx", {
        "strTask": str(task_id),
        "pFields2Return": fields or DEFAULT_TASK_STATUS_FIELDS,
        "pFields2Order": order or [],
        "nHostStateMask": int(state_mask),
        "nLifetime": DEFAULT_LIFETIME,
    })
    iterator_id = str(res.get("strHostIteratorId", ""))
    if not iterator_id:
        return {"total": 0, "items": [], "offset": offset, "limit": limit}
    try:
        cnt = await client.call(
            "Tasks.GetHostStatusRecordsCount", {"strHostIteratorId": iterator_id})
        total = int(cnt.get("PxgRetVal", 0) or 0)
        if total <= 0 or offset >= total:
            return {"total": total, "items": [], "offset": offset, "limit": limit}
        end = min(offset + limit, total)
        rng = await client.call("Tasks.GetHostStatusRecordRange", {
            "strHostIteratorId": iterator_id, "nStart": offset, "nEnd": end,
        })
        items = decode_value(rng.get("pParHostStatus", {}))
        if isinstance(items, dict):
            items = items.get("KLCSP_ITERATOR_ARRAY", [])
        return {"total": total, "items": items, "offset": offset, "limit": limit}
    finally:
        try:
            await client.call(
                "Tasks.ReleaseHostStatusIterator", {"strHostIteratorId": iterator_id})
        except Exception:
            log.debug("Tasks.ReleaseHostStatusIterator fehlgeschlagen", exc_info=True)


async def get_task_history(
    client: KscClient,
    task_id: str,
    hostname: str = "",
    fields: list[str] | None = None,
    sort: list[dict] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    res = await client.call("Tasks.GetTaskHistory", {
        "strTask": str(task_id),
        "pFields2Return": fields or DEFAULT_HISTORY_FIELDS,
        "pSortFields": sort or [],
        "strHostName": hostname or "",
        "pFilter": {},
    })
    iterator_id = str(res.get("strIteratorId", ""))
    if not iterator_id:
        return {"total": 0, "items": [], "offset": offset, "limit": limit}
    return await fetch_via_event_processing(client, iterator_id, limit, offset)


async def get_tasks_of_host(client: KscClient, domain: str, hostname: str) -> dict[str, Any]:
    res = await client.call("Tasks.GetAllTasksOfHost", {
        "strDomainName": domain or "",
        "strHostName": hostname,
    })
    return {"tasks": decode_value(res.get("PxgRetVal", []))}
