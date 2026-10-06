"""Tests für Task-Tools (gemocktes httpx)."""
from __future__ import annotations

import httpx
import pytest

from ksc_mcp.config import KscConfig
from ksc_mcp.ksc_client import KscClient, KscError
from ksc_mcp.tools import tasks as tasks_tools


def _cfg() -> KscConfig:
    return KscConfig(host="ksc.test", user="u", password="p")


def _handler(request: httpx.Request) -> httpx.Response:
    m = request.url.path.rsplit("/", 1)[-1]
    if m == "Session.StartSession":
        return httpx.Response(200, json={"PxgRetVal": "SID"})
    if m == "Tasks.ResetTasksIterator":
        return httpx.Response(200, json={"strTaskIteratorId": "TIT"})
    if m == "Tasks.GetNextTask":
        _handler.n += 1
        if _handler.n <= 2:
            return httpx.Response(200, json={"pTaskData": {"TSK_DISPLAY_NAME": f"T{_handler.n}"}})
        return httpx.Response(200, json={"pTaskData": {}})
    if m == "Tasks.ReleaseTasksIterator":
        return httpx.Response(200, json={})
    if m == "Tasks.GetTask":
        return httpx.Response(200, json={"PxgRetVal": {"DisplayName": "T1"}})
    if m == "Tasks.GetTaskData":
        return httpx.Response(200, json={"PxgRetVal": {"settings": 1}})
    if m == "Tasks.GetTaskStartEvent":
        return httpx.Response(200, json={"PxgRetVal": {"event": "schedule"}})
    if m == "Tasks.GetTaskStatistics2":
        return httpx.Response(200, json={"PxgRetVal": {"4": 10, "16": 1}})
    if m == "Tasks.ResetHostIteratorForTaskStatusEx":
        return httpx.Response(200, json={"strHostIteratorId": "HIT"})
    if m == "Tasks.GetHostStatusRecordsCount":
        return httpx.Response(200, json={"PxgRetVal": 2})
    if m == "Tasks.GetHostStatusRecordRange":
        return httpx.Response(200, json={"pParHostStatus": {"KLCSP_ITERATOR_ARRAY": [
            {"type": "params", "value": {"hostname": "PC1", "state_code": 4}},
            {"type": "params", "value": {"hostname": "PC2", "state_code": 16}},
        ]}})
    if m == "Tasks.ReleaseHostStatusIterator":
        return httpx.Response(200, json={})
    if m == "Tasks.GetTaskHistory":
        return httpx.Response(200, json={"strIteratorId": "EIT"})
    if m == "EventProcessing.GetRecordCount":
        return httpx.Response(200, json={"PxgRetVal": 1})
    if m == "EventProcessing.GetRecordRange":
        return httpx.Response(200, json={"pParamsEvents": {"KLCSP_ITERATOR_ARRAY": [
            {"type": "params", "value": {"event_type": "KLPRCI_TaskState"}},
        ]}})
    if m == "EventProcessing.ReleaseIterator":
        return httpx.Response(200, json={})
    if m == "Tasks.GetAllTasksOfHost":
        return httpx.Response(200, json={"PxgRetVal": ["1", "2"]})
    return httpx.Response(404, text="x")


_handler.n = 0


async def test_list_tasks_pagination_and_release():
    _handler.n = 0
    seen: list[str] = []

    def rec(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path.rsplit("/", 1)[-1])
        return _handler(request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(rec)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await tasks_tools.list_tasks(c, group_id=1, limit=10, offset=0)
        assert out["total"] == 2
        assert out["truncated"] is False
        assert out["tasks"][0]["TSK_DISPLAY_NAME"] == "T1"
        assert "Tasks.ReleaseTasksIterator" in seen


async def test_list_tasks_truncated_when_capped():
    _handler.n = 0
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await tasks_tools.list_tasks(c, limit=1, offset=0)
        assert out["tasks"] == [{"TSK_DISPLAY_NAME": "T1"}]
        assert out["truncated"] is True


async def test_get_task_bundle():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await tasks_tools.get_task(c, "1")
        assert out["attributes"]["DisplayName"] == "T1"
        assert out["settings"] == {"settings": 1}
        assert out["start_event"] == {"event": "schedule"}


async def test_get_task_statistics():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await tasks_tools.get_task_statistics(c, "1")
        assert out["statistics"] == {"4": 10, "16": 1}


async def test_get_task_host_status():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await tasks_tools.get_task_host_status(c, "1", limit=10)
        assert out["total"] == 2
        assert out["items"][1] == {"hostname": "PC2", "state_code": 16}


async def test_get_task_history():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await tasks_tools.get_task_history(c, "1")
        assert out["total"] == 1
        assert out["items"][0]["event_type"] == "KLPRCI_TaskState"


async def test_get_tasks_of_host():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await tasks_tools.get_tasks_of_host(c, "DOM", "PC1")
        assert out["tasks"] == ["1", "2"]


async def test_task_write_methods_still_blocked():
    c = KscClient(_cfg(), http=httpx.AsyncClient())
    for m in ["Tasks.RunTask", "Tasks.AddTask", "Tasks.DeleteTask",
              "Tasks.SuspendTask", "Tasks.UpdateTask",
              "EventProcessing.InitiateDelete", "EventProcessing.CancelDelete"]:
        with pytest.raises(KscError):
            await c.call(m, {})
    await c.aclose()
