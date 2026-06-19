"""
Canonical registry of MCP tool groups.

Single source of truth for:
  * which tool groups exist and which tools belong to each,
  * which groups configuration can enable/disable (``tool_groups``),
  * the tool inventory reported by the HTTP ``health()`` endpoint,
  * the feature grouping documented in the README.

Keep this aligned with the ``@mcp.tool`` registrations in ``server.py`` /
``server_http.py`` and with the ``ToolGroupsConfig`` fields; the test suite
asserts they stay in sync.
"""

from typing import Callable, Dict, List, Tuple

# Ordered mapping group key -> {name, tools}. Order controls the display order
# in the health inventory and the README. These seven groups are toggleable.
TOOL_GROUPS: Dict[str, Dict] = {
    "http": {
        "name": "HTTP / API Testing",
        "tools": ["curl_request", "httpie_request", "api_test"],
    },
    "connectivity": {
        "name": "Network Connectivity",
        "tools": [
            "ping_host", "traceroute_path", "mtr_monitor",
            "telnet_connect", "netcat_test",
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
            "system_status", "cpu_usage", "memory_usage",
            "disk_usage", "process_list",
        ],
    },
    "security": {
        "name": "Security Scanning",
        "tools": ["port_scan", "service_enumeration"],
    },
}

# Always-on diagnostic tools. Not part of TOOL_GROUPS, so they can never be
# disabled: the HTTP /health endpoint depends on health() being registered.
META_GROUP: Dict = {
    "name": "Server / Diagnostics",
    "tools": ["check_required_tools", "health"],
}

# Group keys that configuration may toggle.
TOGGLEABLE_GROUPS: Tuple[str, ...] = tuple(TOOL_GROUPS.keys())


def group_tool(mcp, enabled: bool) -> Callable:
    """Return ``mcp.tool`` when the group is enabled, else a no-op decorator.

    Lets a disabled group's ``@group_tool(...)`` registrations become inert
    without re-indenting the registration blocks.
    """
    if enabled:
        return mcp.tool

    def _noop_decorator_factory(*_args, **_kwargs):
        def _decorator(func):
            return func
        return _decorator

    return _noop_decorator_factory


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
