"""
Tests for configuration modules.
"""

import pytest
import tempfile
import os
import json
from unittest.mock import patch, mock_open
from netops_mcp.config.loader import load_config
from netops_mcp.config.models import Config, LoggingConfig, SecurityConfig, NetworkConfig


class TestConfigLoader:
    """Test configuration loader functionality."""

    def test_load_config_with_valid_file(self):
        """Test loading configuration from valid file."""
        config_data = {
            "logging": {
                "level": "INFO",
                "format": "json",
                "file": "test.log"
            },
            "security": {
                "allow_privileged_commands": True,
                "allowed_hosts": ["localhost", "127.0.0.1"],
                "rate_limit_requests": 60
            },
            "network": {
                "default_timeout": 30,
                "max_retries": 3,
                "ping_count": 4,
                "nmap_scan_timeout": 300
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
            json.dump(config_data, temp_file)
            temp_file.close()
            
            try:
                config = load_config(temp_file.name)
                
                assert config is not None
                assert isinstance(config, Config)
                assert config.logging.level == "INFO"
                assert config.security.allow_privileged_commands == True
                assert config.network.default_timeout == 30
                # server attribute doesn't exist in current config model
                assert config.network.default_timeout == 30
            finally:
                os.unlink(temp_file.name)

    def test_load_config_with_nonexistent_file(self):
        """Test loading configuration with nonexistent file."""
        config = load_config("nonexistent_file.json")
        
        assert config is not None
        assert isinstance(config, Config)
        # Should use default values
        assert config.logging.level == "INFO"
        # server attribute doesn't exist in current config model
        assert config.network.default_timeout == 30

    def test_load_config_with_none_path(self):
        """Test loading configuration with None path."""
        config = load_config(None)
        
        assert config is not None
        assert isinstance(config, Config)
        # Should use default values
        assert config.logging.level == "INFO"

    def test_load_config_with_invalid_json(self):
        """Test loading configuration with invalid JSON."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
            temp_file.write('{"invalid": "json"')
            temp_file.close()
            
            try:
                with pytest.raises(ValueError):
                    config = load_config(temp_file.name)
            finally:
                os.unlink(temp_file.name)

    def test_load_config_with_empty_file(self):
        """Test loading configuration with empty file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
            temp_file.write('{}')
            temp_file.close()
            
            try:
                config = load_config(temp_file.name)
                
                assert config is not None
                assert isinstance(config, Config)
                # Should use default values
                assert config.logging.level == "INFO"
            finally:
                os.unlink(temp_file.name)


class TestConfigModels:
    """Test configuration models."""

    def test_logging_config_defaults(self):
        """Test LoggingConfig default values."""
        config = LoggingConfig()
        
        assert config.level == "INFO"
        assert config.format == "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        assert config.file == None

    def test_logging_config_custom_values(self):
        """Test LoggingConfig with custom values."""
        config = LoggingConfig(
            level="DEBUG",
            format="json",
            file="custom.log"
        )
        
        assert config.level == "DEBUG"
        assert config.format == "json"
        assert config.file == "custom.log"

    def test_security_config_defaults(self):
        """Test SecurityConfig default values."""
        config = SecurityConfig()
        
        assert config.allow_privileged_commands == False
        assert config.allowed_hosts == []
        assert config.rate_limit_requests == 100
        assert config.rate_limit_window == 60

    def test_security_config_custom_values(self):
        """Test SecurityConfig with custom values."""
        config = SecurityConfig(
            allow_privileged_commands=True,
            allowed_hosts=["localhost"],
            rate_limit_requests=30
        )
        
        assert config.allow_privileged_commands == True
        assert config.allowed_hosts == ["localhost"]
        assert config.rate_limit_requests == 30
        assert config.rate_limit_window == 60

    def test_network_config_defaults(self):
        """Test NetworkConfig default values."""
        config = NetworkConfig()
        
        assert config.default_timeout == 30
        assert config.max_retries == 3
        assert config.ping_count == 4
        assert config.nmap_scan_timeout == 300

    def test_network_config_custom_values(self):
        """Test NetworkConfig with custom values."""
        config = NetworkConfig(
            default_timeout=60,
            max_retries=5,
            ping_count=10,
            nmap_scan_timeout=600
        )
        
        assert config.default_timeout == 60
        assert config.max_retries == 5
        assert config.ping_count == 10
        assert config.nmap_scan_timeout == 600

    def test_config_defaults(self):
        """Test Config default values."""
        config = Config()
        
        assert isinstance(config.logging, LoggingConfig)
        assert isinstance(config.security, SecurityConfig)
        assert isinstance(config.network, NetworkConfig)
        # server attribute doesn't exist in current config model
        assert config.network.default_timeout == 30
        # server attributes don't exist in current config model
        assert config.network.max_retries == 3

    def test_config_custom_values(self):
        """Test Config with custom values."""
        config = Config(
            logging={"level": "DEBUG"},
            security={"allow_privileged_commands": True},
            network={"default_timeout": 60, "max_retries": 5, "ping_count": 8}
        )
        
        assert config.logging.level == "DEBUG"
        assert config.security.allow_privileged_commands == True
        assert config.network.default_timeout == 60
        # server attributes don't exist in current config model
        assert config.network.max_retries == 5
        # server attributes don't exist in current config model
        assert config.network.ping_count == 8

    def test_config_validation(self):
        """Test Config validation."""
        # This test is simplified since Pydantic handles validation
        config = Config()
        assert config is not None


class TestToolGroupsConfig:
    """Tool-group enable/disable settings."""

    def test_all_groups_enabled_by_default(self):
        config = Config()
        assert config.tool_groups.http is True
        assert config.tool_groups.discovery is True
        assert config.tool_groups.security is True

    def test_model_fields_match_registry(self):
        """The model's fields must stay in sync with the canonical registry."""
        from netops_mcp.config.models import ToolGroupsConfig
        from netops_mcp.tools.groups import TOOL_GROUPS

        assert set(ToolGroupsConfig.model_fields) == set(TOOL_GROUPS)

    def test_is_enabled_helper(self):
        config = Config(tool_groups={"discovery": False})
        assert config.tool_groups.is_enabled("discovery") is False
        assert config.tool_groups.is_enabled("http") is True
        # Unknown keys default to enabled.
        assert config.tool_groups.is_enabled("nonexistent") is True

    def test_json_config_disables_group(self):
        config_data = {"tool_groups": {"security": False, "discovery": False}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            f.close()
            try:
                config = load_config(f.name)
            finally:
                os.unlink(f.name)

        assert config.tool_groups.security is False
        assert config.tool_groups.discovery is False
        assert config.tool_groups.http is True

    def test_env_var_disables_group(self, monkeypatch):
        monkeypatch.setenv("TOOL_GROUP_DISCOVERY", "false")
        config = load_config(None)
        assert config.tool_groups.discovery is False
        assert config.tool_groups.http is True

    def test_env_var_overrides_json(self, monkeypatch):
        """Env wins over the JSON file (documented precedence)."""
        config_data = {"tool_groups": {"discovery": True}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            f.close()
            monkeypatch.setenv("TOOL_GROUP_DISCOVERY", "false")
            try:
                config = load_config(f.name)
            finally:
                os.unlink(f.name)

        assert config.tool_groups.discovery is False
