"""Schlanker KSC OpenAPI-Client ohne KlAkOAPI-Abhängigkeit.

Protokoll: POST https://host:13299/api/v1.0/<Class>.<Method> mit JSON-Body.
Auth: Session.StartSession -> X-KSC-Session Header für Folge-Calls.
Typen: paramLong/datetime/date/binary/float/double als {"type":..,"value":..}.
"""
from __future__ import annotations

import base64
import logging
import re
import secrets
from datetime import date, datetime
from typing import Any

import httpx

from .config import KscConfig

log = logging.getLogger(__name__)

_METHOD_RE = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){1,2}$")

# --- Read-only Allowlist: nur lesende / aufzählende Methoden ---
# Blockt alle Add/Update/Delete/Move/Run/Suspend/Set/Write/Import/Zero-Gegenstücke.
_ALLOWED_EXACT = frozenset({
    "Session.StartSession",
    "Session.EndSession",
    # HostGroup (lesend)
    "HostGroup.FindHosts",
    "HostGroup.FindHostsAsync",
    "HostGroup.FindHostsAsyncGetAccessor",
    "HostGroup.GetHostInfo",
    "HostGroup.GetHostProducts",
    "HostGroup.GetComponentsForProductOnHost",
    "HostGroup.GetHostfixesForProductOnHost",
    "HostGroup.GetAllHostfixes",
    "HostGroup.FindGroups",
    "HostGroup.GetGroupInfo",
    "HostGroup.GetGroupInfoEx",
    "HostGroup.GetSubgroups",
    "HostGroup.GetGroupId",
    "HostGroup.GroupIdGroups",
    "HostGroup.GroupIdUnassigned",
    "HostGroup.GroupIdSuper",
    "HostGroup.GetDomains",
    "HostGroup.GetDomainHosts",
    "HostGroup.GetStaticInfo",
    "HostGroup.GetInstanceStatistics",
    "HostGroup.GetRunTimeInfo",
    "HostGroup.FindUsers",
    "HostGroup.FindIncidents",
    "HostGroup.GetHostTasks",
    "HostGroup.SS_Read",
    "HostGroup.SS_GetNames",
    # Iteratoren
    "SrvView.ResetIterator",
    "SrvView.ResetIteratorAsync",
    "SrvView.ResetIteratorAsyncGetData",
    "SrvView.GetRecordCount",
    "SrvView.GetRecordRange",
    "SrvView.ReleaseIterator",
    "ChunkAccessor.GetItemsCount",
    "ChunkAccessor.GetItemsChunk",
    "ChunkAccessor.Release",
    # Tasks / Policies (lesend, für Phase 2 vorbereitet)
    "Tasks.GetTask",
    "Tasks.GetTaskData",
    "Tasks.GetTaskStatistics2",
    "Tasks.GetTaskHistory",
    "Tasks.GetTaskStartEvent",
    "Tasks.ResetTasksIterator",
    "Tasks.GetNextTask",
    "Tasks.ReleaseTasksIterator",
    "Tasks.ResetHostIteratorForTaskStatus",
    "Tasks.ResetHostIteratorForTaskStatusEx",
    "Tasks.GetHostStatusRecordsCount",
    "Tasks.GetHostStatusRecordRange",
    "Tasks.GetNextHostStatus",
    "Tasks.ReleaseHostStatusIterator",
    "Tasks.GetAllTasksOfHost",
    "Tasks.GetTaskGroup",
    "Tasks.ResolveTaskId",
    "Policy.GetPolicyData",
    "Policy.GetPoliciesForGroup",
    "Policy.GetEffectivePoliciesForGroup",
    "Policy.GetOutbreakPolicies",
    "Policy.GetPolicyContents",
    # Tags (lesend)
    "HostTagsApi.GetHostTags",
    "ListTags.GetTags",
    "ListTags.GetAllTags",
    # Events: Task-Historie wird ueber EventProcessing-Iteratoren gelesen
    "EventProcessing.GetRecordCount",
    "EventProcessing.GetRecordRange",
    "EventProcessing.ReleaseIterator",
    # Freie Event-Abfragen (nur lesend, keine Deletes)
    "EventProcessingFactory.CreateEventProcessing",
    "EventProcessingFactory.CreateEventProcessing2",
    "EventProcessingFactory.CreateEventProcessingForHost",
    "EventProcessingFactory.CreateEventProcessingForHost2",
})

