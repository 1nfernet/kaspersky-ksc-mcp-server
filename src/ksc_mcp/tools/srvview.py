"""Generischer SrvView-Lese-Query (nur lesend, mit View-Validierung)."""
from __future__ import annotations

import re
from typing import Any

from ..iterators import fetch_via_srvview
from ..ksc_client import KscClient, KscError

_VIEW_RE = re.compile(r"^[A-Za-z0-9_]{1,128}$")

# Bekannte, häufig genutzte Views (nicht abschließend — weitere Views mit
# gleichem Namensmuster werden ebenfalls zugelassen, solange sie lesend sind).
KNOWN_VIEWS = frozenset({
    "UmdmDevices",
    "Hosts",
    "Groups",
    "Tasks",
    "Policies",
    "Events",
})


def validate_view(view: str) -> str:
    if not isinstance(view, str):
        raise KscError(message=f"Ungueltiger SrvView-Name: {view!r}")
    v = view.strip()
    if not v or not _VIEW_RE.match(v):
        raise KscError(message=f"Ungueltiger SrvView-Name: {view!r}")
    return v


async def srvview_query(
    client: KscClient,
    view: str,
    view_filter: str = "",
    fields: list[str] | None = None,
    order: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    v = validate_view(view)
    return await fetch_via_srvview(client, v, view_filter, fields, order, limit, offset)
