"""
Tests for the tool-group feature: the canonical registry, the config model,
and the post-registration filter that unregisters disabled groups from a
FastMCP instance.
"""

import json
import tempfile
from types import SimpleNamespace

import pytest
from netops_mcp.config.loader import load_config
from netops_mcp.config.models import ToolGroupsConfig
from netops_mcp.tools.groups import (
    META_GROUP,
    TOGGLEABLE_GROUPS,
    TOOL_GROUPS,
    apply_group_filter,
    enabled_tool_names,
)
from netops_mcp.tools.registry import register_tools
from pydantic import ValidationError


class TestRegistry:
    def test_inventory_is_26_unique_tools(self):
        names = [t for g in TOOL_GROUPS.values() for t in g["tools"]]
        names += META_GROUP["tools"]
        assert len(names) == 26
        assert len(set(names)) == 26  # no tool appears in two groups

    def test_toggleable_groups_match_registry_keys(self):
        assert TOGGLEABLE_GROUPS == tuple(TOOL_GROUPS.keys())

    def test_meta_tools_are_not_a_toggleable_group(self):
        assert "meta" not in TOOL_GROUPS
        assert META_GROUP["tools"] == ["check_required_tools", "health"]

    def test_config_fields_match_group_keys(self):
        # ToolGroupsConfig must expose exactly one bool per toggleable group.
        assert set(ToolGroupsConfig.model_fields) == set(TOOL_GROUPS)


class TestEnabledToolNames:
    def test_all_enabled_lists_every_tool(self):
        names = enabled_tool_names(lambda _key: True)
        assert len(names) == 26
        assert names[-2:] == ["check_required_tools", "health"]

    def test_disabled_group_is_excluded_but_meta_kept(self):
        names = enabled_tool_names(lambda key: key != "discovery")
        assert "nmap_scan" not in names
        assert "service_discovery" not in names
        assert "curl_request" in names
        assert "health" in names and "check_required_tools" in names


class TestToolGroupsConfig:
    def test_defaults_all_enabled(self):
        cfg = ToolGroupsConfig()
        assert all(cfg.is_enabled(k) for k in TOOL_GROUPS)

    def test_is_enabled_reads_field(self):
        cfg = ToolGroupsConfig(discovery=False)
        assert cfg.is_enabled("discovery") is False
        assert cfg.is_enabled("http") is True

    def test_unknown_key_rejected(self):
        with pytest.raises(ValidationError):
            ToolGroupsConfig(does_not_exist=False)

    def test_json_config_disables_group(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"tool_groups": {"discovery": False}}, f)
            path = f.name
        cfg = load_config(path)
        assert cfg.tool_groups.is_enabled("discovery") is False
        assert cfg.tool_groups.is_enabled("http") is True


def _register(mcp_factory, is_enabled):
    """Register the full surface on a fresh FastMCP, then apply the filter."""
    mcp = mcp_factory()
    register_tools(mcp, SimpleNamespace(_tests_passed=None))
    count = apply_group_filter(mcp, is_enabled)
    registered = set(mcp._tool_manager._tools)
    return registered, count


def _factories():
    from mcp.server.fastmcp import FastMCP as SDKFastMCP  # stdio (no remove_tool)

    factories = [("stdio", lambda: SDKFastMCP("test"))]
    try:
        from fastmcp import FastMCP as StdFastMCP  # http (has remove_tool)

        factories.append(("http", lambda: StdFastMCP("test")))
    except ImportError:  # pragma: no cover
        pass
    return factories


class TestApplyGroupFilter:
    """The filter must actually unregister tools on BOTH FastMCP variants."""

    @pytest.mark.parametrize("label,factory", _factories())
    def test_all_enabled_keeps_all_26(self, label, factory):
        registered, count = _register(factory, lambda _k: True)
        assert count == 26
        assert len(registered) == 26

    @pytest.mark.parametrize("label,factory", _factories())
    def test_disabled_group_is_removed_meta_kept(self, label, factory):
        registered, count = _register(factory, lambda k: k != "discovery")
        # discovery tools gone...
        assert "nmap_scan" not in registered
        assert "service_discovery" not in registered
        # ...other groups and the always-on meta tools remain.
        assert "curl_request" in registered
        assert "health" in registered
        assert "check_required_tools" in registered
        assert count == 24

    @pytest.mark.parametrize("label,factory", _factories())
    def test_group_inventory_matches_registered_surface(self, label, factory):
        """The grouping must stay in sync with what register_tools registers.

        Guards against a future upstream pull adding/removing/renaming a tool
        without updating TOOL_GROUPS: a new tool would otherwise be silently
        ungrouped (always-on, never filterable), and a removed one would leave a
        stale group entry that _remove_tool would no-op on.
        """
        registered, _ = _register(factory, lambda _k: True)
        covered = {t for g in TOOL_GROUPS.values() for t in g["tools"]} | set(META_GROUP["tools"])
        assert registered - covered == set(), f"registered but ungrouped: {registered - covered}"
        assert covered - registered == set(), f"grouped but not registered: {covered - registered}"
