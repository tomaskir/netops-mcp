"""
HTTP/API testing tools for NetOps MCP.
"""

import json
import os
import re
import tempfile
from typing import Dict, List, Optional, Any
from mcp.types import TextContent as Content
from ..base import NetOpsTool


# RFC 7230 token characters — the only bytes allowed in an HTTP header field
# name. The set deliberately excludes '@' (so a header can never be turned into
# curl's "-H @filename" read-from-file form) and ':'/'=' (so a header can't be
# smuggled in as an httpie request item).
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


class HTTPTools(NetOpsTool):
    """Tools for HTTP/API testing and diagnostics."""

    def _validate_header(self, key: str, value: str) -> None:
        """Reject header items that curl/httpie could reinterpret unsafely.

        A field name outside the RFC 7230 token set (e.g. one starting with
        '@') could make curl read headers from a local file, and CR/LF/NUL in a
        value enables request header injection.

        Raises:
            ValueError: If the header name or value is unsafe.
        """
        if not isinstance(key, str) or not _HEADER_NAME_RE.match(key):
            raise ValueError(f"Invalid header name: {key!r}")
        if not isinstance(value, str) or re.search(r"[\r\n\x00]", value):
            raise ValueError(f"Invalid header value for {key!r}")

    def _validate_url(self, url: str) -> bool:
        """Validate URL format.

        Args:
            url: URL to validate

        Returns:
            True if URL is valid
        """
        if not url or not isinstance(url, str):
            return False
        
        # Basic URL validation regex
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
        
        return bool(url_pattern.match(url))

    def _validate_method(self, method: str) -> bool:
        """Validate HTTP method.

        Args:
            method: HTTP method to validate

        Returns:
            True if method is valid
        """
        if not method or not isinstance(method, str):
            return False
        
        valid_methods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']
        return method.upper() in valid_methods

    def _format_curl_command(self, url: str, output_file: str, method: str = "GET",
                           headers: Optional[Dict[str, str]] = None,
                           data: Optional[str] = None, timeout: int = 30) -> List[str]:
        """Format curl command with parameters.

        Args:
            url: Target URL
            output_file: Path where curl writes the response body
            method: HTTP method
            headers: Optional HTTP headers
            data: Optional request body
            timeout: Request timeout

        Returns:
            List of command arguments
        """
        # -g disables curl's URL globbing so '[', ']', '{', '}' in the URL are
        # sent literally instead of expanding into extra requests.
        command = ['curl', '-g', '-s', '-w', '@-', '-o', output_file, '-X', method, url]

        # Add headers
        if headers:
            for key, value in headers.items():
                self._validate_header(key, value)
                command.extend(['-H', f'{key}: {value}'])

        # Add data
        if data:
            # --data-raw (not -d): a leading '@' is sent literally instead of
            # being treated as "read this local file", which would otherwise let
            # a caller exfiltrate arbitrary server-side files to the target URL.
            command.extend(['--data-raw', data])

        # Add timeout
        command.extend(['--max-time', str(timeout)])

        return command

    def _format_httpie_command(self, url: str, method: str = "GET",
                              headers: Optional[Dict[str, str]] = None,
                              data: Optional[Dict[str, Any]] = None, 
                              timeout: int = 30) -> List[str]:
        """Format httpie command with parameters.

        Args:
            url: Target URL
            method: HTTP method
            headers: Optional HTTP headers
            data: Optional request data
            timeout: Request timeout

        Returns:
            List of command arguments
        """
        # --ignore-stdin stops httpie from blocking on / reading redirected
        # stdin as the request body.
        command = ['http', '--ignore-stdin', method, url, '--timeout', str(timeout)]

        # Add headers
        if headers:
            for key, value in headers.items():
                self._validate_header(key, value)
                command.append(f'{key}:{value}')

        # Add data
        if data:
            for key, value in data.items():
                # httpie treats 'name@file' and 'name=@file' request items as
                # read-from-file. Restricting the field name to a token and
                # forbidding '@' in the value blocks local-file disclosure.
                if not isinstance(key, str) or not _HEADER_NAME_RE.match(key):
                    raise ValueError(f"Invalid data field name: {key!r}")
                if '@' in str(value):
                    raise ValueError(f"Invalid data value for {key!r}: '@' not allowed")
                command.append(f'{key}={value}')

        return command

    def _parse_curl_output(self, output: str) -> Dict[str, Any]:
        """Parse curl output statistics.

        Args:
            output: Raw curl output

        Returns:
            Dictionary with parsed statistics
        """
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"error": "Could not parse curl output"}

    def curl_request(self, url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None, 
                    data: Optional[str] = None, timeout: int = 30) -> List[Content]:
        """Execute HTTP request using curl.

        Args:
            url: Target URL
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            headers: Optional HTTP headers
            data: Optional request body
            timeout: Request timeout in seconds

        Returns:
            List of Content objects with curl response
        """
        try:
            if not self._validate_url(url):
                raise ValueError("Invalid URL provided")
            
            if not self._validate_method(method):
                raise ValueError("Invalid HTTP method provided")

            # Use a unique temp file per request so concurrent calls don't
            # clobber each other's response bodies (and to avoid a predictable
            # path in a shared /tmp).
            fd, output_file = tempfile.mkstemp(prefix="netops-curl-")
            os.close(fd)
            try:
                command = self._format_curl_command(url, output_file, method, headers, data, timeout)

                # Execute curl with format
                result = self._execute_command(command, timeout + 5)

                if result["success"]:
                    # Read output file
                    try:
                        with open(output_file, 'r') as f:
                            response_body = f.read()
                    except FileNotFoundError:
                        response_body = ""
                else:
                    response_body = ""
            finally:
                try:
                    os.unlink(output_file)
                except OSError:
                    pass

            if result["success"]:
                # Parse curl stats
                stats = self._parse_curl_output(result["stdout"])

                response_data = {
                    "url": url,
                    "method": method,
                    "success": True,
                    "stats": stats,
                    "response_body": response_body,
                    "stderr": result["stderr"]
                }
            else:
                response_data = {
                    "url": url,
                    "method": method,
                    "success": False,
                    "error": result["stderr"],
                    "return_code": result["return_code"]
                }
            
            return self._format_response(response_data, "curl_request")
            
        except Exception as e:
            return self._handle_error("curl request", e)

    def httpie_request(self, url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None,
                      data: Optional[Dict[str, Any]] = None, timeout: int = 30) -> List[Content]:
        """Execute HTTP request using httpie.

        Args:
            url: Target URL
            method: HTTP method
            headers: Optional HTTP headers
            data: Optional request body
            timeout: Request timeout in seconds

        Returns:
            List of Content objects with httpie response
        """
        try:
            if not self._validate_url(url):
                raise ValueError("Invalid URL provided")
            
            if not self._validate_method(method):
                raise ValueError("Invalid HTTP method provided")

            command = self._format_httpie_command(url, method, headers, data, timeout)
            
            result = self._execute_command(command, timeout + 5)
            
            response_data = {
                "url": url,
                "method": method,
                "success": result["success"],
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "return_code": result["return_code"]
            }
            
            return self._format_response(response_data, "httpie_request")
            
        except Exception as e:
            return self._handle_error("httpie request", e)

    def api_test(self, url: str, method: str = "GET", expected_status: int = 200,
                headers: Optional[Dict[str, str]] = None, timeout: int = 30) -> List[Content]:
        """Test API endpoint with validation.

        Args:
            url: API endpoint URL
            method: HTTP method
            expected_status: Expected HTTP status code
            headers: Optional HTTP headers
            timeout: Request timeout

        Returns:
            List of Content objects with API test results
        """
        try:
            if not self._validate_url(url):
                raise ValueError("Invalid URL provided")
            
            if not self._validate_method(method):
                raise ValueError("Invalid HTTP method provided")

            # Unique temp file per request to avoid concurrent clobbering and a
            # predictable path in a shared /tmp.
            fd, output_file = tempfile.mkstemp(prefix="netops-api-")
            os.close(fd)
            try:
                # Use curl for API testing with proper output handling
                # (-g disables URL globbing; see _format_curl_command).
                command = ['curl', '-g', '-s', '-w', '%{http_code}', '-o', output_file, '-X', method, url]

                # Add headers
                if headers:
                    for key, value in headers.items():
                        self._validate_header(key, value)
                        command.extend(['-H', f'{key}: {value}'])

                # Add timeout
                command.extend(['--max-time', str(timeout)])

                result = self._execute_command(command, timeout + 5)

                if result["success"]:
                    # Read response body
                    try:
                        with open(output_file, 'r') as f:
                            response_body = f.read()
                    except FileNotFoundError:
                        response_body = ""
            finally:
                try:
                    os.unlink(output_file)
                except OSError:
                    pass

            if result["success"]:
                # Parse status code
                try:
                    status_code = int(result["stdout"])
                except ValueError:
                    status_code = 0
                
                test_result = {
                    "url": url,
                    "method": method,
                    "expected_status": expected_status,
                    "actual_status": status_code,
                    "success": status_code == expected_status,
                    "response_body": response_body,
                    "test_passed": status_code == expected_status
                }
            else:
                test_result = {
                    "url": url,
                    "method": method,
                    "expected_status": expected_status,
                    "success": False,
                    "error": result["stderr"],
                    "test_passed": False
                }
            
            return self._format_response(test_result, "api_test")
            
        except Exception as e:
            return self._handle_error("API test", e)
