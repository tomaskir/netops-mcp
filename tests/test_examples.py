"""Validate the shipped MCP client example configs against the actual code.

A stdio MCP client (e.g. Cursor) launches the server as a subprocess that
speaks MCP over stdio, so the example must invoke the stdio module
``netops_mcp.server`` — NOT ``netops_mcp.server_http``, which starts a blocking
uvicorn HTTP server and never speaks stdio.
"""

import importlib.util
import json
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_cursor_stdio_example_launches_the_stdio_module():
    config = json.loads((EXAMPLES / "cursor_mcp_config.json").read_text())
    server = config["mcpServers"]["netops-mcp"]
    assert server["command"] == "python"
    # Must run the stdio transport, not the HTTP server.
    assert server["args"] == ["-m", "netops_mcp.server"]
    assert "netops_mcp.server_http" not in server["args"]


def test_example_module_is_importable():
    # The module the example points at must exist as an importable target.
    assert importlib.util.find_spec("netops_mcp.server") is not None
