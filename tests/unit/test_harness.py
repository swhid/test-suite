"""
Unit tests for main harness functionality
"""

import pytest
import tempfile
import os
import yaml
from pathlib import Path
from typing import Optional
from unittest.mock import Mock, patch, MagicMock

from harness.harness import SwhidHarness
from harness.plugins.base import SwhidImplementation, ImplementationInfo, SwhidTestResult, ComparisonResult


class MockImplementation(SwhidImplementation):
    """Mock implementation for testing."""
    
    def __init__(self, name="mock", available=True, swhid="swh:1:cnt:test123", error=None):
        self._name = name
        self._available = available
        self._swhid = swhid
        self._error = error
    
    def get_info(self) -> ImplementationInfo:
        return ImplementationInfo(
            name=self._name,
            version="1.0.0",
            language="python",
            description="Mock implementation for testing"
        )
    
    def is_available(self) -> bool:
        return self._available
    
    def get_capabilities(self):
        from harness.plugins.base import ImplementationCapabilities
        return ImplementationCapabilities(
            supported_types=["cnt", "dir"],
            supported_qualifiers=[],
            api_version="1.0",
            max_payload_size_mb=100,
            supports_unicode=True,
            supports_percent_encoding=True
        )
    
    def compute_swhid(self, payload_path: str, obj_type: str = None, 
                     commit: Optional[str] = None, tag: Optional[str] = None) -> str:
        if not self._available:
            raise RuntimeError("Implementation not available")
        if self._error:
            raise RuntimeError(self._error)
        return self._swhid


