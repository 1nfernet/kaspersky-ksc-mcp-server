"""Tests für Config, Typ-Helper und Read-Only-Guard."""
from __future__ import annotations

import pytest

from ksc_mcp.config import KscConfig
from ksc_mcp.ksc_client import (
    decode_value,
    is_read_only_method,
    kl_binary,
    kl_datetime,
    kl_double,
    kl_float,
    kl_long,
)


def test_config_basic_auth_header():
    cfg = KscConfig(host="ksc.test", user="admin", password="pw", internal=False)
    h = cfg.auth_header()
    assert h.startswith("KSCBasic")
    assert 'internal="0"' in h


def test_config_token_has_priority():
    cfg = KscConfig(host="ksc.test", user="u", password="p", token="abc123")
    assert cfg.use_token_auth
    assert cfg.auth_header() == "KSCT abc123"


def test_config_missing_host_raises():
    with pytest.raises(ValueError):
        KscConfig.from_env({"KSC_USER": "u"})


def test_verify_parsing():
    assert KscConfig._parse_verify("false") is False
    assert KscConfig._parse_verify("0") is False
    assert KscConfig._parse_verify("true") is True
    assert KscConfig._parse_verify("/path/cer") == "/path/cer"


def test_type_helpers():
    assert kl_long(5) == {"type": "long", "value": 5}
    assert kl_datetime("2016-09-19T15:22:35Z")["type"] == "datetime"
    assert kl_float(1.5)["type"] == "float"
    assert kl_double(1.5)["type"] == "double"
    b = kl_binary(b"hi")
    assert b["type"] == "binary"
    import base64
    assert base64.b64decode(b["value"]) == b"hi"


def test_decode_nested():
    raw = {"var1": 23, "var2": {"type": "long", "value": 13},
           "var3": {"type": "params", "value": {"a": 1}}}
    assert decode_value(raw) == {"var1": 23, "var2": 13, "var3": {"a": 1}}


def test_readonly_guard_allows_reads():
    for m in ["HostGroup.FindHosts", "HostGroup.GetHostInfo", "HostGroup.GroupIdGroups",
              "SrvView.ResetIterator", "SrvView.GetRecordRange",
              "ChunkAccessor.GetItemsChunk", "Tasks.GetTask", "Policy.GetPolicyData"]:
        assert is_read_only_method(m), m


def test_readonly_guard_blocks_writes():
    for m in ["HostGroup.AddHost", "HostGroup.UpdateHost", "HostGroup.RemoveHost",
              "HostGroup.MoveHostsToGroup", "HostGroup.AddGroup", "HostGroup.RemoveGroup",
              "Tasks.RunTask", "Tasks.AddTask", "Tasks.DeleteTask",
              "Policy.AddPolicy", "Policy.UpdatePolicyData", "Policy.DeletePolicy",
              "HostGroup.SS_Write", "HostGroup.ZeroVirusCountForGroup"]:
        assert not is_read_only_method(m), m
