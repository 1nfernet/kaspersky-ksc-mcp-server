"""Tests für Pro-Request-Auth (Header -> KSC), Middleware und Isolation."""
from __future__ import annotations

import os
from unittest import mock

import httpx
import pytest

from ksc_mcp import auth as auth_mod
from ksc_mcp import server as server_mod
from ksc_mcp.auth import RequestAuth, current_request_auth, parse_auth_headers
from ksc_mcp.ksc_client import KscClient, KscError


@pytest.fixture(autouse=True)
def _clean_state():
    old_client, old_config = server_mod._client, server_mod._config
    server_mod._client, server_mod._config = None, None
    token = auth_mod._request_auth.set(None)
    with mock.patch.dict(os.environ, {"KSC_HOST": "ksc.test", "KSC_USER": "env-user",
                                       "KSC_PER_REQUEST_AUTH": "0"}, clear=False):
        yield
    auth_mod._request_auth.reset(token)
    server_mod._client, server_mod._config = old_client, old_config


def test_parse_case_insensitive_and_vserver():
    out = parse_auth_headers({"X-KSC-Authorization": 'KSCT abc', "X-Ksc-Vserver": "dnM="})
    assert out == RequestAuth(authorization="KSCT abc", vserver="dnM=")


def test_parse_missing_is_none():
    assert parse_auth_headers({}) is None
    assert parse_auth_headers({"X-KSC-Authorization": "   "}) is None


def test_parse_rejects_long_and_non_ascii():
    with pytest.raises(KscError):
        parse_auth_headers({"X-KSC-Authorization": "x" * 9000})
    with pytest.raises(KscError):
        parse_auth_headers({"X-KSC-Authorization": "KSCBäsic x"})


def test_contextvar_roundtrip_and_reset():
    tok = auth_mod.set_request_auth({"x-ksc-authorization": "KSCT abc"})
    assert current_request_auth() == RequestAuth(authorization="KSCT abc", vserver=None)
    auth_mod.reset_request_auth(tok)
    assert current_request_auth() is None


def test_malformed_header_surfaces_as_ksc_error():
    tok = auth_mod.set_request_auth({"x-ksc-authorization": "x" * 9000})
    with pytest.raises(KscError):
        current_request_auth()
    auth_mod.reset_request_auth(tok)


def test_flag_parsing():
    assert auth_mod.per_request_auth_enabled({"KSC_PER_REQUEST_AUTH": "1"}) is True
    assert auth_mod.per_request_auth_enabled({"KSC_PER_REQUEST_AUTH": "yes"}) is True
    assert auth_mod.per_request_auth_enabled({}) is False
    assert auth_mod.per_request_auth_enabled({"KSC_PER_REQUEST_AUTH": "0"}) is False


def test_builder_parity_with_config():
    from ksc_mcp.config import KscConfig, build_ksc_basic

    cases = [
        ("api-user", "S3cret!", "", False),
        ("adm", "pw", "", True),
        ("dom-user", "pw2", "CORP", False),
    ]
    for user, password, domain, internal in cases:
        cfg = KscConfig(host="h", user=user, password=password,
                        domain=domain, internal=internal)
        assert build_ksc_basic(user, password, domain, internal) == cfg.auth_header()


def test_component_headers_build_ksc_basic():
    from ksc_mcp.config import build_ksc_basic

    out = parse_auth_headers({"X-KSC-User": "api-user", "X-KSC-Password": "S3cret!"})
    assert out is not None
    assert out.authorization == build_ksc_basic("api-user", "S3cret!", "", False)
    assert out.authorization == 'KSCBasic user="YXBpLXVzZXI=", pass="UzNjcmV0IQ==", internal="0"'
    assert out.vserver is None