class TestSwhidHarness:
    """Test SwhidHarness class."""
    
    def test_harness_initialization(self):
        """Test harness initialization with default config."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config = {
                "output": {"results_dir": "test_results"},
                "settings": {"parallel_tests": 2},
                "payloads": {
                    "content": [
                        {"name": "test", "path": "/test/path"}
                    ]
                }
            }
            yaml.dump(config, f)
            config_path = f.name
        
        try:
            harness = SwhidHarness(config_path)
            assert harness.config_path == config_path
            assert harness.results_dir == Path("test_results")
        finally:
            os.unlink(config_path)
    
    def test_load_config(self):
        """Test config loading."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config = {
                "output": {"results_dir": "test_results"},
                "settings": {"parallel_tests": 2},
                "payloads": {}
            }
            yaml.dump(config, f)
            config_path = f.name
        
        try:
            harness = SwhidHarness(config_path)
            assert harness.config["output"]["results_dir"] == "test_results"
            assert harness.config["settings"]["parallel_tests"] == 2
        finally:
            os.unlink(config_path)
    
    @patch('harness.harness.ImplementationDiscovery')
    def test_load_implementations(self, mock_discovery_class):
        """Test loading implementations."""
        # Setup mock discovery
        mock_discovery = Mock()
        mock_impl1 = MockImplementation("impl1")
        mock_impl2 = MockImplementation("impl2")
        mock_discovery.discover_implementations.return_value = {
            "impl1": mock_impl1,
            "impl2": mock_impl2
        }
        mock_discovery_class.return_value = mock_discovery
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config = {
                "output": {"results_dir": "test_results"},
                "settings": {"parallel_tests": 2},
                "payloads": {}
            }
            yaml.dump(config, f)
            config_path = f.name
        
        try:
            harness = SwhidHarness(config_path)
            implementations = harness._load_implementations()
            
            assert len(implementations) == 2
            assert "impl1" in implementations
            assert "impl2" in implementations
        finally:
            os.unlink(config_path)
    
    @patch('harness.harness.ImplementationDiscovery')
    def test_load_implementations_filtered(self, mock_discovery_class):
        """Test loading filtered implementations."""
        # Setup mock discovery
        mock_discovery = Mock()
        mock_impl1 = MockImplementation("impl1")
        mock_impl2 = MockImplementation("impl2")
        mock_discovery.discover_implementations.return_value = {
            "impl1": mock_impl1,
            "impl2": mock_impl2
        }
        mock_discovery_class.return_value = mock_discovery
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config = {
                "output": {"results_dir": "test_results"},
                "settings": {"parallel_tests": 2},
                "payloads": {}
            }
            yaml.dump(config, f)
            config_path = f.name
        
        try:
            harness = SwhidHarness(config_path)
            implementations = harness._load_implementations(["impl1"])
            
            assert len(implementations) == 1
            assert "impl1" in implementations
            assert "impl2" not in implementations
        finally:
            os.unlink(config_path)
    
    def test_run_single_test_success(self):
        """Test running a single successful test."""
        impl = MockImplementation("test-impl", available=True, swhid="swh:1:cnt:success123")
        
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"test content")
            f.flush()
            
            harness = SwhidHarness.__new__(SwhidHarness)  # Create without __init__
            result = harness._run_single_test(impl, f.name, "test_file")
            
            assert result.success is True
            assert result.swhid == "swh:1:cnt:success123"
            assert result.implementation == "test-impl"
            assert result.error is None
    
    def test_run_single_test_failure(self):
        """Test running a single failed test."""
        impl = MockImplementation("test-impl", available=True, error="Test error")
        
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"test content")
            f.flush()
            
            harness = SwhidHarness.__new__(SwhidHarness)  # Create without __init__
            result = harness._run_single_test(impl, f.name, "test_file")
            
            assert result.success is False
            assert result.swhid is None
            assert result.error == "Test error"
    
    def test_compare_results_all_match(self):
        """Test comparing results when all match."""
        results = {
            "impl1": SwhidTestResult("test.txt", "/path", "impl1", "swh:1:cnt:test123", None, 1.0, True),
            "impl2": SwhidTestResult("test.txt", "/path", "impl2", "swh:1:cnt:test123", None, 1.5, True)
        }
        
        harness = SwhidHarness.__new__(SwhidHarness)  # Create without __init__
        comparison = harness._compare_results("test.txt", "/path/to/test.txt", results)
        
        assert comparison.all_match is True
        assert comparison.payload_name == "test.txt"
        assert len(comparison.results) == 2
    
    def test_compare_results_no_match(self):
        """Test comparing results when they don't match."""
        results = {
            "impl1": SwhidTestResult("test.txt", "/path", "impl1", "swh:1:cnt:test123", None, 1.0, True),
            "impl2": SwhidTestResult("test.txt", "/path", "impl2", "swh:1:cnt:different", None, 1.5, True)
        }
        
        harness = SwhidHarness.__new__(SwhidHarness)  # Create without __init__
        comparison = harness._compare_results("test.txt", "/path/to/test.txt", results)
        
        assert comparison.all_match is False
    
    def test_compare_results_with_failure(self):
        """Test comparing results when some implementations fail."""
        results = {
            "impl1": SwhidTestResult("test.txt", "/path", "impl1", "swh:1:cnt:test123", None, 1.0, True),
            "impl2": SwhidTestResult("test.txt", "/path", "impl2", None, "Error occurred", 1.5, False)
        }
        
        harness = SwhidHarness.__new__(SwhidHarness)  # Create without __init__
        comparison = harness._compare_results("test.txt", "/path/to/test.txt", results)
        
        assert comparison.all_match is False
    
    def test_compare_results_with_expected(self):
        """Test comparing results with expected SWHID."""
        results = {
            "impl1": SwhidTestResult("test.txt", "/path", "impl1", "swh:1:cnt:expected123", None, 1.0, True),
            "impl2": SwhidTestResult("test.txt", "/path", "impl2", "swh:1:cnt:expected123", None, 1.5, True)
        }
        
        harness = SwhidHarness.__new__(SwhidHarness)  # Create without __init__
        comparison = harness._compare_results("test.txt", "/path/to/test.txt", results, "swh:1:cnt:expected123")
        
        assert comparison.all_match is True
        assert comparison.expected_swhid == "swh:1:cnt:expected123"
    
    def test_compare_results_with_wrong_expected(self):
        """Test comparing results with wrong expected SWHID."""
        results = {
            "impl1": SwhidTestResult("test.txt", "/path", "impl1", "swh:1:cnt:actual123", None, 1.0, True),
            "impl2": SwhidTestResult("test.txt", "/path", "impl2", "swh:1:cnt:actual123", None, 1.5, True)
        }
        
        harness = SwhidHarness.__new__(SwhidHarness)  # Create without __init__
        comparison = harness._compare_results("test.txt", "/path/to/test.txt", results, "swh:1:cnt:expected123")
        
        assert comparison.all_match is False
