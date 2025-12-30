"""
Unit tests for harness v2/SHA256 support.
"""

import pytest
import tempfile
import os
import yaml
from unittest.mock import Mock, patch, MagicMock

from harness.harness import SwhidHarness
from harness.plugins.base import SwhidTestResult, ComparisonResult
from tests.unit.test_harness import MockImplementation


class TestHarnessV2Support:
    """Test harness v2/SHA256 support."""
    
    def test_run_single_test_with_v2(self):
        """Test that _run_single_test passes version/hash to implementation."""
        impl = MockImplementation("test-impl", available=True, swhid="swh:2:cnt:abc123")
        
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"test content")
            f.flush()
            
            harness = SwhidHarness.__new__(SwhidHarness)
            
            # Mock compute_swhid to capture arguments
            original_compute = impl.compute_swhid
            call_args = []
            def mock_compute(*args, **kwargs):
                call_args.append((args, kwargs))
                return original_compute(*args, **kwargs)
            impl.compute_swhid = mock_compute
            
            result = harness._run_single_test(
                impl, f.name, "test_file", category="content",
                version=2, hash_algo="sha256"
            )
            
            assert result.success is True
            assert result.version == 2
            assert len(call_args) == 1
            _, kwargs = call_args[0]
            assert kwargs.get("version") == 2
            assert kwargs.get("hash_algo") == "sha256"
    
    def test_run_single_test_with_v1_default(self):
        """Test that _run_single_test defaults to v1 when no version specified."""
        impl = MockImplementation("test-impl", available=True, swhid="swh:1:cnt:abc123")
        
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"test content")
            f.flush()
            
            harness = SwhidHarness.__new__(SwhidHarness)
            result = harness._run_single_test(impl, f.name, "test_file", category="content")
            
            assert result.success is True
            assert result.version == 1
    
    def test_compare_results_v1_only(self):
        """Test _compare_results with v1 results only."""
        results = {
            "impl1": SwhidTestResult("test.txt", "/path", "impl1", "swh:1:cnt:abc123", None, 1.0, True, version=1),
            "impl2": SwhidTestResult("test.txt", "/path", "impl2", "swh:1:cnt:abc123", None, 1.5, True, version=1)
        }
        
        harness = SwhidHarness.__new__(SwhidHarness)
        comparison = harness._compare_results(
            "test.txt", "/path/to/test.txt", results,
            expected_swhid="swh:1:cnt:abc123"
        )
        
        assert comparison.all_match is True
        assert comparison.expected_swhid == "swh:1:cnt:abc123"
        assert comparison.expected_swhid_sha256 is None
    
    def test_compare_results_v2_only(self):
        """Test _compare_results with v2 results only."""
        results = {
            "impl1": SwhidTestResult("test.txt", "/path", "impl1", "swh:2:cnt:def456", None, 1.0, True, version=2),
            "impl2": SwhidTestResult("test.txt", "/path", "impl2", "swh:2:cnt:def456", None, 1.5, True, version=2)
        }
        
        harness = SwhidHarness.__new__(SwhidHarness)
        comparison = harness._compare_results(
            "test.txt", "/path/to/test.txt", results,
            expected_swhid=None,
            expected_swhid_sha256="swh:2:cnt:def456"
        )
        
        assert comparison.all_match is True
        assert comparison.expected_swhid_sha256 == "swh:2:cnt:def456"
    
    def test_compare_results_dual_version(self):
        """Test _compare_results with both v1 and v2 results."""
        results = {
            "impl1_v1": SwhidTestResult("test.txt", "/path", "impl1", "swh:1:cnt:abc123", None, 1.0, True, version=1),
            "impl1_v2": SwhidTestResult("test.txt", "/path", "impl1", "swh:2:cnt:def456", None, 1.0, True, version=2),
            "impl2_v1": SwhidTestResult("test.txt", "/path", "impl2", "swh:1:cnt:abc123", None, 1.5, True, version=1),
            "impl2_v2": SwhidTestResult("test.txt", "/path", "impl2", "swh:2:cnt:def456", None, 1.5, True, version=2)
        }
        
        harness = SwhidHarness.__new__(SwhidHarness)
        comparison = harness._compare_results(
            "test.txt", "/path/to/test.txt", results,
            expected_swhid="swh:1:cnt:abc123",
            expected_swhid_sha256="swh:2:cnt:def456"
        )
        
        assert comparison.all_match is True
        assert comparison.expected_swhid == "swh:1:cnt:abc123"
        assert comparison.expected_swhid_sha256 == "swh:2:cnt:def456"
    
    def test_compare_results_v1_mismatch(self):
        """Test _compare_results when v1 results don't match expected."""
        results = {
            "impl1": SwhidTestResult("test.txt", "/path", "impl1", "swh:1:cnt:wrong123", None, 1.0, True, version=1),
            "impl2": SwhidTestResult("test.txt", "/path", "impl2", "swh:1:cnt:wrong123", None, 1.5, True, version=1)
        }
        
        harness = SwhidHarness.__new__(SwhidHarness)
        comparison = harness._compare_results(
            "test.txt", "/path/to/test.txt", results,
            expected_swhid="swh:1:cnt:expected123"
        )
        
        assert comparison.all_match is False
    
    def test_compare_results_v2_mismatch(self):
        """Test _compare_results when v2 results don't match expected."""
        results = {
            "impl1": SwhidTestResult("test.txt", "/path", "impl1", "swh:2:cnt:wrong456", None, 1.0, True, version=2),
            "impl2": SwhidTestResult("test.txt", "/path", "impl2", "swh:2:cnt:wrong456", None, 1.5, True, version=2)
        }
        
        harness = SwhidHarness.__new__(SwhidHarness)
        comparison = harness._compare_results(
            "test.txt", "/path/to/test.txt", results,
            expected_swhid=None,
            expected_swhid_sha256="swh:2:cnt:expected456"
        )
        
        assert comparison.all_match is False
    
    def test_run_tests_extracts_expected_swhid_sha256(self):
        """Test that run_tests extracts expected_swhid_sha256 from config."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config = {
                "output": {"results_dir": "test_results"},
                "settings": {"parallel_tests": 1},
                "payloads": {
                    "content": [
                        {
                            "name": "test",
                            "path": "/nonexistent/path",
                            "expected_swhid": "swh:1:cnt:abc123",
                            "expected_swhid_sha256": "swh:2:cnt:def456"
                        }
                    ]
                }
            }
            yaml.dump(config, f)
            config_path = f.name
        
        try:
            harness = SwhidHarness(config_path)
            # Mock implementations to avoid actual execution
            harness.implementations = {
                "mock": MockImplementation("mock", available=False)
            }
            
            # The test should extract both expected values
            # We can't easily test the full run without actual payloads,
            # but we can verify the config is loaded correctly
            payload = harness.config["payloads"]["content"][0]
            assert payload.get("expected_swhid") == "swh:1:cnt:abc123"
            assert payload.get("expected_swhid_sha256") == "swh:2:cnt:def456"
        finally:
            os.unlink(config_path)
    
    def test_version_detection_from_swhid(self):
        """Test that version is detected from SWHID string when not explicitly provided."""
        impl = MockImplementation("test-impl", available=True, swhid="swh:2:cnt:abc123")
        
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"test content")
            f.flush()
            
            harness = SwhidHarness.__new__(SwhidHarness)
            # Don't pass version, let it be detected from SWHID
            result = harness._run_single_test(impl, f.name, "test_file", category="content")
            
            # Version should be detected as 2 from the SWHID
            assert result.success is True
            assert result.version == 2
            assert result.swhid.startswith("swh:2:")

