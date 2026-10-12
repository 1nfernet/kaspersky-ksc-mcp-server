"""Tests für Client-Calls und Pagination mit gemocktem httpx."""
from __future__ import annotations

import httpx
import pytest

from ksc_mcp.config import KscConfig
from ksc_mcp.iterators import fetch_via_chunk_accessor, fetch_via_srvview
from ksc_mcp.ksc_client import KscClient, KscError
from ksc_mcp.tools import srvview as srvview_tools


def _cfg() -> KscConfig:
    return KscConfig(host="ksc.test", user="u", password="p")


def _mock_transport(routes: dict[str, dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        payload = routes.get(method)
        if payload is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, json=payload)
    return httpx.MockTransport(handler)


async def test_call_session_start_routes_to_login():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        m = request.url.path.rsplit("/", 1)[-1]
        if m == "Session.StartSession":
            seen["auth"] = request.headers.get("Authorization", "")
            return httpx.Response(200, json={"PxgRetVal": "SID9"})
        return httpx.Response(404, text="x")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        c = KscClient(_cfg(), http=http)
        out = await c.call("Session.StartSession", {})
        assert out == {"PxgRetVal": "SID9"}
        assert c._session_id == "SID9"
        assert seen["auth"].startswith("KSCBasic")


async def test_call_session_end_clears_session():
    async with httpx.AsyncClient(
        transport=_mock_transport({"Session.EndSession": {}})
    ) as http:
        c = KscClient(_cfg(), http=http)
        c._session_id = "OLD"
        out = await c.call("Session.EndSession", {})
        assert out == {}
        assert c._session_id is None


def test_config_rejects_invalid_port_and_timeout():
    with pytest.raises(ValueError, match="KSC_PORT"):
        KscConfig.from_env({"KSC_HOST": "h", "KSC_USER": "u", "KSC_PORT": "abc"})
    with pytest.raises(ValueError, match="KSC_TIMEOUT"):
        KscConfig.from_env({"KSC_HOST": "h", "KSC_USER": "u", "KSC_TIMEOUT": "soon"})


async def test_ksc_unreachable_surfaces_without_crash():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        c = KscClient(_cfg(), http=http)
        with pytest.raises(httpx.ConnectError):
            await c.call("HostGroup.GroupIdGroups", {})


async def test_login_and_call_ok():
    routes = {
        "Session.StartSession": {"PxgRetVal": "SID123"},
        "HostGroup.GroupIdGroups": {"PxgRetVal": 1},
    }
    async with httpx.AsyncClient(transport=_mock_transport(routes)) as http:
        c = KscClient(_cfg(), http=http)
        r = await c.call("HostGroup.GroupIdGroups", {})
        assert r["PxgRetVal"] == 1
        assert c._session_id == "SID123"


async def test_pxg_error_raises():
    routes = {
        "Session.StartSession": {"PxgRetVal": "SID"},
        "HostGroup.GetHostInfo": {"PxgError": {"code": 1681, "module": "KLFT", "message": "not found"}},
    }
    async with httpx.AsyncClient(transport=_mock_transport(routes)) as http:
        c = KscClient(_cfg(), http=http)
        with pytest.raises(KscError) as e:
            await c.call("HostGroup.GetHostInfo", {"strHostName": "x"})
        assert e.value.code == 1681


async def test_write_blocked_without_http():
    c = KscClient(_cfg(), http=httpx.AsyncClient())
    with pytest.raises(KscError, match="read-only"):
        await c.call("HostGroup.AddHost", {})
    await c.aclose()


async def test_chunk_pagination_releases():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        m = request.url.path.rsplit("/", 1)[-1]
        calls.append(m)
        if m == "Session.StartSession":
            return httpx.Response(200, json={"PxgRetVal": "SID"})
        if m == "HostGroup.FindHosts":
            return httpx.Response(200, json={"PxgRetVal": 2, "strAccessor": "ACC"})
        if m == "ChunkAccessor.GetItemsCount":
            return httpx.Response(200, json={"PxgRetVal": 2})
        if m == "ChunkAccessor.GetItemsChunk":
            return httpx.Response(200, json={"pChunk": {"KLCSP_ITERATOR_ARRAY": [
                {"type": "params", "value": {"KLHST_WKS_HOSTNAME": "PC1"}},
                {"type": "params", "value": {"KLHST_WKS_HOSTNAME": "PC2"}},
            ]}})
        if m == "ChunkAccessor.Release":
            return httpx.Response(200, json={})
        return httpx.Response(404, text="x")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        c = KscClient(_cfg(), http=http)
        out = await fetch_via_chunk_accessor(c, "HostGroup.FindHosts", {"wstrFilter": ""}, limit=10, offset=0)
        assert out["total"] == 2
        assert out["items"][0]["KLHST_WKS_HOSTNAME"] == "PC1"
        assert "ChunkAccessor.Release" in calls


async def test_srvview_pagination():
    def handler(request: httpx.Request) -> httpx.Response:
        m = request.url.path.rsplit("/", 1)[-1]
        if m == "Session.StartSession":
            return httpx.Response(200, json={"PxgRetVal": "SID"})
        if m == "SrvView.ResetIterator":
            return httpx.Response(200, json={"wstrIteratorId": "IT1"})
        if m == "SrvView.GetRecordCount":
            return httpx.Response(200, json={"PxgRetVal": 1})
        if m == "SrvView.GetRecordRange":
            return httpx.Response(200, json={"pRecords": {"KLCSP_ITERATOR_ARRAY": [
                {"type": "params", "value": {"Dev_Id": 1}}]}})
        if m == "SrvView.ReleaseIterator":
            return httpx.Response(200, json={})
        return httpx.Response(404, text="x")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        c = KscClient(_cfg(), http=http)
        out = await fetch_via_srvview(c, "UmdmDevices", "", ["Dev_Id"], limit=10, offset=0)
        assert out["total"] == 1
        assert out["items"][0]["Dev_Id"] == 1


async def test_srvview_invalid_view():
    c = KscClient(_cfg(), http=httpx.AsyncClient())
    with pytest.raises(KscError):
        await srvview_tools.srvview_query(c, "böse-view!!")
    await c.aclose()
