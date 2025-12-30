"""
Python SWHID Implementation Plugin

This module provides an interface to the Python SWHID implementation
for the testing harness.
"""

import subprocess
import os
import sys
from pathlib import Path
from typing import Optional

from harness.plugins.base import SwhidImplementation, ImplementationInfo, ImplementationCapabilities

class Implementation(SwhidImplementation):
    """Python SWHID implementation plugin."""
    
    def get_info(self) -> ImplementationInfo:
        """Return implementation metadata."""
        return ImplementationInfo(
            name="python",
            version="1.0.0",
            language="python",
            description="Python SWHID implementation via swh.model.cli",
            test_command="python3 -m swh.model.cli --help",
            dependencies=["swh.model"]
        )
    
    def is_available(self) -> bool:
        """Check if Python implementation is available."""
        try:
            # Check if swh.model is available
            result = subprocess.run(
                ["python3", "-c", "import swh.model"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=5
            )
            if result.returncode != 0:
                return False
            
            # Check if CLI is available
            result = subprocess.run(
                ["python3", "-m", "swh.model.cli", "--help"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=10
            )
            return result.returncode == 0
            
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return False
    
    def get_capabilities(self) -> ImplementationCapabilities:
        """Return implementation capabilities."""
        return ImplementationCapabilities(
            supported_types=["cnt", "dir", "rev", "rel", "snp"],
            supported_qualifiers=["origin", "visit", "anchor", "path", "lines"],
            api_version="1.0",
            max_payload_size_mb=1000,
            supports_unicode=True,
            supports_percent_encoding=True
        )
    
    def compute_swhid(self, payload_path: str, obj_type: Optional[str] = None,
                     commit: Optional[str] = None, tag: Optional[str] = None,
                     version: Optional[int] = None, hash_algo: Optional[str] = None) -> str:
        """Compute SWHID for a payload using the Python implementation.
        
        Note: version and hash_algo parameters are accepted for API compatibility
        but are ignored as the Python implementation only supports v1/SHA1.
        """
        # Python swh.model.cli doesn't support revision/release types
        # Skip these as unsupported
        if obj_type in ("revision", "release"):
            raise NotImplementedError(f"Python implementation doesn't support {obj_type} object type")
        
        # Build the command
        cmd = ["python3", "-m", "swh.model.cli"]
        
        # Add object type if specified
        if obj_type and obj_type != "auto":
            cmd.extend(["--type", obj_type])
        
        # Ensure snapshot type is passed for git repos
        if obj_type is None:
            obj_type = self.detect_object_type(payload_path)
            if obj_type and obj_type != "auto":
                # Reset and add again to ensure correct flag ordering
                cmd = ["python3", "-m", "swh.model.cli", "--type", obj_type]
        
        # Add the payload path
        cmd.append(payload_path)
        
        # Run the command
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=30
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"Python implementation failed: {result.stderr}")
            
            # Parse the output
            output = result.stdout.strip()
            if not output:
                raise RuntimeError("No output from Python implementation")
            
            # The output format is: SWHID\tfilename (optional)
            # We want just the SWHID part
            swhid = output.split('\t')[0].strip()
            
            if not swhid.startswith("swh:"):
                raise RuntimeError(f"Invalid SWHID format: {swhid}")
            
            return swhid
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("Python implementation timed out")
        except FileNotFoundError:
            raise RuntimeError("Python implementation not found (swh.model not available)")
        except Exception as e:
            raise RuntimeError(f"Error running Python implementation: {e}")
