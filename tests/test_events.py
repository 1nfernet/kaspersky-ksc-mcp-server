"""Tests für Event-Tools (gemocktes httpx)."""
from __future__ import annotations

import httpx
import pytest

from ksc_mcp.config import KscConfig
from ksc_mcp.ksc_client import KscClient, KscError, is_read_only_method
from ksc_mcp.tools import events as events_tools


def _cfg() -> KscConfig:
    return KscConfig(host="ksc.test", user="u", password="p")


def _handler(request: httpx.Request) -> httpx.Response:
    m = request.url.path.rsplit("/", 1)[-1]
    if m == "Session.StartSession":
        return httpx.Response(200, json={"PxgRetVal": "SID"})
    if m in ("EventProcessingFactory.CreateEventProcessing2",
             "EventProcessingFactory.CreateEventProcessingForHost2"):
        return httpx.Response(200, json={"strIteratorId": "EIT"})
    if m == "EventProcessing.GetRecordCount":
        return httpx.Response(200, json={"PxgRetVal": 2})
    if m == "EventProcessing.GetRecordRange":
        import json as _json

        body = _json.loads(request.content.decode() or "{}")
        all_items = [
            {"type": "params", "value": {"event_type": "GNRL_EV_VIRUS_FOUND"}},
            {"type": "params", "value": {"event_type": "KLPRCI_TaskState"}},
        ]
        start = int(body.get("nStart", 0) or 0)
        end = int(body.get("nEnd", len(all_items)) or 0)
        return httpx.Response(
            200, json={"pParamsEvents": {"KLCSP_ITERATOR_ARRAY": all_items[start:end]}})
    if m == "EventProcessing.ReleaseIterator":
        return httpx.Response(200, json={})
    return httpx.Response(404, text="x")


def test_factory_methods_allowlisted():
    for m in ["EventProcessingFactory.CreateEventProcessing",
              "EventProcessingFactory.CreateEventProcessing2",
              "EventProcessingFactory.CreateEventProcessingForHost",
              "EventProcessingFactory.CreateEventProcessingForHost2"]:
        assert is_read_only_method(m), m


async def test_query_events():
    seen: list[str] = []

    def rec(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path.rsplit("/", 1)[-1])
        return _handler(request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(rec)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await events_tools.query_events(
            c, event_filter={"event_type": "GNRL_EV_VIRUS_FOUND"}, limit=10)
        assert out["total"] == 2
        assert out["items"][0]["event_type"] == "GNRL_EV_VIRUS_FOUND"
        assert "EventProcessingFactory.CreateEventProcessing2" in seen
        assert "EventProcessing.ReleaseIterator" in seen


async def test_query_host_events():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await events_tools.query_host_events(c, hostname="PC1", limit=1, offset=1)
        assert out["total"] == 2
        assert out["items"] == [{"event_type": "KLPRCI_TaskState"}]


async def test_event_deletes_still_blocked():
    c = KscClient(_cfg(), http=httpx.AsyncClient())
    for m in ["EventProcessing.InitiateDelete", "EventProcessing.CancelDelete"]:
        with pytest.raises(KscError):
            await c.call(m, {})
    await c.aclose()
