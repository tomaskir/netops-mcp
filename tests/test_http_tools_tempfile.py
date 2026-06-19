"""
Tests for per-request temp-file handling in curl_request.

Guards the fix that replaced the shared, predictable /tmp/curl_output path with
a unique tempfile.mkstemp file per request, always cleaned up (even on error).
"""

import os
import tempfile
from unittest.mock import patch

from netops_mcp.tools.network.http_tools import HTTPTools

# Capture the real mkstemp before any patch so the wrapper doesn't recurse into
# the mock it replaces.
_REAL_MKSTEMP = tempfile.mkstemp

SUCCESS = {
    "success": True,
    "stdout": '{"http_code": "200", "time_total": "0.1"}',
    "stderr": "",
    "return_code": 0,
    "command": "curl ...",
}


def _capturing_mkstemp(paths):
    def wrapper(*args, **kwargs):
        fd, path = _REAL_MKSTEMP(*args, **kwargs)
        paths.append(path)
        return fd, path

    return wrapper


def _patch_mkstemp(paths):
    return patch(
        "netops_mcp.tools.network.http_tools.tempfile.mkstemp",
        side_effect=_capturing_mkstemp(paths),
    )


class TestCurlTempFiles:
    def test_uses_unique_file_per_request(self, mock_execute_command):
        mock_execute_command.return_value = SUCCESS
        paths = []
        with _patch_mkstemp(paths):
            HTTPTools().curl_request("https://example.com")
            HTTPTools().curl_request("https://example.com")

        assert len(paths) == 2
        assert paths[0] != paths[1]  # per-request, not a shared path
        assert all(os.path.basename(p).startswith("netops-curl-") for p in paths)

    def test_temp_file_removed_after_success(self, mock_execute_command):
        mock_execute_command.return_value = SUCCESS
        paths = []
        with _patch_mkstemp(paths):
            HTTPTools().curl_request("https://example.com")

        assert paths and not os.path.exists(paths[0])

    def test_temp_file_removed_on_error(self, mock_execute_command):
        mock_execute_command.side_effect = RuntimeError("boom")
        paths = []
        with _patch_mkstemp(paths):
            result = HTTPTools().curl_request("https://example.com")

        assert "error" in result[0].text.lower()  # degraded to an error payload
        assert paths and not os.path.exists(paths[0])  # cleanup still ran