def test_component_headers_domain_and_internal():
    out = parse_auth_headers({"x-ksc-user": "u", "x-ksc-password": "p",
                              "x-ksc-domain": "CORP", "x-ksc-internal": "0"})
    assert out is not None
    assert 'domain="' in out.authorization and 'internal="0"' in out.authorization
    out2 = parse_auth_headers({"x-ksc-user": "u", "x-ksc-password": "p",
                               "x-ksc-domain": "CORP", "x-ksc-internal": "1"})
    assert out2 is not None
    assert "domain=" not in out2.authorization and 'internal="1"' in out2.authorization


def test_verbatim_wins_over_components():
    out = parse_auth_headers({"X-KSC-Authorization": "KSCT tok123",
                              "X-KSC-User": "u", "X-KSC-Password": "p"})
    assert out is not None
    assert out.authorization == "KSCT tok123"


def test_components_require_both_parts():
    with pytest.raises(KscError):
        parse_auth_headers({"X-KSC-User": "only-user"})
    with pytest.raises(KscError):
        parse_auth_headers({"X-KSC-Password": "only-pass"})


def test_components_reject_injection_and_non_ascii():
    with pytest.raises(KscError):
        parse_auth_headers({"X-KSC-User": "a\r\nX-Injected: 1", "X-KSC-Password": "p"})
    with pytest.raises(KscError):
        parse_auth_headers({"X-KSC-User": "Päss", "X-KSC-Password": "p"})
    with pytest.raises(KscError):
        parse_auth_headers({"X-KSC-User": "u", "X-KSC-Password": "x" * 600})


async def test_use_client_with_component_headers():
    from ksc_mcp.config import build_ksc_basic

    created: dict = {}

    class _StubClient:
        def __init__(self, config, auth_header=None, vserver_header=None, **kwargs):
            created.update(auth_header=auth_header, vserver_header=vserver_header)
            self.is_ephemeral = auth_header is not None

        async def logout(self):
            pass

        async def aclose(self):
            pass

    tok = auth_mod.set_request_auth({"x-ksc-user": "api-user",
                                     "x-ksc-password": "S3cret!"})
    try:
        with mock.patch.object(server_mod, "KscClient", _StubClient):
            async with server_mod.use_client():
                pass
        assert created["auth_header"] == build_ksc_basic("api-user", "S3cret!", "", False)
    finally:
        auth_mod.reset_request_auth(tok)


def test_config_allows_missing_user_in_per_request_mode():
    from ksc_mcp.config import KscConfig

    cfg = KscConfig.from_env({"KSC_HOST": "h"}, require_auth=False)
    assert cfg.user == "" and not cfg.use_token_auth
    with pytest.raises(ValueError, match="KSC_TOKEN noch KSC_USER"):
        KscConfig.from_env({"KSC_HOST": "h"}, require_auth=True)


async def test_ephemeral_client_uses_header_and_logs_out():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        m = request.url.path.rsplit("/", 1)[-1]
        if m == "Session.StartSession":
            seen["auth"] = request.headers.get("Authorization", "")
            return httpx.Response(200, json={"PxgRetVal": "SID"})
        if m == "Session.EndSession":
            seen["logout"] = "yes"
            assert request.headers.get("X-KSC-Session") == "SID"
            return httpx.Response(200, json={})
        if m == "HostGroup.GroupIdGroups":
            return httpx.Response(200, json={"PxgRetVal": 1})
        return httpx.Response(404, text="x")

    cfg = server_mod.get_config()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = KscClient(cfg, http=http, auth_header="KSCT header-token")
        assert client.is_ephemeral is True
        out = await client.call("HostGroup.GroupIdGroups", {})
        assert out == {"PxgRetVal": 1}
        assert seen["auth"] == "KSCT header-token"
        await client.logout()
        await client.aclose()
        assert seen.get("logout") == "yes"
        assert client._session_id is None


async def test_env_client_is_not_ephemeral():
    cfg = server_mod.get_config()
    assert KscClient(cfg, http=httpx.AsyncClient()).is_ephemeral is False