_ALLOWED_PREFIXES = (
    "HostGroup.Get",
    "HostGroup.Find",
    "HostGroup.GroupId",
    "SrvView.Get",
    "SrvView.Reset",
    "ChunkAccessor.Get",
    "Tasks.Get",
    "Policy.Get",
    "HostTagsApi.Get",
    "ListTags.Get",
    "EventProcessing.Get",
    "EventProcessing.Release",
    "EventProcessingFactory.Create",
)

# ListTags ist instanzgebunden (z.B. "HostsTags.ListTags.GetAllTags").
# Der Instanz-Prefix wird für die Allowlist-Prüfung abgestreift.
_TAG_INSTANCES = frozenset({"HostsTags"})


def _strip_instance(method: str) -> str:
    parts = method.split(".")
    if len(parts) == 3 and parts[0] in _TAG_INSTANCES:
        return f"{parts[1]}.{parts[2]}"
    return method


def is_read_only_method(method: str) -> bool:
    base = _strip_instance(method)
    if base in _ALLOWED_EXACT:
        return True
    return any(base.startswith(p) for p in _ALLOWED_PREFIXES)


class KscError(Exception):
    def __init__(self, code: Any = None, module: str = "", message: str = "",
                 file: str = "", line: Any = None, raw: Any = None):
        super().__init__(f"KSC-Fehler {code} [{module}]: {message}")
        self.code = code
        self.module = module
        self.message = message
        self.file = file
        self.line = line
        self.raw = raw


# --- KLOAPI-Typ-Helper ---
def kl_long(v: int) -> dict:
    return {"type": "long", "value": int(v)}


def kl_datetime(v: datetime | str) -> dict:
    s = v.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(v, datetime) else v
    return {"type": "datetime", "value": s}


def kl_date(v: date | str) -> dict:
    s = v.isoformat() if isinstance(v, (date, datetime)) else v
    return {"type": "date", "value": s}


def kl_binary(v: bytes) -> dict:
    return {"type": "binary", "value": base64.b64encode(v).decode("ascii")}


def kl_float(v: float) -> dict:
    return {"type": "float", "value": float(v)}


def kl_double(v: float) -> dict:
    return {"type": "double", "value": float(v)}


def kl_params(d: dict) -> dict:
    return {"type": "params", "value": dict(d)}


def decode_value(v: Any) -> Any:
    """Dekodiert {"type":..,"value":..}-Wrapper rekursiv, inkl. Iterator-Arrays."""
    if isinstance(v, list):
        return [decode_value(x) for x in v]
    if isinstance(v, dict):
        if set(v.keys()) == {"type", "value"} and isinstance(v.get("type"), str):
            t, val = v["type"], v["value"]
            if t == "params" and isinstance(val, dict):
                return {k: decode_value(x) for k, x in val.items()}
            if t == "params" and val is None:
                return {}
            if t in ("long", "datetime", "date", "binary", "float", "double"):
                return val
            # paramArray u.ä.: Liste dekodieren
            if isinstance(val, (list, dict)):
                return decode_value(val)
            return val
        out: dict[str, Any] = {}
        for k, x in v.items():
            if k == "KLCSP_ITERATOR_ARRAY" and isinstance(x, list):
                out[k] = [decode_value(e) for e in x]
            else:
                out[k] = decode_value(x)
        return out
    return v


def _request_id() -> str:
    return f"{secrets.token_hex(8).upper()}_{secrets.token_hex(8).upper()}"


