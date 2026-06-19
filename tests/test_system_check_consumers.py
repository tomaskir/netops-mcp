"""
Tests for system-info content and the HTTP diagnostic tools.

Guards two fixes: platform_version is present in get_system_info() (its absence
caused a KeyError in the startup banner / --test path), and the HTTP
check_required_tools / health tools execute without the infinite recursion the
name-shadowing bug introduced.
"""

import asyncio

from netops_mcp.server_http import NetOpsMCPHTTPServer
from netops_mcp.utils.system_check import get_system_info


def _call_tool(server, name):
    result = server.mcp.call_tool(name, {})
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    return result


class TestSystemInfo:
    def test_includes_platform_version(self):
        info = get_system_info()
        assert "platform_version" in info

    def test_includes_keys_referenced_by_startup_banner(self):
        info = get_system_info()
        for key in ("platform", "platform_version", "python_version", "cpu_count"):
            assert key in info


class TestHttpDiagnosticTools:
    def test_check_required_tools_runs_without_recursion(self):
        # Before the alias fix the registered tool shadowed the module import
        # and recursed until RecursionError. A clean call proves it now resolves
        # the renamed helper instead of itself.
        result = _call_tool(NetOpsMCPHTTPServer(), "check_required_tools")
        assert result is not None

    def test_health_runs_without_recursion(self):
        result = _call_tool(NetOpsMCPHTTPServer(), "health")
        assert result is not None