async def test_use_client_header_path_builds_ephemeral():
    created: dict = {}
    closed: list[str] = []

    class _StubClient:
        def __init__(self, config, auth_header=None, vserver_header=None, **kwargs):
            created.update(auth_header=auth_header, vserver_header=vserver_header)
            self.is_ephemeral = auth_header is not None
            self._session_id = None

        async def logout(self):
            closed.append("logout")

        async def aclose(self):
            closed.append("aclose")

    tok = auth_mod.set_request_auth({"x-ksc-authorization": "KSCT h1"})
    try:
        with mock.patch.object(server_mod, "KscClient", _StubClient):
            async with server_mod.use_client() as client:
                assert client.is_ephemeral is True
        assert created == {"auth_header": "KSCT h1", "vserver_header": None}
    finally:
        auth_mod.reset_request_auth(tok)
    assert closed == ["logout", "aclose"]


async def test_use_client_fail_closed_without_header():
    with mock.patch.dict(os.environ, {"KSC_PER_REQUEST_AUTH": "1"}), \
            pytest.raises(KscError, match="KSC_PER_REQUEST_AUTH"):
        async with server_mod.use_client():
            raise AssertionError("unreachable")


async def test_use_client_env_fallback_by_default():
    async with server_mod.use_client() as client:
        assert client.is_ephemeral is False
        assert client is server_mod.get_client()


async def test_middleware_sets_and_resets_contextvar():
    mw = server_mod.KscAuthMiddleware(app=None)

    async def fake_app(scope, receive, send):
        assert current_request_auth() == RequestAuth(authorization="KSCT m1")

    mw.app = fake_app
    scope = {"type": "http",
             "headers": [(b"x-ksc-authorization", b"KSCT m1"),
                         (b"content-type", b"application/json")]}
    await mw(scope, None, None)
    assert current_request_auth() is None  # Reset nach Request


async def test_middleware_passes_through_non_http():
    called: list[str] = []

    async def fake_app(scope, receive, send):
        called.append(scope.get("type"))

    mw = server_mod.KscAuthMiddleware(fake_app)
    await mw({"type": "websocket", "headers": []}, None, None)
    assert called == ["websocket"]
    assert current_request_auth() is None


async def test_all_tools_fail_closed_without_header():
    """Regression: jedes Tool muss durch use_client() gehen (kein Singleton-Bypass).

    Mit Flag an und ohne Header muss überall der Fail-closed-KscError kommen —
    ein direkter get_client()-Aufruf würde stattdessen am fehlenden ENV scheitern.
    """
    calls = [
        ("ksc_list_groups", ()),
        ("ksc_get_group", (1,)),
        ("ksc_find_hosts", ()),
        ("ksc_get_host", ("h",)),
        ("ksc_get_host_products", ("h",)),
        ("ksc_server_status", ()),
        ("ksc_srvview_query", ("V",)),
        ("ksc_get_host_tags", ()),
        ("ksc_list_tags", ()),
        ("ksc_get_host_details", ("h",)),
        ("ksc_list_tasks", ()),
        ("ksc_get_task", ("1",)),
        ("ksc_get_task_statistics", ("1",)),
        ("ksc_get_task_host_status", ("1",)),
        ("ksc_get_task_history", ("1",)),
        ("ksc_get_tasks_of_host", ("d", "h")),
        ("ksc_list_policies", (1,)),
        ("ksc_get_policy", (1,)),
        ("ksc_get_outbreak_policies", ()),
        ("ksc_query_events", ()),
        ("ksc_query_host_events", ("h",)),
    ]
    with mock.patch.dict(os.environ, {"KSC_PER_REQUEST_AUTH": "1",
                                         "KSC_USER": "", "KSC_TOKEN": ""}):
        for name, args in calls:
            with pytest.raises(KscError, match="KSC_PER_REQUEST_AUTH"):
                await getattr(server_mod, name)(*args)