class KscClient:
    """Async KSC-Client mit Session-Caching und Read-Only-Guard."""

    def __init__(self, config: KscConfig, http: httpx.AsyncClient | None = None):
        self.config = config
        self._http = http
        self._own_http = http is None
        self._session_id: str | None = None

    async def _http_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                verify=self.config.verify,
                timeout=self.config.timeout,
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and self._own_http:
            await self._http.aclose()
            self._http = None

    def _headers(self, *, with_session: bool, for_login: bool = False) -> dict[str, str]:
        h: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "X-KSC-RequestId": _request_id(),
        }
        if for_login:
            h["Authorization"] = self.config.auth_header()
        elif with_session and self._session_id:
            h["X-KSC-Session"] = self._session_id
        vs = self.config.vserver_header()
        if vs:
            h["X-KSC-VServer"] = vs
        return h

    async def login(self) -> str:
        http = await self._http_client()
        url = f"{self.config.base_url}/api/v1.0/Session.StartSession"
        r = await http.post(url, headers=self._headers(with_session=False, for_login=True), json={})
        if r.status_code in (401, 403):
            raise KscError(code=r.status_code, module="HTTP", message=f"Auth fehlgeschlagen ({r.status_code})")
        r.raise_for_status()
        body = r.json() if r.content else {}
        if "PxgError" in body:
            e = body["PxgError"]
            raise KscError(e.get("code"), e.get("module", ""), e.get("message", ""),
                           e.get("file", ""), e.get("line"), body)
        sid = body.get("PxgRetVal")
        if not sid:
            raise KscError(message="StartSession lieferte keine Session-ID", raw=body)
        self._session_id = str(sid)
        return self._session_id

    async def logout(self) -> None:
        if not self._session_id:
            return
        try:
            http = await self._http_client()
            url = f"{self.config.base_url}/api/v1.0/Session.EndSession"
            await http.post(url, headers=self._headers(with_session=True), json={})
        except Exception:
            log.debug("EndSession fehlgeschlagen", exc_info=True)
        finally:
            self._session_id = None

    async def call(self, method: str, params: dict | None = None) -> dict[str, Any]:
        """Ruft eine KSC-Methode auf. Nur Allowlist-Methoden erlaubt."""
        if not _METHOD_RE.match(method):
            raise KscError(message=f"Ungueltiger Methodenname: {method!r}")
        if not is_read_only_method(method):
            raise KscError(message=f"Schreibende Methode blockiert (read-only): {method}")
        # Session-Lifecycle laeuft immer ueber login()/logout(), damit der
        # Authorization-Header garantiert gesetzt ist (call() setzt ihn nie).
        if method == "Session.StartSession":
            return {"PxgRetVal": await self.login()}
        if method == "Session.EndSession":
            await self.logout()
            return {}
        http = await self._http_client()
        if not self._session_id:
            await self.login()
        url = f"{self.config.base_url}/api/v1.0/{method}"
        body = params or {}

        async def _post() -> httpx.Response:
            return await http.post(url, headers=self._headers(with_session=True), json=body)

        r = await _post()
        if r.status_code in (401, 403):
            # Session abgelaufen -> einmal neu anmelden
            await self.login()
            r = await _post()
        if r.status_code != 200:
            raise KscError(code=r.status_code, module="HTTP",
                           message=f"HTTP {r.status_code}: {r.text[:500]}")
        data = r.json() if r.content else {}
        if isinstance(data, dict) and "PxgError" in data:
            e = data["PxgError"]
            raise KscError(e.get("code"), e.get("module", ""), e.get("message", ""),
                           e.get("file", ""), e.get("line"), data)
        if not isinstance(data, dict):
            return {"PxgRetVal": data}
        return data

    def retval(self, response: dict, default: Any = None) -> Any:
        return decode_value(response.get("PxgRetVal", default))

    def outpar(self, response: dict, name: str, default: Any = None) -> Any:
        return decode_value(response.get(name, default))
