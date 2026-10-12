"""KSC Read-Only MCP-Server (mcp-SDK, stdio + streamable-http).

Entspricht mcp-dev-env BEST-PRACTICES / AGENTS:
- MCPServer aus mcp>=2 mit vollstaendigen ToolAnnotations
- Logs nur nach stderr (stdout ist fuer JSON-RPC reserviert)
- Secrets nur via ENV, keine Defaults mit echten Werten
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import auth as auth_mod
from .config import KscConfig
from .ksc_client import KscClient, KscError
from .tools import events as events_tools
from .tools import host_details as details_tools
from .tools import hosts as hosts_tools
from .tools import policies as policies_tools
from .tools import server_info as server_tools
from .tools import srvview as srvview_tools
from .tools import tags as tags_tools
from .tools import tasks as tasks_tools

log = logging.getLogger(__name__)

mcp = MCPServer("kaspersky-ksc-readonly")

_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,  # spricht via Netzwerk mit externem KSC-Server
)

_client: KscClient | None = None
_config: KscConfig | None = None


def get_config() -> KscConfig:
    global _config
    if _config is None:
        load_dotenv()
        # Im Pro-Request-Modus kommen Credentials per Header; ENV braucht
        # dann nur Host/Port/TLS/Timeout (kein User/Token-Pflicht).
        _config = KscConfig.from_env(
            os.environ, require_auth=not auth_mod.per_request_auth_enabled()
        )
        if _config.verify is False:
            log.warning(
                "KSC_VERIFY=false — TLS-Zertifikat wird NICHT geprüft "
                "(selbstsigniertes klserver.cer erwartet)"
            )
    return _config


def get_client() -> KscClient:
    global _client
    if _client is None:
        _client = KscClient(get_config())
    return _client


class KscAuthMiddleware:
    """Reine ASGI-Middleware: legt X-KSC-*-Header pro Request in ContextVar.

    Kein SDK-Fork: wird auf die von mcp.streamable_http_app() gebaute
    Starlette-App aufgesetzt. Werte werden nie geloggt.
    """

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        raw = scope.get("headers", [])
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in raw}
        token = auth_mod.set_request_auth(headers)
        try:
            await self.app(scope, receive, send)
        finally:
            auth_mod.reset_request_auth(token)


@asynccontextmanager
async def use_client() -> Any:
    """Liefert den KSC-Client für genau diesen Call.

    - Mit Request-Headern: ephemerer Client (eigene Session, danach
      EndSession + close, kein Reuse über Nutzer hinweg).
    - Ohne Header: ENV-Singleton — außer KSC_PER_REQUEST_AUTH=1, dann
      Fail-closed mit klarer Fehlermeldung.
    """
    req_auth = auth_mod.current_request_auth()
    if req_auth is not None:
        client = KscClient(
            get_config(),
            auth_header=req_auth.authorization,
            vserver_header=req_auth.vserver,
        )
        try:
            yield client
        finally:
            try:
                await client.logout()
            finally:
                await client.aclose()
    else:
        if auth_mod.per_request_auth_enabled():
            raise KscError(
                message="Pro-Request-Auth aktiv (KSC_PER_REQUEST_AUTH=1), "
                "aber kein X-KSC-Authorization-Header im Request"
            )
        yield get_client()


@mcp.tool(
    annotations=ToolAnnotations(
        title="Administrationsgruppen auflisten",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_list_groups(
    group_filter: str = "",
    fields: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Administrationsgruppen auflisten (lesend, HostGroup.FindGroups)."""
    async with use_client() as client:
        return await hosts_tools.list_groups(client, group_filter, fields, limit, offset)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Administrationsgruppe lesen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_get_group(group_id: int) -> dict:
    """Eine Administrationsgruppe + direkte Untergruppen lesen."""
    async with use_client() as client:
        return await hosts_tools.get_group(client, group_id)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Hosts suchen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_find_hosts(
    host_filter: str = "",
    fields: list[str] | None = None,
    order: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Hosts per Filter suchen (lesend, HostGroup.FindHosts)."""
    async with use_client() as client:
        return await hosts_tools.find_hosts(client, host_filter, fields, order, limit, offset)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Host lesen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_get_host(hostname: str, fields: list[str] | None = None) -> dict:
    """Host-Attribute lesen (HostGroup.GetHostInfo)."""
    async with use_client() as client:
        return await hosts_tools.get_host(client, hostname, fields)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Host-Produkte lesen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_get_host_products(hostname: str) -> dict:
    """Installierte Produkte eines Hosts lesen."""
    async with use_client() as client:
        return await hosts_tools.get_host_products(client, hostname)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Server-Status lesen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_server_status() -> dict:
    """Server-Statistiken lesen (GetStaticInfo/GetInstanceStatistics/GetRunTimeInfo)."""
    async with use_client() as client:
        return await server_tools.server_status(client)


@mcp.tool(
    annotations=ToolAnnotations(
        title="SrvView-Abfrage",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_srvview_query(
    view: str,
    view_filter: str = "",
    fields: list[str] | None = None,
    order: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Generischer SrvView-Lesezugriff, z.B. view='UmdmDevices'. Nur lesend."""
    async with use_client() as client:
        return await srvview_tools.srvview_query(client, view, view_filter, fields, order, limit, offset)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Host-Tags lesen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_get_host_tags(hostname: str | None = None, host_id: str | None = None) -> dict:
    """Tags eines Hosts lesen (HostTagsApi.GetHostTags). hostname oder host_id (GUID) angeben."""
    async with use_client() as client:
        return await tags_tools.get_host_tags(client, hostname=hostname, host_id=host_id)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Tag-Katalog lesen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_list_tags() -> dict:
    """Alle vergebenen Tag-Werte lesen (ListTags.GetAllTags, Instanz HostsTags)."""
    async with use_client() as client:
        return await tags_tools.list_tags(client)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Host-Details lesen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_get_host_details(
    hostname: str,
    fields: list[str] | None = None,
    include_products: bool = True,
    include_tags: bool = True,
) -> dict:
    """Kompletter Asset-Datensatz: Attribute + Produkte + Tags eines Hosts in einem Call."""
    async with use_client() as client:
        return await details_tools.get_host_details(
            client, hostname, fields, include_products, include_tags
        )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Tasks auflisten",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_list_tasks(
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
) -> dict:
    """Gruppen-Tasks auflisten (lesend, Tasks.ResetTasksIterator/GetNextTask)."""
    async with use_client() as client:
        return await tasks_tools.list_tasks(
            client, group_id, group_significant, product, version,
            component, instance, task_name, include_supergroups, limit, offset,
        )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Task lesen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_get_task(task_id: str) -> dict:
    """Task-Attribute + Settings + Start-Event lesen (GetTask/GetTaskData/GetTaskStartEvent)."""
    async with use_client() as client:
        return await tasks_tools.get_task(client, task_id)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Task-Statistiken lesen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_get_task_statistics(task_id: str) -> dict:
    """Task-Statistiken lesen (Tasks.GetTaskStatistics2)."""
    async with use_client() as client:
        return await tasks_tools.get_task_statistics(client, task_id)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Task-Hoststatus lesen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_get_task_host_status(
    task_id: str,
    fields: list[str] | None = None,
    order: list[str] | None = None,
    state_mask: int = 0x7F,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Host-Ausfuehrungsstatus eines Tasks lesen (paginiert). state_mask: Bitmaske nach a00179, 0x7F = alle Zustaende."""
    async with use_client() as client:
        return await tasks_tools.get_task_host_status(
            client, task_id, fields, order, state_mask, limit, offset
        )


@mcp.tool(
    annotations=ToolAnnotations(
        title="Task-Historie lesen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_get_task_history(
    task_id: str,
    hostname: str = "",
    fields: list[str] | None = None,
    sort: list[dict] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Task-Ausfuehrungshistorie lesen (GetTaskHistory + EventProcessing, paginiert). sort: [{"Name": <attr>, "Asc": true}]."""
    async with use_client() as client:
        return await tasks_tools.get_task_history(client, task_id, hostname, fields, sort, limit, offset)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Tasks eines Hosts lesen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_get_tasks_of_host(domain: str, hostname: str) -> dict:
    """Alle Gruppen- und globalen Tasks eines Hosts lesen (Tasks.GetAllTasksOfHost)."""
    async with use_client() as client:
        return await tasks_tools.get_tasks_of_host(client, domain, hostname)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Policies auflisten",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_list_policies(group_id: int, effective: bool = False) -> dict:
    """Policies einer Gruppe lesen (effective=true: wirksame inkl. vererbter Policies)."""
    async with use_client() as client:
        return await policies_tools.list_policies(client, group_id, effective)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Policy lesen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_get_policy(policy_id: int) -> dict:
    """Policy-Daten lesen (Policy.GetPolicyData)."""
    async with use_client() as client:
        return await policies_tools.get_policy(client, policy_id)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Outbreak-Policies lesen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_get_outbreak_policies() -> dict:
    """Outbreak-Policies lesen (Policy.GetOutbreakPolicies)."""
    async with use_client() as client:
        return await policies_tools.get_outbreak_policies(client)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Events abfragen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_query_events(
    event_filter: dict | None = None,
    fields: list[str] | None = None,
    order: list[dict] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Freie Event-Abfrage mit Filter (CreateEventProcessing2, paginiert). Filter-Attribute siehe Doku a00134."""
    async with use_client() as client:
        return await events_tools.query_events(client, event_filter, fields, order, limit, offset)


@mcp.tool(
    annotations=ToolAnnotations(
        title="Host-Events abfragen",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
async def ksc_query_host_events(
    hostname: str,
    product: str = "",
    version: str = "",
    event_filter: dict | None = None,
    fields: list[str] | None = None,
    order: list[dict] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Events eines Hosts mit Filter lesen (CreateEventProcessingForHost2, paginiert)."""
    async with use_client() as client:
        return await events_tools.query_host_events(
            client, hostname, product, version, event_filter, fields, order, limit, offset
        )


# Re-export für Tests / Doku, damit _READ_ONLY nicht als ungenutzt gilt.
READ_ONLY_ANNOTATIONS = _READ_ONLY


def main() -> None:
    ap = argparse.ArgumentParser(description="Kaspersky KSC Read-Only MCP Server")
    ap.add_argument("--http", action="store_true", help="Streamable HTTP statt stdio")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    if args.http:
        import uvicorn

        app = mcp.streamable_http_app()
        app.add_middleware(KscAuthMiddleware)
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
