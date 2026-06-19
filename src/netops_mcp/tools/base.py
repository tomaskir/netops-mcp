"""
Base classes and utilities for NetOps MCP tools.

This module provides the foundation for all NetOps MCP tools, including:
- Base tool class with common functionality
- Response formatting utilities
- Error handling mechanisms
- Logging setup
"""

import logging
import subprocess
from typing import Any, Dict, List, Optional, Union
from mcp.types import TextContent as Content

from ..validators.input_validator import validate_timeout, ValidationError


# Hard ceilings on user-supplied numeric parameters. The tools run
# synchronously in the server's worker-thread pool, so an unbounded timeout (or
# a huge probe count combined with one) lets a single request pin a worker and,
# in aggregate, exhaust the pool — a cheap denial of service. These also bound
# the values echoed into the spawned command.
MAX_TIMEOUT = 600
MAX_PROBE_COUNT = 100
MAX_TRACEROUTE_HOPS = 64
MAX_PROCESS_LIMIT = 1000


class NetOpsTool:
    """Base class for NetOps MCP tools.
    
    This class provides common functionality used by all NetOps tool implementations:
    - Standardized logging
    - Response formatting
    - Error handling
    - Subprocess execution
    """

    def __init__(self):
        """Initialize the tool."""
        self.logger = logging.getLogger(f"netops-mcp.{self.__class__.__name__.lower()}")

    def _format_response(self, data: Any, tool_name: Optional[str] = None) -> List[Content]:
        """Format response data into MCP content.

        Args:
            data: Raw data to format
            tool_name: Name of the tool for context

        Returns:
            List of Content objects
        """
        import json
        
        if isinstance(data, dict):
            formatted = json.dumps(data, indent=2, default=str)
        elif isinstance(data, list):
            formatted = json.dumps(data, indent=2, default=str)
        else:
            formatted = str(data)

        return [Content(type="text", text=formatted)]

    def _validate_timeout(self, timeout: Union[int, str], maximum: int = MAX_TIMEOUT) -> int:
        """Validate and bound a user-supplied timeout (seconds).

        Raises:
            ValueError: If the timeout is not an integer in [1, maximum].
        """
        try:
            return validate_timeout(int(timeout), max_timeout=maximum)
        except (ValidationError, ValueError, TypeError) as e:
            raise ValueError(f"Invalid timeout: {e}")

    def _validate_count(
        self,
        value: Union[int, str],
        name: str = "count",
        maximum: int = MAX_PROBE_COUNT,
        minimum: int = 1,
    ) -> int:
        """Validate and bound a positive-integer parameter (count, hops, ...).

        Raises:
            ValueError: If the value is not an integer in [minimum, maximum].
        """
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid {name}: must be an integer")
        if n < minimum or n > maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        return n

    def _execute_command(self, command: List[str], timeout: int = 30) -> Dict[str, Any]:
        """Execute a system command safely.

        Args:
            command: Command to execute as list
            timeout: Command timeout in seconds

        Returns:
            Dictionary containing command results
        """
        # Backstop: never let a command run longer than MAX_TIMEOUT regardless
        # of caller, so a worker thread can't be held indefinitely.
        try:
            timeout = max(1, min(int(timeout), MAX_TIMEOUT))
        except (TypeError, ValueError):
            timeout = 30

        try:
            self.logger.debug(f"Executing command: {' '.join(command)}")

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
                "command": ' '.join(command)
            }
            
        except subprocess.TimeoutExpired:
            self.logger.error(f"Command timed out: {' '.join(command)}")
            return {
                "success": False,
                "stdout": "",
                "stderr": "Command timed out",
                "return_code": -1,
                "command": ' '.join(command)
            }
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Command failed: {' '.join(command)} - {e}")
            return {
                "success": False,
                "stdout": e.stdout or "",
                "stderr": e.stderr or str(e),
                "return_code": e.returncode,
                "command": ' '.join(command)
            }
        except FileNotFoundError:
            self.logger.error(f"Command not found: {command[0]}")
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Command not found: {command[0]}",
                "return_code": -1,
                "command": ' '.join(command)
            }
        except Exception as e:
            self.logger.error(f"Unexpected error executing command: {e}")
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "return_code": -1,
                "command": ' '.join(command)
            }

    def _handle_error(self, operation: str, error: Exception) -> List[Content]:
        """Handle and log errors from operations.

        Args:
            operation: Description of the operation that failed
            error: The exception that occurred

        Returns:
            List of Content objects with error information
        """
        error_msg = str(error)
        self.logger.error(f"Failed to {operation}: {error_msg}")

        error_response = {
            "error": True,
            "operation": operation,
            "message": error_msg,
            "type": type(error).__name__
        }

        return self._format_response(error_response)

    def _validate_host(self, host: str) -> bool:
        """Validate host parameter.

        Args:
            host: Host to validate

        Returns:
            True if host is valid
        """
        if not host or not isinstance(host, str):
            return False
        
        host = host.strip()
        if len(host) == 0:
            return False
        
        # Check for invalid patterns
        if '..' in host or ' ' in host:
            return False
        
        # Basic domain/IP validation
        import re
        # IP address pattern
        ip_pattern = re.compile(r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$')
        # Domain pattern
        domain_pattern = re.compile(r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$')
        
        return bool(ip_pattern.match(host) or domain_pattern.match(host))

    def _validate_port(self, port: Union[int, str]) -> bool:
        """Validate port parameter.

        Args:
            port: Port to validate

        Returns:
            True if port is valid
        """
        try:
            port_num = int(port)
            return 1 <= port_num <= 65535
        except (ValueError, TypeError):
            return False
