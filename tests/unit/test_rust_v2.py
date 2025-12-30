"""
Unit tests for Rust implementation v2/SHA256 support.
"""

import pytest
import os
import subprocess
from unittest.mock import Mock, patch, MagicMock, call
from pathlib import Path

from implementations.rust.implementation import Implementation


class TestRustV2Support:
    """Test Rust implementation v2/SHA256 support."""
    
    @patch('implementations.rust.implementation.subprocess.run')
    @patch.object(Implementation, '_ensure_binary_built')
    def test_compute_swhid_v1_default(self, mock_ensure_binary, mock_subprocess):
        """Test that compute_swhid defaults to v1 (no flags)."""
        # Setup mocks
        mock_ensure_binary.return_value = "/path/to/swhid"
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "swh:1:cnt:abc123\n"
        mock_subprocess.return_value = mock_result
        
        impl = Implementation()
        
        # Create a temporary file for testing
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_file = f.name
        
        try:
            result = impl.compute_swhid(temp_file, obj_type="content")
            
            # Verify command was called without version/hash flags
            calls = mock_subprocess.call_args_list
            assert len(calls) > 0
            # Last call should be the actual compute command
            last_call = calls[-1]
            cmd = last_call[0][0]  # First positional argument is the command list
            assert cmd[0] == "/path/to/swhid"
            assert "--version" not in cmd
            assert "--hash" not in cmd
            assert result == "swh:1:cnt:abc123"
        finally:
            os.unlink(temp_file)
    
    @patch('implementations.rust.implementation.subprocess.run')
    @patch.object(Implementation, '_ensure_binary_built')
    def test_compute_swhid_v2_sha256(self, mock_ensure_binary, mock_subprocess):
        """Test that compute_swhid adds --version 2 --hash sha256 flags when specified."""
        # Setup mocks
        mock_ensure_binary.return_value = "/path/to/swhid"
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "swh:2:cnt:def4567890123456789012345678901234567890123456789012345678901234\n"
        mock_subprocess.return_value = mock_result
        
        impl = Implementation()
        
        # Create a temporary file for testing
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_file = f.name
        
        try:
            result = impl.compute_swhid(
                temp_file,
                obj_type="content",
                version=2,
                hash_algo="sha256"
            )
            
            # Verify command was called with version/hash flags
            calls = mock_subprocess.call_args_list
            assert len(calls) > 0
            last_call = calls[-1]
            cmd = last_call[0][0]
            assert cmd[0] == "/path/to/swhid"
            assert "--version" in cmd
            assert "--hash" in cmd
            # Find positions of flags
            version_idx = cmd.index("--version")
            hash_idx = cmd.index("--hash")
            assert cmd[version_idx + 1] == "2"
            assert cmd[hash_idx + 1] == "sha256"
            assert result.startswith("swh:2:cnt:")
        finally:
            os.unlink(temp_file)
    
    @patch('implementations.rust.implementation.subprocess.run')
    @patch.object(Implementation, '_ensure_binary_built')
    def test_compute_swhid_v2_only(self, mock_ensure_binary, mock_subprocess):
        """Test that compute_swhid adds --version 2 but not --hash when only version specified."""
        # Setup mocks
        mock_ensure_binary.return_value = "/path/to/swhid"
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "swh:2:cnt:abc123\n"
        mock_subprocess.return_value = mock_result
        
        impl = Implementation()
        
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_file = f.name
        
        try:
            result = impl.compute_swhid(
                temp_file,
                obj_type="content",
                version=2
            )
            
            # Verify command was called with version flag but not hash flag
            calls = mock_subprocess.call_args_list
            last_call = calls[-1]
            cmd = last_call[0][0]
            assert "--version" in cmd
            assert cmd[cmd.index("--version") + 1] == "2"
            # Hash flag should not be present (defaults to sha1 for v2)
            assert "--hash" not in cmd
        finally:
            os.unlink(temp_file)
    
    @patch('implementations.rust.implementation.subprocess.run')
    @patch.object(Implementation, '_ensure_binary_built')
    def test_compute_swhid_sha256_only(self, mock_ensure_binary, mock_subprocess):
        """Test that compute_swhid adds --hash sha256 but not --version when only hash specified."""
        # Setup mocks
        mock_ensure_binary.return_value = "/path/to/swhid"
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "swh:1:cnt:abc123\n"
        mock_subprocess.return_value = mock_result
        
        impl = Implementation()
        
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_file = f.name
        
        try:
            result = impl.compute_swhid(
                temp_file,
                obj_type="content",
                hash_algo="sha256"
            )
            
            # Verify command was called with hash flag but not version flag
            calls = mock_subprocess.call_args_list
            last_call = calls[-1]
            cmd = last_call[0][0]
            assert "--hash" in cmd
            assert cmd[cmd.index("--hash") + 1] == "sha256"
            # Version flag should not be present (defaults to 1)
            assert "--version" not in cmd
        finally:
            os.unlink(temp_file)
    
    @patch('implementations.rust.implementation.subprocess.run')
    @patch.object(Implementation, '_ensure_binary_built')
    def test_compute_swhid_backward_compatibility(self, mock_ensure_binary, mock_subprocess):
        """Test that compute_swhid maintains backward compatibility (no version/hash params)."""
        # Setup mocks
        mock_ensure_binary.return_value = "/path/to/swhid"
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "swh:1:cnt:abc123\n"
        mock_subprocess.return_value = mock_result
        
        impl = Implementation()
        
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content")
            temp_file = f.name
        
        try:
            # Call without version/hash parameters (old API)
            result = impl.compute_swhid(temp_file, obj_type="content")
            
            # Should work and produce v1 result
            assert result == "swh:1:cnt:abc123"
            
            # Verify no version/hash flags were added
            calls = mock_subprocess.call_args_list
            last_call = calls[-1]
            cmd = last_call[0][0]
            assert "--version" not in cmd
            assert "--hash" not in cmd
        finally:
            os.unlink(temp_file)
    
    @patch('implementations.rust.implementation.subprocess.run')
    @patch.object(Implementation, '_ensure_binary_built')
    def test_compute_swhid_directory_v2(self, mock_ensure_binary, mock_subprocess):
        """Test that directory computation works with v2/SHA256."""
        # Setup mocks
        mock_ensure_binary.return_value = "/path/to/swhid"
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "swh:2:dir:def4567890123456789012345678901234567890123456789012345678901234\n"
        mock_subprocess.return_value = mock_result
        
        impl = Implementation()
        
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, "file.txt")
            with open(test_file, "w") as f:
                f.write("content")
            
            result = impl.compute_swhid(
                temp_dir,
                obj_type="directory",
                version=2,
                hash_algo="sha256"
            )
            
            # Verify command includes v2/SHA256 flags
            calls = mock_subprocess.call_args_list
            last_call = calls[-1]
            cmd = last_call[0][0]
            assert "--version" in cmd
            assert "--hash" in cmd
            assert result.startswith("swh:2:dir:")
    
    @patch('implementations.rust.implementation.subprocess.run')
    @patch.object(Implementation, '_ensure_binary_built')
    def test_compute_swhid_revision_v2(self, mock_ensure_binary, mock_subprocess):
        """Test that revision computation works with v2/SHA256."""
        # Setup mocks
        mock_ensure_binary.return_value = "/path/to/swhid"
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "swh:2:rev:def4567890123456789012345678901234567890123456789012345678901234\n"
        mock_subprocess.return_value = mock_result
        
        impl = Implementation()
        
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock git repo detection
            os.makedirs(os.path.join(temp_dir, ".git"))
            
            result = impl.compute_swhid(
                temp_dir,
                obj_type="revision",
                commit="HEAD",
                version=2,
                hash_algo="sha256"
            )
            
            # Verify command includes v2/SHA256 flags
            calls = mock_subprocess.call_args_list
            last_call = calls[-1]
            cmd = last_call[0][0]
            assert "--version" in cmd
            assert "--hash" in cmd
            assert result.startswith("swh:2:rev:")

