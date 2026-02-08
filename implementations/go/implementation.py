"""
Go SWHID Implementation Plugin

This module provides an interface to the Go SWHID implementation
for the testing harness.
"""

import subprocess
import os
import platform
import logging
import shutil
from typing import Optional

from harness.plugins.base import SwhidImplementation, ImplementationInfo, ImplementationCapabilities
from harness.utils.permissions import get_source_permissions, create_git_repo_with_permissions

logger = logging.getLogger(__name__)


def _normalize_go_swhid_output(raw: str) -> str:
    """Normalize Go CLI stdout: strip leading 'SWHID:' prefix and optional multi-line.

    The Go swhid CLI may print e.g. 'SWHID: swh:1:rev:...' or multi-line output.
    Returns a single line starting with 'swh:' for harness validation.
    """
    text = raw.strip()
    if not text:
        return text
    # Strip leading "SWHID:" (case-insensitive) and following whitespace
    if text.upper().startswith("SWHID:"):
        text = text[6:].lstrip()
    # If multi-line, take the first line that starts with swh:
    if "\n" in text:
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("SWHID:"):
                line = line[6:].lstrip()
            if line.startswith("swh:"):
                return line
        return text.splitlines()[0].strip()
    return text


class Implementation(SwhidImplementation):
    """Go SWHID implementation plugin."""

    def __init__(self):
        """Initialize Go implementation and find swhid command path."""
        super().__init__()
        self._swhid_path = None
        self._temp_dirs: list = []
        self._find_swhid_path()

    def _get_go_bin_dirs(self) -> list:
        """Return list of directories where go install puts binaries (GOBIN or GOPATH/bin)."""
        try:
            # Prefer go env for authoritative paths
            gobin_result = subprocess.run(
                ["go", "env", "GOBIN"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            gobin = (gobin_result.stdout or "").strip() if gobin_result.returncode == 0 else ""
            if gobin:
                return [gobin]

            gopath_result = subprocess.run(
                ["go", "env", "GOPATH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if gopath_result.returncode != 0 or not gopath_result.stdout:
                gopath = os.environ.get("GOPATH", os.path.join(os.path.expanduser("~"), "go"))
            else:
                gopath = (gopath_result.stdout or "").strip()
            # GOPATH can be a list (pathsep-separated, e.g. : on Unix, ; on Windows)
            return [os.path.join(p.strip(), "bin") for p in gopath.split(os.pathsep) if p.strip()]
        except Exception as e:
            logger.debug(f"Go: go env failed: {e}, using process env")
            gobin = os.environ.get("GOBIN")
            gopath = os.environ.get("GOPATH", os.path.join(os.path.expanduser("~"), "go"))
            if gobin:
                return [gobin]
            return [os.path.join(gopath, "bin")]

    def _find_swhid_path(self) -> Optional[str]:
        """Find the swhid command path and cache it.

        Uses package-manager (Go) paths only: SWHID_GO_PATH, then go env GOBIN/GOPATH
        bin dirs. Does not use PATH so we never pick the Rust or Ruby binary.
        """
        if self._swhid_path:
            return self._swhid_path

        logger.debug("Go: Starting swhid binary detection")
        is_windows = platform.system() == "Windows"
        binary_name = "swhid.exe" if is_windows else "swhid"

        # 1. Explicit override
        env_path = os.environ.get("SWHID_GO_PATH")
        if env_path and os.path.isfile(env_path):
            if self._verify_go_implementation(env_path):
                logger.info(f"Go: Found swhid via SWHID_GO_PATH: {env_path}")
                self._swhid_path = env_path
                return env_path

        # 2. Go toolchain bin dirs (go env GOBIN / GOPATH)
        for search_path in self._get_go_bin_dirs():
            candidate = os.path.join(search_path, binary_name)
            if os.path.isfile(candidate) and self._verify_go_implementation(candidate):
                logger.info(f"Go: Found swhid at: {candidate}")
                self._swhid_path = candidate
                return candidate

        # 3. Build from source if go is available
        if shutil.which("go"):
            try:
                result = subprocess.run(
                    ["go", "install", "github.com/andrew/swhid-go/cmd/swhid@latest"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    for search_path in self._get_go_bin_dirs():
                        candidate = os.path.join(search_path, binary_name)
                        if os.path.isfile(candidate) and self._verify_go_implementation(candidate):
                            logger.info(f"Go: Installed and found swhid at: {candidate}")
                            self._swhid_path = candidate
                            return candidate
            except Exception as e:
                logger.debug(f"Go: Failed to install from source: {e}")

        logger.warning("Go: Could not find swhid binary")
        return None

    def _verify_go_implementation(self, path: str) -> bool:
        """Verify that the binary is the Go implementation."""
        try:
            result = subprocess.run(
                [path, "--help"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=5
            )
            output = result.stdout + result.stderr
            # Check for Go-specific help text
            return "swhid-go" in output.lower() or "github.com/andrew/swhid-go" in output.lower() or (
                "content" in output and "directory" in output and "revision" in output
            )
        except Exception as e:
            logger.debug(f"Go: Verification failed: {e}")
            return False

    def get_info(self) -> ImplementationInfo:
        """Return implementation metadata."""
        return ImplementationInfo(
            name="go",
            version="0.1.0",
            language="go",
            description="Go SWHID implementation via swhid-go",
            git_repo="https://github.com/andrew/swhid-go",
            test_command="swhid --help",
            dependencies=["go"]
        )

    def is_available(self) -> bool:
        """Check if Go implementation is available."""
        logger.debug("Go: Checking availability")
        swhid_path = self._find_swhid_path()
        if not swhid_path:
            logger.warning("Go: Implementation not available - swhid binary not found")
            return False

        # Test that the command actually works
        try:
            result = subprocess.run(
                [swhid_path, "--help"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=5
            )
            if result.returncode == 0:
                logger.info(f"Go: Implementation is available at: {swhid_path}")
                return True
            else:
                logger.warning(f"Go: Test command failed with returncode {result.returncode}")
                return False
        except subprocess.TimeoutExpired:
            logger.warning("Go: Test command timed out")
            return False
        except Exception as e:
            logger.warning(f"Go: Exception testing binary: {e}")
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
                     commit: Optional[str] = None, tag: Optional[str] = None,
                     version: Optional[int] = None, hash_algo: Optional[str] = None) -> str:
        """Compute SWHID for a payload using the Go implementation.

        Note: version and hash_algo parameters are accepted for API compatibility
        but are ignored as the Go implementation only supports v1/SHA1.
        """

        swhid_path = self._find_swhid_path()
        if not swhid_path:
            raise RuntimeError("Go implementation not found (swhid-go not installed)")

        cmd = [swhid_path]

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
                if os.path.isdir(os.path.join(payload_path, ".git")):
                    cmd.extend(["snapshot", payload_path])
                else:
                    cmd.append("directory")
            else:
                raise ValueError(f"Cannot determine object type for {payload_path}")
        else:
            raise NotImplementedError(f"Go implementation doesn't support {obj_type} object type")

        # For content type, read from stdin
        if cmd[-1] == "content":
            try:
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
                    raise RuntimeError(f"Go implementation failed: {stderr}")

                output = result.stdout.decode('utf-8', errors='replace').strip()
                output = _normalize_go_swhid_output(output)
                if not output:
                    raise RuntimeError("No output from Go implementation")

                if not output.startswith("swh:"):
                    raise RuntimeError(f"Invalid SWHID format: {output}")

                return output

            except subprocess.TimeoutExpired:
                raise RuntimeError("Go implementation timed out")
            except FileNotFoundError as e:
                raise RuntimeError(f"File not found: {e}")
            except Exception as e:
                raise RuntimeError(f"Error running Go implementation: {e}")

        # For directory and git types, pass path as argument
        elif cmd[1] in ["directory", "revision", "release", "snapshot"]:
            if cmd[1] == "directory":
                # On Windows, preserve permissions via temp Git repo
                payload_path = self._ensure_permissions_preserved(payload_path)
                cmd.append(payload_path)

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
                    raise RuntimeError(f"Go implementation failed: {result.stderr}")

                output = result.stdout.strip()
                output = _normalize_go_swhid_output(output)
                if not output:
                    raise RuntimeError("No output from Go implementation")

                if not output.startswith("swh:"):
                    raise RuntimeError(f"Invalid SWHID format: {output}")

                return output

            except subprocess.TimeoutExpired:
                raise RuntimeError("Go implementation timed out")
            except FileNotFoundError:
                raise RuntimeError("Go implementation not found (swhid-go not installed)")
            except Exception as e:
                raise RuntimeError(f"Error running Go implementation: {e}")
            finally:
                self._cleanup_temp_dirs()

    def _ensure_permissions_preserved(self, source_path: str) -> str:
        """Ensure file permissions are preserved for external tools.

        On Windows, files lose executable bits when copied. This method creates
        a temporary Git repository with permissions set in the Git index.
        """
        import tempfile

        # On Unix-like systems, permissions are usually preserved
        if platform.system() != 'Windows':
            return source_path

        # Read source permissions using shared utility
        source_permissions = get_source_permissions(source_path)

        # If no executable files found, no need for temp repo
        if not any(source_permissions.values()):
            return source_path

        # Create temporary Git repository with permissions set in index
        temp_dir = tempfile.mkdtemp(prefix="swhid-go-")
        self._temp_dirs.append(temp_dir)

        target_path, success = create_git_repo_with_permissions(
            source_path, source_permissions, temp_dir, target_subdir="target"
        )

        if success:
            return target_path
        else:
            return source_path

    def _cleanup_temp_dirs(self):
        """Clean up temporary directories created for permission preservation."""
        for temp_dir in self._temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
            except Exception:
                pass
        self._temp_dirs.clear()
