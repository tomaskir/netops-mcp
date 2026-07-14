"""
Canonical registry of MCP tool groups.

Single source of truth for:
  * which tool groups exist and which tools belong to each,
  * which groups configuration can enable/disable (``tool_groups``),
  * the tool inventory the HTTP ``health`` endpoint reports (derived, since the
    filter below unregisters disabled tools from the FastMCP instance).

Keep this aligned with the ``@mcp.tool`` registrations in ``tools/registry.py``
and with the ``ToolGroupsConfig`` fields; the test suite asserts they stay in
sync.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

# Ordered mapping group key -> {name, tools}. Order controls display order in
# the health inventory and the README. These seven groups are toggleable.
TOOL_GROUPS: Dict[str, Dict] = {
    "http": {
        "name": "HTTP / API Testing",
        "tools": ["curl_request", "httpie_request", "api_test"],
    },
    "connectivity": {
        "name": "Network Connectivity",
        "tools": [
            "ping_host",
            "traceroute_path",
            "mtr_monitor",
            "telnet_connect",
            "netcat_test",
        ],
    },
    "dns": {
        "name": "DNS",
        "tools": ["nslookup_query", "dig_query", "host_lookup"],
    },
    "discovery": {
        "name": "Network Discovery",
        "tools": ["nmap_scan", "service_discovery"],
    },
    "system_network": {
        "name": "System Network",
        "tools": ["ss_connections", "netstat_connections", "arp_table", "arping_host"],
    },
    "monitoring": {
        "name": "System Monitoring",
        "tools": [
            "system_status",
            "cpu_usage",
            "memory_usage",
            "disk_usage",
            "process_list",
        ],
    },
    "security": {
        "name": "Security Scanning",
        "tools": ["port_scan", "service_enumeration"],
    },
}

# Always-on diagnostic tools. Not part of TOOL_GROUPS, so they can never be
# disabled: the HTTP /health endpoint depends on the health tool being present.
META_GROUP: Dict = {
    "name": "Server / Diagnostics",
    "tools": ["check_required_tools", "health"],
}

# Group keys that configuration may toggle.
TOGGLEABLE_GROUPS: Tuple[str, ...] = tuple(TOOL_GROUPS.keys())


def enabled_tool_names(is_enabled: Callable[[str], bool]) -> List[str]:
    """Flat list of tool names for all enabled groups, in canonical order.

    ``is_enabled(group_key) -> bool`` decides each toggleable group; the
    always-on META tools are always appended.
    """
    names: List[str] = []
    for key, group in TOOL_GROUPS.items():
        if is_enabled(key):
            names.extend(group["tools"])
    names.extend(META_GROUP["tools"])
    return names


def remove_tool(mcp: Any, name: str) -> None:
    """Unregister a tool, tolerating differences between FastMCP variants.

    Standalone fastmcp (HTTP transport) exposes ``remove_tool()``. The
    SDK-bundled ``mcp.server.fastmcp.FastMCP`` (stdio) does not, so fall back to
    popping the tool manager's registry directly — the same ``_tool_manager._tools``
    structure the health endpoint counts, so the removal is reflected everywhere.
    """
    try:
        remover = getattr(mcp, "remove_tool", None)
        if callable(remover):
            remover(name)
            return
    except Exception:
        pass
    try:
        tool_mgr = getattr(mcp, "_tool_manager", None)
        tools = getattr(tool_mgr, "_tools", None)
        if isinstance(tools, dict):
            tools.pop(name, None)
    except Exception:
        pass


def _registered_count(mcp: Any) -> Optional[int]:
    tool_mgr = getattr(mcp, "_tool_manager", None)
    tools = getattr(tool_mgr, "_tools", None)
    return len(tools) if isinstance(tools, dict) else None


def apply_group_filter(
    mcp: Any, is_enabled: Callable[[str], bool], logger: Any = None
) -> Optional[int]:
    """Unregister the tools of every disabled tool group.

    Called by both servers right after ``register_tools`` registers the full
    surface. Returns the resulting registered-tool count (or ``None`` if it
    cannot be derived), so the caller can keep its reported ``tool_count`` in
    sync with what actually remains callable.
    """
    for key, group in TOOL_GROUPS.items():
        if is_enabled(key):
            continue
        for tool_name in group["tools"]:
            remove_tool(mcp, tool_name)
        if logger is not None:
            logger.info(f"Tool group '{key}' disabled; removed {len(group['tools'])} tools")
    return _registered_count(mcp)
