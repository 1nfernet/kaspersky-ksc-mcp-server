"""Tests für Tag-Tools und Host-Details (gemocktes httpx)."""
from __future__ import annotations

import httpx
import pytest

from ksc_mcp.config import KscConfig
from ksc_mcp.ksc_client import KscClient, KscError, is_read_only_method
from ksc_mcp.tools import host_details as details_tools
from ksc_mcp.tools import tags as tags_tools


def _cfg() -> KscConfig:
    return KscConfig(host="ksc.test", user="u", password="p")


def test_tag_methods_allowlisted():
    assert is_read_only_method("HostTagsApi.GetHostTags")
    assert is_read_only_method("ListTags.GetTags")
    assert is_read_only_method("ListTags.GetAllTags")
    # Instanz-Prefix wird abgestreift und geprueft
    assert is_read_only_method("HostsTags.ListTags.GetAllTags")
    assert is_read_only_method("HostsTags.ListTags.GetTags")


def test_tag_write_methods_blocked():
    for m in ["ListTags.AddTag", "ListTags.SetTags", "ListTags.DeleteTags2",
              "ListTags.RenameTag", "HostsTags.ListTags.AddTag"]:
        assert not is_read_only_method(m), m


async def test_invalid_method_name_blocked():
    c = KscClient(_cfg(), http=httpx.AsyncClient())
    with pytest.raises(KscError):
        await c.call("../login", {})
    await c.aclose()


def _tags_handler(request: httpx.Request) -> httpx.Response:
    m = request.url.path.rsplit("/", 1)[-1]
    if m == "Session.StartSession":
        return httpx.Response(200, json={"PxgRetVal": "SID"})
    if m == "HostGroup.GetHostInfo":
        return httpx.Response(200, json={"PxgRetVal": {
            "KLHST_INSTANCEID": "GUID-123",
            "KLHST_WKS_HOSTNAME": "PC1",
        }})
    if m == "HostTagsApi.GetHostTags":
        return httpx.Response(200, json={"PxgRetVal": [
            {"type": "params", "value": {
                "KLHST_TagValue": "Server",
                "KLHST_IS_TAG_SET_BY_PRODUCT": False,
                "KLHST_IS_TAG_SET_BY_HOSTTAGRULE": True,
            }},
        ]})
    if m == "HostsTags.ListTags.GetAllTags":
        return httpx.Response(200, json={"PxgRetVal": ["Server", "Kritisch"]})
    if m == "HostGroup.GetHostProducts":
        return httpx.Response(200, json={"PxgRetVal": {"KES": "11.0"}})
    return httpx.Response(404, text="x")


async def test_get_host_tags_via_hostname():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_tags_handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await tags_tools.get_host_tags(c, hostname="PC1")
        assert out["host_id"] == "GUID-123"
        assert out["tags"][0]["KLHST_TagValue"] == "Server"


async def test_get_host_tags_via_id_skips_lookup():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        m = request.url.path.rsplit("/", 1)[-1]
        seen.append(m)
        return _tags_handler(request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await tags_tools.get_host_tags(c, host_id="GUID-123")
        assert out["host_id"] == "GUID-123"
        assert "HostGroup.GetHostInfo" not in seen


async def test_get_host_tags_needs_identifier():
    c = KscClient(_cfg(), http=httpx.AsyncClient())
    with pytest.raises(KscError):
        await tags_tools.get_host_tags(c)
    await c.aclose()


async def test_list_tags():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_tags_handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await tags_tools.list_tags(c)
        assert out["tags"] == ["Server", "Kritisch"]


async def test_get_host_details_bundle():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_tags_handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await details_tools.get_host_details(c, "PC1")
        assert out["host"]["KLHST_WKS_HOSTNAME"] == "PC1"
        assert out["host_id"] == "GUID-123"
        assert out["products"] == {"KES": "11.0"}
        assert out["tags"][0]["KLHST_TagValue"] == "Server"


async def test_get_host_details_minimal():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_tags_handler)
    ) as http:
        c = KscClient(_cfg(), http=http)
        out = await details_tools.get_host_details(
            c, "PC1", include_products=False, include_tags=False
        )
        assert "products" not in out
        assert "tags" not in out
        assert out["host"]["KLHST_WKS_HOSTNAME"] == "PC1"
