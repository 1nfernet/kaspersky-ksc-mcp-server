"""Server-Status-Tools (nur lesend)."""
from __future__ import annotations

from typing import Any

from ..ksc_client import KscClient, decode_value


async def server_status(client: KscClient) -> dict[str, Any]:
    static = await client.call("HostGroup.GetStaticInfo", {"pValues": []})
    instance = await client.call("HostGroup.GetInstanceStatistics", {"vecFilterFields": []})
    runtime = await client.call("HostGroup.GetRunTimeInfo", {"pValues": []})
    return {
        "static": decode_value(static.get("PxgRetVal", {})),
        "instance_statistics": decode_value(instance.get("PxgRetVal", {})),
        "runtime": decode_value(runtime.get("PxgRetVal", {})),
    }
