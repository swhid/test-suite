"""
Rust SWHID Implementation Plugin

This module provides an interface to the Rust SWHID implementation
for the testing harness.
"""

import subprocess
import os
import sys
import logging
from pathlib import Path
from typing import Optional

from harness.plugins.base import SwhidImplementation, ImplementationInfo, ImplementationCapabilities
from harness.utils.permissions import get_source_permissions, create_git_repo_with_permissions

logger = logging.getLogger(__name__)

class Implementation(SwhidImplementation):
    """Rust SWHID implementation plugin."""
    
    def __init__(self) -> None:
        self._binary_path_cache: Optional[str] = None
        self._temp_dirs: list = []  # Track temp directories for cleanup
        self._content_command_format: Optional[str] = None  # Cache detected format: "positional" or "file_flag"
    
    def get_info(self) -> ImplementationInfo:
        """Return implementation metadata."""
        return ImplementationInfo(
            name="rust",
            version="1.0.0",
            language="rust",
            description="Rust SWHID implementation via cargo run",
            build_command="cargo build",
            test_command="cargo test",
            dependencies=["cargo", "rustc"]
        )
    
    def _resolve_binary_path_from_env(self) -> Optional[str]:
        """Resolve binary path from SWHID_RS_PATH environment variable.
        
        Handles three cases:
        1. Points to binary file: use it directly
        2. Points to binary directory: look for 'swhid' in that directory
        3. Points to project root: construct path to target/release/swhid
        
        Returns:
            Binary path if found, None otherwise
        """
        import platform
        
        env_path = os.environ.get("SWHID_RS_PATH")
        if not env_path:
            return None
        
        env_path_obj = Path(env_path)
        if not env_path_obj.exists():
            return None
        
        binary_name = "swhid.exe" if platform.system() == "Windows" else "swhid"
        
        # Case 1: Points to binary file
        if env_path_obj.is_file() and env_path_obj.name in ("swhid", "swhid.exe"):
            if os.access(env_path_obj, os.X_OK):
                return str(env_path_obj)
        
        # Case 2: Points to binary directory (e.g., /path/to/release/)
        if env_path_obj.is_dir():
            binary_path = env_path_obj / binary_name
            if binary_path.exists() and os.access(binary_path, os.X_OK):
                return str(binary_path)
        
        # Case 3: Points to project root (has Cargo.toml)
        cargo_toml = env_path_obj / "Cargo.toml"
        if cargo_toml.exists():
            binary_path = env_path_obj / "target" / "release" / binary_name
            if binary_path.exists() and os.access(binary_path, os.X_OK):
                return str(binary_path)
        
        return None

    def _get_cargo_bin_dirs(self) -> list:
        """Return list of directories where cargo install puts binaries."""
        import platform
        # CARGO_INSTALL_ROOT overrides install root; else CARGO_HOME/bin (default ~/.cargo/bin)
        install_root = os.environ.get("CARGO_INSTALL_ROOT")
        if install_root:
            return [os.path.join(os.path.normpath(install_root), "bin")]
        cargo_home = os.environ.get("CARGO_HOME", os.path.join(os.path.expanduser("~"), ".cargo"))
        return [os.path.join(os.path.normpath(cargo_home), "bin")]

    def _find_binary_in_cargo_bin_dirs(self) -> Optional[str]:
        """Look for swhid binary in CARGO_HOME/bin or CARGO_INSTALL_ROOT/bin. Return path or None."""
        import platform
        binary_name = "swhid.exe" if platform.system() == "Windows" else "swhid"
        for bin_dir in self._get_cargo_bin_dirs():
            candidate = os.path.join(bin_dir, binary_name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return None

    def is_available(self) -> bool:
        """Check if Rust implementation is available.

        Uses SWHID_RS_PATH, then CARGO_HOME/bin (or CARGO_INSTALL_ROOT/bin),
        then existing target/release binary if project root exists. Does not
        use PATH or trigger a build.
        """
        import platform
        try:
            binary_path = self._resolve_binary_path_from_env()
            if not binary_path:
                binary_path = self._find_binary_in_cargo_bin_dirs()
            if not binary_path:
                project_root = self._get_project_root()
                if project_root:
                    binary_name = "swhid.exe" if platform.system() == "Windows" else "swhid"
                    candidate = str(Path(project_root) / "target" / "release" / binary_name)
                    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                        binary_path = candidate
            if binary_path:
                result = subprocess.run(
                    [binary_path, "--help"],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=5
                )
                return result.returncode == 0
            return False
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
    
    def _build_binary(self, project_root: str) -> str:
        """Build the Rust binary with git feature enabled."""
        import platform
        # On Windows, the binary is swhid.exe, on Unix it's swhid
        binary_name = "swhid.exe" if platform.system() == "Windows" else "swhid"
        binary_path = Path(project_root) / "target" / "release" / binary_name
        build_cmd = ["cargo", "build", "--release", "--features", "git"]
        logger.info("Building Rust binary with git feature enabled...")
        
        result = subprocess.run(
            build_cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=300  # 5 minutes for build
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"Failed to build Rust binary: {error_msg}")
        
        if not binary_path.exists():
            raise RuntimeError(f"Binary not found after build: {binary_path}")
        
        # Cache binary path for reuse
        self._binary_path_cache = str(binary_path)
        return self._binary_path_cache

    def _ensure_binary_built(self) -> str:
        """Find the Rust swhid binary and return its path.

        Priority: SWHID_RS_PATH, then CARGO_HOME/bin (or CARGO_INSTALL_ROOT/bin),
        then build from source. Does not use PATH.
        """
        import platform

        if self._binary_path_cache:
            return self._binary_path_cache

        binary_path = self._resolve_binary_path_from_env()
        if not binary_path:
            binary_path = self._find_binary_in_cargo_bin_dirs()
        if binary_path:
            self._binary_path_cache = binary_path
            return binary_path

        project_root = self._get_project_root()
        if project_root:
            binary_name = "swhid.exe" if platform.system() == "Windows" else "swhid"
            binary_path = str(Path(project_root) / "target" / "release" / binary_name)
            if not Path(binary_path).exists():
                binary_path = self._build_binary(project_root)
            self._binary_path_cache = binary_path
            return binary_path

        raise RuntimeError(
            "Rust swhid binary not found. Set SWHID_RS_PATH, install via cargo install, "
            "or run from the swhid-rs project root."
        )
    
    def compute_swhid(self, payload_path: str, obj_type: Optional[str] = None,
                     commit: Optional[str] = None, tag: Optional[str] = None,
                     version: Optional[int] = None, hash_algo: Optional[str] = None) -> str:
        """Compute SWHID for a payload using the Rust implementation.
        
        Args:
            payload_path: Path to the payload
            obj_type: Object type (content, directory, revision, release, snapshot)
            commit: Optional commit SHA for revision SWHIDs
            tag: Optional tag name for release SWHIDs
            version: Optional SWHID version (1 for v1, 2 for v2). Defaults to 1.
            hash_algo: Optional hash algorithm ('sha1' or 'sha256'). Defaults to 'sha1'.
        """
        # Convert to absolute path
        payload_path = os.path.abspath(payload_path)
        
        # Auto-detect object type if not provided
        if obj_type is None:
            obj_type = self.detect_object_type(payload_path)
        
        # Get binary path (from PATH or build from source)
        binary_path = self._ensure_binary_built()
        
        # Build the command based on object type
        # Run the binary directly instead of cargo run
        cmd = [binary_path]
        
        # Add version/hash flags if specified
        if version == 2:
            cmd.extend(["--version", "2"])
        if hash_algo == "sha256":
            cmd.extend(["--hash", "sha256"])
        
        if obj_type == "content":
            # Try both formats to support both experimental and published versions
            # First try experimental format (positional), then fall back to published (--file)
            # Pass version and hash_algo to ensure flags are added to the command
            result_swhid = self._try_content_command(binary_path, payload_path, version, hash_algo)
            if result_swhid:
                return result_swhid
            
            # If both formats failed, build command with detected format and let error propagate
            content_format = self._detect_content_command_format(binary_path)
            if content_format == "file_flag":
                cmd.extend(["content", "--file", payload_path])
            else:
                cmd.extend(["content", payload_path])
        elif obj_type == "directory":
            # For directory: swhid dir <path>
            # Use new permission handling features from swhid-rs
            # Create a temporary Git repo with permissions set in index if needed
            payload_path, use_git_index = self._ensure_permissions_preserved(payload_path)
            cmd.extend(["dir", payload_path])
            
            # Use auto source when we created a Git repo - it will discover the repo by walking up
            # from the target subdirectory to find the repo root, then use Git index
            # This is necessary because we pass a subdirectory path, not the repo root
            if use_git_index:
                cmd.extend(["--permissions-source", "auto"])
                logger.info("Using --permissions-source auto (Git repo created, will discover and use Git index)")
            else:
                # Use auto-detection (will use Git index if repo found, otherwise filesystem)
                cmd.extend(["--permissions-source", "auto"])
                logger.debug("Using --permissions-source auto (will auto-detect)")
        elif obj_type == "snapshot":
            # For snapshot: swhid git snapshot <REPO> [COMMIT]
            # Note: requires --features git, so we need to ensure binary was built with git feature
            # Uses positional arguments, not --repo flag
            
            # Diagnostic: Compute SWHIDs for all branches and tags in the snapshot
            # This helps debug Windows-specific snapshot issues
            try:
                self._diagnose_snapshot_branches(payload_path, binary_path)
            except Exception as e:
                logger.warning(f"Snapshot diagnosis failed (non-critical): {e}")
                import traceback
                logger.debug(traceback.format_exc())
            
            cmd.extend(["git", "snapshot", payload_path])
        elif obj_type == "revision":
            # For revision: swhid git revision <REPO> [COMMIT]
            # This is for git repositories, payload_path should be the repo
            # Note: requires --features git
            # Uses positional arguments, not --repo flag
            # Resolve short SHA to full SHA if needed (Rust tool may not support short SHAs)
            resolved_commit = commit
            if commit and len(commit) < 40 and commit != "HEAD":
                # Use git rev-parse to resolve short SHA to full SHA
                try:
                    result = subprocess.run(
                        ["git", "rev-parse", commit],
                        cwd=payload_path,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='replace',
                        check=True,
                        timeout=5
                    )
                    resolved_commit = result.stdout.strip()
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    # If git rev-parse fails, use original commit (let Rust tool handle it)
                    resolved_commit = commit
            
            cmd.extend(["git", "revision", payload_path])
            if resolved_commit:
                cmd.append(resolved_commit)
        elif obj_type == "release":
            # For release: swhid git release <REPO> <TAG>
            # Uses positional arguments: <REPO> <TAG>
            if not tag:
                raise ValueError("Release SWHID requires a tag name")
            cmd.extend(["git", "release", payload_path, tag])
        else:
            raise ValueError(f"Unsupported object type: {obj_type}")
        
        # Run the command
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60  # Increased timeout since we're running binary directly (no compilation)
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip()
                
                # If content command failed, try the other format
                if obj_type == "content":
                    # Toggle format and try again
                    if self._content_command_format == "positional":
                        # Try with --file flag
                        alt_cmd = [binary_path]
                        # Add version/hash flags if specified
                        if version == 2:
                            alt_cmd.extend(["--version", "2"])
                        if hash_algo == "sha256":
                            alt_cmd.extend(["--hash", "sha256"])
                        alt_cmd.extend(["content", "--file", payload_path])
                        
                        alt_result = subprocess.run(
                            alt_cmd,
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='replace',
                            timeout=60
                        )
                        if alt_result.returncode == 0:
                            self._content_command_format = "file_flag"
                            output = alt_result.stdout.strip()
                            if output and output.startswith("swh:"):
                                return output.split('\n')[0].strip()
                    else:
                        # Try with positional argument
                        alt_cmd = [binary_path]
                        # Add version/hash flags if specified
                        if version == 2:
                            alt_cmd.extend(["--version", "2"])
                        if hash_algo == "sha256":
                            alt_cmd.extend(["--hash", "sha256"])
                        alt_cmd.extend(["content", payload_path])
                        
                        alt_result = subprocess.run(
                            alt_cmd,
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='replace',
                            timeout=60
                        )
                        if alt_result.returncode == 0:
                            self._content_command_format = "positional"
                            output = alt_result.stdout.strip()
                            if output and output.startswith("swh:"):
                                return output.split('\n')[0].strip()
                
                raise RuntimeError(f"Rust implementation failed: {error_msg}")
            
            # Parse the output - should be just the SWHID
            output = result.stdout.strip()
            if not output:
                raise RuntimeError("No output from Rust implementation")
            
            # The output should be just the SWHID
            swhid = output.split('\n')[0].strip()
            
            if not swhid.startswith("swh:"):
                raise RuntimeError(f"Invalid SWHID format: {swhid}")
            
            return swhid
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("Rust implementation timed out")
        except FileNotFoundError:
            raise RuntimeError("Rust implementation not found (cargo not available)")
        except Exception as e:
            raise RuntimeError(f"Error running Rust implementation: {e}")
        finally:
            # Cleanup temporary directories if created
            self._cleanup_temp_dirs()
    
    def _ensure_permissions_preserved(self, source_path: str) -> tuple[str, bool]:
        """Ensure file permissions are preserved for external tools.
        
        On Windows, files lose executable bits when copied. This method creates
        a temporary Git repository with permissions set in the Git index,
        which swhid-rs can read using --permissions-source git-index.
        
        Args:
            source_path: Path to source file or directory
        
        Returns:
            Tuple of (path_to_use, use_git_index_flag)
            - path_to_use: Path to use (may be temporary Git repo, or original)
            - use_git_index: True if we created a Git repo and should use --permissions-source git-index
        """
        import stat
        import tempfile
        import shutil
        import platform
        
        # On Unix-like systems, permissions are usually preserved from filesystem
        # swhid-rs can read them directly, so use auto-detection
        if platform.system() != 'Windows':
            return source_path, False
        
        # Read source permissions using shared utility
        source_permissions = get_source_permissions(source_path)
        
        # If no executable files found, no need for Git repo
        if not any(source_permissions.values()):
            return source_path, False
        
        # Create temporary Git repository with permissions set in index
        # Use shared utility to create Git repo with permissions
        temp_dir = tempfile.mkdtemp(prefix="swhid-rs-tools-")
        self._temp_dirs = getattr(self, '_temp_dirs', [])
        self._temp_dirs.append(temp_dir)
        
        target_path, success = create_git_repo_with_permissions(
            source_path, source_permissions, temp_dir, target_subdir="target"
        )
        
        if success:
            # Return the target subdirectory path - swhid-rs will discover Git repo by walking up
            return target_path, True
        else:
            # Fallback to original path if Git repo creation failed
            return source_path, False
    
    
    def _detect_content_command_format(self, binary_path: str) -> str:
        """Detect which command format the swhid binary supports for content.
        
        Returns:
            "positional" for experimental version (swhid content <path>)
            "file_flag" for published version (swhid content --file <path>)
        """
        # Use cached result if available
        if self._content_command_format is not None:
            return self._content_command_format
        
        # Try to detect by checking help output or trying a test command
        # First, try checking help for content command
        try:
            result = subprocess.run(
                [binary_path, "content", "--help"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=5
            )
            # If --help works, check if --file is mentioned in help
            if result.returncode == 0 and "--file" in result.stdout:
                self._content_command_format = "file_flag"
                logger.debug("Detected published version (--file flag supported)")
                return self._content_command_format
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass
        
        # If help check didn't work, try the experimental format first
        # (since that's what we're moving towards)
        # We'll fall back to --file format if positional fails during actual execution
        # For now, default to experimental (positional) format
        self._content_command_format = "positional"
        logger.debug("Defaulting to experimental version (positional argument)")
        return self._content_command_format
    
    def _try_content_command(self, binary_path: str, payload_path: str, 
                            version: Optional[int], hash_algo: Optional[str]) -> Optional[str]:
        """Try to execute content command and return SWHID if successful, None if format wrong.
        
        Uses cached format if available, otherwise tries both formats to detect the correct one.
        """
        cmd = [binary_path]
        
        # Add version/hash flags if specified
        if version == 2:
            cmd.extend(["--version", "2"])
        if hash_algo == "sha256":
            cmd.extend(["--hash", "sha256"])
        
        # If we have a cached format, try that first
        if self._content_command_format == "file_flag":
            # Try published format first (--file flag)
            test_cmd = cmd + ["content", "--file", payload_path]
            try:
                result = subprocess.run(
                    test_cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=10
                )
                if result.returncode == 0:
                    output = result.stdout.strip()
                    if output and output.startswith("swh:"):
                        return output.split('\n')[0].strip()
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                pass
            # If cached format failed, try the other one
            self._content_command_format = None
        
        # Try experimental format (positional argument) - either first time or as fallback
        test_cmd = cmd + ["content", payload_path]
        try:
            result = subprocess.run(
                test_cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=10
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                if output and output.startswith("swh:"):
                    # Success with experimental format
                    if self._content_command_format != "positional":
                        self._content_command_format = "positional"
                        logger.debug("Detected experimental version (positional argument works)")
                    return output.split('\n')[0].strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass
        
        # If experimental format failed and we don't have a cached format, try published format
        if self._content_command_format is None:
            test_cmd = cmd + ["content", "--file", payload_path]
            try:
                result = subprocess.run(
                    test_cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=10
                )
                if result.returncode == 0:
                    output = result.stdout.strip()
                    if output and output.startswith("swh:"):
                        # Success with published format
                        self._content_command_format = "file_flag"
                        logger.debug("Detected published version (--file flag works)")
                        return output.split('\n')[0].strip()
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                    pass
            
        return None
    
    def _get_project_root(self) -> Optional[str]:
        """
        Find the Rust project root directory.
        
        Search order:
        1. SWHID_RS_PATH environment variable (if it points to project root)
        2. Hardcoded known location (/home/dicosmo/code/swhid-rs)
        3. Search current directory and parents for Cargo.toml with name="swhid"
        """
        # 1. Check environment variable first (if it points to project root)
        env_path = os.environ.get("SWHID_RS_PATH")
        if env_path:
            env_path_obj = Path(env_path)
            if env_path_obj.exists():
                # Check if it's a project root (has Cargo.toml)
                cargo_toml = env_path_obj / "Cargo.toml"
                if cargo_toml.exists():
                    return str(env_path_obj)
        
        # 2. Try the known location (for backwards compatibility)
        known_path = Path("/home/dicosmo/code/swhid-rs")
        if known_path.exists() and (known_path / "Cargo.toml").exists():
            return str(known_path)
        
        # 3. Fallback: Look for Cargo.toml in current directory and parents
        # and check if it contains "swhid" in the name
        current = Path.cwd()
        
        for path in [current] + list(current.parents):
            cargo_toml = path / "Cargo.toml"
            if cargo_toml.exists():
                # Simple check: read first few lines to see if it's the swhid project
                try:
                    with open(cargo_toml, 'r') as f:
                        content = f.read(200)  # Read first 200 chars
                        if 'name = "swhid"' in content or 'name="swhid"' in content:
                            return str(path)
                except Exception:
                    pass
        
        return None
    
    def _diagnose_snapshot_branches(self, repo_path: str, binary_path: str):
        """Diagnostic: Compute and log SWHIDs for all branches and tags in a snapshot.
        
        This helps identify which branches/tags have different SWHIDs on Windows vs other platforms.
        """
        import subprocess
        import platform
        
        logger.info("=" * 70)
        logger.info("SNAPSHOT DIAGNOSIS: Computing SWHIDs for all branches and tags")
        logger.info("=" * 70)
        logger.info(f"Platform: {platform.system()}")
        logger.info(f"Repository: {repo_path}")
        logger.info("")
        
        # Get all branches
        try:
            result = subprocess.run(
                ["git", "branch", "-a"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=5
            )
            if result.returncode == 0:
                branches = [b.strip().replace('* ', '').replace('remotes/origin/', '') 
                           for b in result.stdout.strip().split('\n') if b.strip()]
                logger.info(f"Branches found: {branches}")
                
                # Compute revision SWHID for each branch
                logger.info("")
                logger.info("Branch Revision SWHIDs:")
                logger.info("-" * 70)
                for branch in branches:
                    if branch.startswith('remotes/'):
                        continue
                    try:
                        # Get commit hash
                        commit_result = subprocess.run(
                            ["git", "rev-parse", branch],
                            cwd=repo_path,
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='replace',
                            timeout=5
                        )
                        if commit_result.returncode == 0:
                            commit_hash = commit_result.stdout.strip()
                            # Compute revision SWHID
                            rev_cmd = [binary_path, "git", "revision", repo_path, commit_hash]
                            rev_result = subprocess.run(
                                rev_cmd,
                                capture_output=True,
                                text=True,
                                encoding='utf-8',
                                errors='replace',
                                timeout=10
                            )
                            if rev_result.returncode == 0:
                                rev_swhid = rev_result.stdout.strip()
                                logger.info(f"  {branch:20} -> {rev_swhid}")
                            else:
                                logger.warning(f"  {branch:20} -> Failed to compute revision SWHID: {rev_result.stderr[:100]}")
                    except Exception as e:
                        logger.debug(f"  {branch:20} -> Error: {e}")
        except Exception as e:
            logger.debug(f"Failed to get branches: {e}")
        
        # Get all tags
        try:
            result = subprocess.run(
                ["git", "tag", "-l"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=5
            )
            if result.returncode == 0:
                tags = [t.strip() for t in result.stdout.strip().split('\n') if t.strip()]
                logger.info("")
                logger.info("Tag Release SWHIDs:")
                logger.info("-" * 70)
                for tag in tags:
                    try:
                        # Get tag object hash
                        tag_result = subprocess.run(
                            ["git", "rev-parse", tag],
                            cwd=repo_path,
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='replace',
                            timeout=5
                        )
                        if tag_result.returncode == 0:
                            tag_hash = tag_result.stdout.strip()
                            # Check if it's an annotated tag or lightweight
                            tag_type_result = subprocess.run(
                                ["git", "cat-file", "-t", tag],
                                cwd=repo_path,
                                capture_output=True,
                                text=True,
                                encoding='utf-8',
                                errors='replace',
                                timeout=5
                            )
                            tag_type = tag_type_result.stdout.strip() if tag_type_result.returncode == 0 else "unknown"
                            
                            # Compute release SWHID
                            rel_cmd = [binary_path, "git", "release", repo_path, tag]
                            rel_result = subprocess.run(
                                rel_cmd,
                                capture_output=True,
                                text=True,
                                encoding='utf-8',
                                errors='replace',
                                timeout=10
                            )
                            if rel_result.returncode == 0:
                                rel_swhid = rel_result.stdout.strip()
                                logger.info(f"  {tag:20} ({tag_type:8}) -> {rel_swhid}")
                            else:
                                logger.warning(f"  {tag:20} -> Failed to compute release SWHID: {rel_result.stderr[:100]}")
                    except Exception as e:
                        logger.debug(f"  {tag:20} -> Error: {e}")
        except Exception as e:
            logger.debug(f"Failed to get tags: {e}")
        
        logger.info("")
        logger.info("=" * 70)
    
    def _cleanup_temp_dirs(self):
        """Clean up temporary directories created for permission preservation."""
        import shutil
        temp_dirs = getattr(self, '_temp_dirs', [])
        for temp_dir in temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
            except Exception:
                pass
        self._temp_dirs.clear()
