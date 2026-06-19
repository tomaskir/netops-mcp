"""
Tests for the canonical tool-group registry (single source of truth).
"""

from netops_mcp.tools.groups import (
    META_GROUP,
    TOGGLEABLE_GROUPS,
    TOOL_GROUPS,
    enabled_tool_names,
    group_tool,
)


class TestRegistry:
    def test_inventory_is_26_unique_tools(self):
        names = [t for g in TOOL_GROUPS.values() for t in g["tools"]]
        names += META_GROUP["tools"]
        assert len(names) == 26
        assert len(set(names)) == 26  # no tool appears in two groups

    def test_toggleable_groups_match_registry_keys(self):
        assert TOGGLEABLE_GROUPS == tuple(TOOL_GROUPS.keys())

    def test_meta_tools_are_not_a_toggleable_group(self):
        # health/check_required_tools must never be disableable.
        assert "meta" not in TOOL_GROUPS
        assert META_GROUP["tools"] == ["check_required_tools", "health"]


class _FakeMCP:
    def tool(self, *args, **kwargs):
        def deco(func):
            func._registered = True
            return func
        return deco


class TestGroupTool:
    def test_enabled_returns_real_decorator(self):
        mcp = _FakeMCP()
        deco = group_tool(mcp, True)

        @deco(description="x")
        def f():
            return 1

        assert getattr(f, "_registered", False) is True

    def test_disabled_returns_noop_decorator(self):
        mcp = _FakeMCP()
        deco = group_tool(mcp, False)

        @deco(description="x")
        def f():
            return 1

        # Function is left untouched and never registered.
        assert getattr(f, "_registered", False) is False
        assert f() == 1


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
        # Meta tools survive regardless.
        assert "health" in names
        assert "check_required_tools" in names
