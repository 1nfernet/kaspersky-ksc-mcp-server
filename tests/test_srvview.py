"""Validation tests for the generic read-only SrvView query."""

import pytest

from ksc_mcp.ksc_client import KscError
from ksc_mcp.tools.srvview import validate_view


@pytest.mark.parametrize("view", [None, 7, "", "UmdmDevices\u03a9"])
def test_validate_view_rejects_non_string_empty_and_unicode_names(view: object) -> None:
    """Invalid tool input must consistently produce the public KscError."""
    with pytest.raises(KscError):
        validate_view(view)  # type: ignore[arg-type]
