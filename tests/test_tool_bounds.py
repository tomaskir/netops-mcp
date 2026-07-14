"""
Tests for user-supplied timeout/count bounds (worker-exhaustion / DoS hardening).

Covers the base-class validators, the _execute_command ceiling clamp, and a
representative set of tool call sites that reject out-of-range values before any
command runs.
"""

from unittest.mock import MagicMock

import pytest

from netops_mcp.tools.base import (
    MAX_PROBE_COUNT,
    MAX_PROCESS_LIMIT,
    MAX_TIMEOUT,
    MAX_TRACEROUTE_HOPS,
    NetOpsTool,
)
from netops_mcp.tools.network.connectivity_tools import ConnectivityTools
from netops_mcp.tools.network.discovery_tools import DiscoveryTools
from netops_mcp.tools.security.scanning_tools import ScanningTools
from netops_mcp.tools.system.monitoring_tools import MonitoringTools


class TestValidateTimeout:
    def setup_method(self):
        self.tool = NetOpsTool()

    def test_accepts_in_range(self):
        assert self.tool._validate_timeout(30) == 30

    def test_accepts_numeric_string(self):
        assert self.tool._validate_timeout("45") == 45

    @pytest.mark.parametrize("bad", [MAX_TIMEOUT + 1, 0, -5, "abc", None])
    def test_rejects_out_of_range_or_non_int(self, bad):
        with pytest.raises(ValueError):
            self.tool._validate_timeout(bad)

    def test_honors_lower_per_site_maximum(self):
        assert self.tool._validate_timeout(300, maximum=300) == 300
        with pytest.raises(ValueError):
            self.tool._validate_timeout(400, maximum=300)


class TestValidateCount:
    def setup_method(self):
        self.tool = NetOpsTool()

    def test_accepts_in_range(self):
        assert self.tool._validate_count(5, "count") == 5

    @pytest.mark.parametrize("bad", [0, -1, MAX_PROBE_COUNT + 1, "x", None])
    def test_rejects_out_of_range_or_non_int(self, bad):
        with pytest.raises(ValueError):
            self.tool._validate_count(bad, "count")

    def test_honors_custom_bounds(self):
        assert (
            self.tool._validate_count(
                MAX_TRACEROUTE_HOPS, "max_hops", maximum=MAX_TRACEROUTE_HOPS
            )
            == MAX_TRACEROUTE_HOPS
        )
        with pytest.raises(ValueError):
            self.tool._validate_count(
                MAX_TRACEROUTE_HOPS + 1, "max_hops", maximum=MAX_TRACEROUTE_HOPS
            )


class TestExecuteCommandClamp:
    """The subprocess timeout is the real guarantee a worker can't be pinned."""

    def _run(self, mock_subprocess_run, timeout):
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        NetOpsTool()._execute_command(["echo", "hi"], timeout=timeout)
        return mock_subprocess_run.call_args.kwargs["timeout"]

    def test_clamps_excessive_timeout_to_ceiling(self, mock_subprocess_run):
        assert self._run(mock_subprocess_run, 10_000) == MAX_TIMEOUT

    def test_floors_nonpositive_timeout_to_one(self, mock_subprocess_run):
        assert self._run(mock_subprocess_run, 0) == 1

    def test_non_int_timeout_defaults_to_30(self, mock_subprocess_run):
        assert self._run(mock_subprocess_run, "oops") == 30


class TestCallSitesRejectOutOfRange:
    """Guarded tools return an error payload instead of spawning a command."""

    def test_traceroute_rejects_excessive_hops(self, mock_execute_command):
        result = ConnectivityTools().traceroute_path("example.com", max_hops=99999)
        assert "error" in result[0].text.lower()
        mock_execute_command.assert_not_called()

    def test_nmap_rejects_excessive_timeout(self, mock_execute_command):
        result = DiscoveryTools().nmap_scan("example.com", timeout=999999)
        assert "error" in result[0].text.lower()
        mock_execute_command.assert_not_called()

    def test_port_scan_rejects_excessive_timeout(self, mock_execute_command):
        result = ScanningTools().port_scan("example.com", "1-10", timeout=999999)
        assert "error" in result[0].text.lower()
        mock_execute_command.assert_not_called()

    def test_process_list_rejects_excessive_limit(self):
        result = MonitoringTools().process_list(limit=MAX_PROCESS_LIMIT + 1)
        assert "error" in result[0].text.lower()
