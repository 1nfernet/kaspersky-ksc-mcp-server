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

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .config import KscConfig
from .ksc_client import KscClient
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


def get_client() -> KscClient:
    global _client
    if _client is None:
        load_dotenv()
        cfg = KscConfig.from_env(os.environ)
        if cfg.verify is False:
            log.warning(
                "KSC_VERIFY=false — TLS-Zertifikat wird NICHT geprüft "
                "(selbstsigniertes klserver.cer erwartet)"
            )
        _client = KscClient(cfg)
    return _client


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
    return await hosts_tools.list_groups(get_client(), group_filter, fields, limit, offset)


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
    return await hosts_tools.get_group(get_client(), group_id)


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
    return await hosts_tools.find_hosts(get_client(), host_filter, fields, order, limit, offset)


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
    return await hosts_tools.get_host(get_client(), hostname, fields)


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
    return await hosts_tools.get_host_products(get_client(), hostname)


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
    return await server_tools.server_status(get_client())


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
    return await srvview_tools.srvview_query(get_client(), view, view_filter, fields, order, limit, offset)


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
    return await tags_tools.get_host_tags(get_client(), hostname=hostname, host_id=host_id)


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
    return await tags_tools.list_tags(get_client())


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
    return await details_tools.get_host_details(
        get_client(), hostname, fields, include_products, include_tags
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
    return await tasks_tools.list_tasks(
        get_client(), group_id, group_significant, product, version,
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
    return await tasks_tools.get_task(get_client(), task_id)


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
    return await tasks_tools.get_task_statistics(get_client(), task_id)


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
    return await tasks_tools.get_task_host_status(
        get_client(), task_id, fields, order, state_mask, limit, offset
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
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Task-Ausfuehrungshistorie lesen (GetTaskHistory + EventProcessing, paginiert)."""
    return await tasks_tools.get_task_history(get_client(), task_id, hostname, fields, None, limit, offset)


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
    return await tasks_tools.get_tasks_of_host(get_client(), domain, hostname)


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
    return await policies_tools.list_policies(get_client(), group_id, effective)


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
    return await policies_tools.get_policy(get_client(), policy_id)


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
    return await policies_tools.get_outbreak_policies(get_client())


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
    return await events_tools.query_events(get_client(), event_filter, fields, order, limit, offset)


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
    return await events_tools.query_host_events(
        get_client(), hostname, product, version, event_filter, fields, order, limit, offset
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
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
