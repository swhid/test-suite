"""
Ruby SWHID Implementation Plugin

This module provides an interface to the Ruby SWHID implementation
for the testing harness.
"""

import subprocess
import os
from typing import Optional

from harness.plugins.base import SwhidImplementation, ImplementationInfo, ImplementationCapabilities

class Implementation(SwhidImplementation):
    """Ruby SWHID implementation plugin."""

    def get_info(self) -> ImplementationInfo:
        """Return implementation metadata."""
        return ImplementationInfo(
            name="ruby",
            version="0.3.0",
            language="ruby",
            description="Ruby SWHID implementation via swhid gem",
            test_command="swhid --help",
            dependencies=["swhid"]
        )

    def is_available(self) -> bool:
        """Check if Ruby implementation is available."""
        try:
            # Check if swhid gem is installed and CLI is available
            result = subprocess.run(
                ["swhid", "help"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return False

    def get_capabilities(self) -> ImplementationCapabilities:
        """Return implementation capabilities."""
        return ImplementationCapabilities(
            supported_types=["cnt", "dir", "rev", "rel", "snp"],
            supported_qualifiers=["origin", "visit", "anchor", "path", "lines", "bytes"],
            api_version="1.0",
            max_payload_size_mb=1000,
            supports_unicode=True,
            supports_percent_encoding=True
        )

    def compute_swhid(self, payload_path: str, obj_type: Optional[str] = None,
                     commit: Optional[str] = None, tag: Optional[str] = None) -> str:
        """Compute SWHID for a payload using the Ruby implementation."""

        # Build the command
        cmd = ["swhid"]

        # Map object types to swhid CLI commands
        if obj_type == "content" or obj_type == "cnt":
            cmd.append("content")
        elif obj_type == "directory" or obj_type == "dir":
            cmd.append("directory")
        elif obj_type == "revision" or obj_type == "rev":
            cmd.extend(["revision", payload_path])
            if commit:
                cmd.append(commit)
        elif obj_type == "release" or obj_type == "rel":
            cmd.extend(["release", payload_path])
            if tag:
                cmd.append(tag)
        elif obj_type == "snapshot" or obj_type == "snp":
            cmd.extend(["snapshot", payload_path])
        elif obj_type is None or obj_type == "auto":
            # Auto-detect based on path
            if os.path.isfile(payload_path):
                cmd.append("content")
            elif os.path.isdir(payload_path):
                # Check if it's a git repository
                if os.path.isdir(os.path.join(payload_path, ".git")):
                    cmd.extend(["snapshot", payload_path])
                else:
                    cmd.append("directory")
            else:
                raise ValueError(f"Cannot determine object type for {payload_path}")
        else:
            raise NotImplementedError(f"Ruby implementation doesn't support {obj_type} object type")

        # For content type, read from stdin
        if cmd[-1] == "content":
            try:
                # Read file and pipe to stdin
                with open(payload_path, 'rb') as f:
                    content = f.read()

                result = subprocess.run(
                    cmd,
                    input=content,
                    capture_output=True,
                    timeout=30
                )

                if result.returncode != 0:
                    stderr = result.stderr.decode('utf-8', errors='replace')
                    raise RuntimeError(f"Ruby implementation failed: {stderr}")

                # Parse the output
                output = result.stdout.decode('utf-8', errors='replace').strip()
                if not output:
                    raise RuntimeError("No output from Ruby implementation")

                if not output.startswith("swh:"):
                    raise RuntimeError(f"Invalid SWHID format: {output}")

                return output

            except subprocess.TimeoutExpired:
                raise RuntimeError("Ruby implementation timed out")
            except FileNotFoundError as e:
                raise RuntimeError(f"File not found: {e}")
            except Exception as e:
                raise RuntimeError(f"Error running Ruby implementation: {e}")

        # For directory and git types, pass path as argument
        elif cmd[1] in ["directory", "revision", "release", "snapshot"]:
            if cmd[1] == "directory":
                cmd.append(payload_path)

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode != 0:
                    raise RuntimeError(f"Ruby implementation failed: {result.stderr}")

                # Parse the output
                output = result.stdout.strip()
                if not output:
                    raise RuntimeError("No output from Ruby implementation")

                if not output.startswith("swh:"):
                    raise RuntimeError(f"Invalid SWHID format: {output}")

                return output

            except subprocess.TimeoutExpired:
                raise RuntimeError("Ruby implementation timed out")
            except FileNotFoundError:
                raise RuntimeError("Ruby implementation not found (swhid gem not installed)")
            except Exception as e:
                raise RuntimeError(f"Error running Ruby implementation: {e}")
