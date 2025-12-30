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

logger = logging.getLogger(__name__)

class Implementation(SwhidImplementation):
    """Rust SWHID implementation plugin."""
    
    def __init__(self) -> None:
        self._git_build_ready = False
        self._default_build_ready = False
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
    
    def is_available(self) -> bool:
        """Check if Rust implementation is available."""
        try:
            # Check if cargo is available
            result = subprocess.run(
                ["cargo", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return False
            
            # Check if swhid-rs project exists and is accessible
            project_root = self._get_project_root()
            if not project_root:
                return False
            
            # Verify the project can be accessed (Cargo.toml exists and is readable)
            cargo_toml = Path(project_root) / "Cargo.toml"
            if not cargo_toml.exists():
                return False
            
            # Optionally: Check if project can be built (but this is slow, so skip for now)
            # We'll discover build issues when actually trying to use it
            # For now, just verify the project structure exists
            
            return True
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
    
    def _build_binary(self, project_root: str, use_git_feature: bool) -> str:
        """Build the Rust binary, optionally enabling the git feature."""
        import platform
        # On Windows, the binary is swhid.exe, on Unix it's swhid
        binary_name = "swhid.exe" if platform.system() == "Windows" else "swhid"
        binary_path = Path(project_root) / "target" / "release" / binary_name
        build_cmd = ["cargo", "build", "--release"]
        if use_git_feature:
            build_cmd.extend(["--features", "git"])
            logger.info("Building Rust binary with git feature enabled...")
        else:
            logger.info("Building Rust binary without git feature...")
        
        result = subprocess.run(
            build_cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
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

    def _ensure_binary_built(self, project_root: str, needs_git: bool = False) -> str:
        """Ensure the Rust binary is built (with git feature if needed) and return its path."""
        import platform
        binary_name = "swhid.exe" if platform.system() == "Windows" else "swhid"
        binary_path = self._binary_path_cache or str(Path(project_root) / "target" / "release" / binary_name)
        
        # If git feature is required but we haven't built with it yet, build now
        if needs_git and not self._git_build_ready:
            binary_path = self._build_binary(project_root, use_git_feature=True)
            self._git_build_ready = True
            # Building with git feature also produces a usable binary for non-git operations
            self._default_build_ready = True
            return binary_path
        
        # If binary missing entirely or never built, build without git feature
        if not Path(binary_path).exists() or not self._default_build_ready:
            binary_path = self._build_binary(project_root, use_git_feature=needs_git)
            self._default_build_ready = True
            if needs_git:
                self._git_build_ready = True
            return binary_path
        
        return binary_path
    
    def compute_swhid(self, payload_path: str, obj_type: Optional[str] = None,
                     commit: Optional[str] = None, tag: Optional[str] = None) -> str:
        """Compute SWHID for a payload using the Rust implementation."""
        # Convert to absolute path
        payload_path = os.path.abspath(payload_path)
        
        # Auto-detect object type if not provided
        if obj_type is None:
            obj_type = self.detect_object_type(payload_path)
        
        # Get project root (should be /home/dicosmo/code/swhid-rs)
        project_root = self._get_project_root()
        if not project_root:
            raise RuntimeError("Could not find Rust project root (/home/dicosmo/code/swhid-rs)")
        
        # Determine if we need git feature
        needs_git = obj_type in ("snapshot", "revision", "release")
        
        # Ensure binary is built (check and build if needed)
        binary_path = self._ensure_binary_built(project_root, needs_git=needs_git)
        
        # Build the command based on object type
        # Run the binary directly instead of cargo run
        cmd = [binary_path]
        
        if obj_type == "content":
            # Try both formats to support both experimental and published versions
            # First try experimental format (positional), then fall back to published (--file)
            result_swhid = self._try_content_command(binary_path, payload_path, None, None)
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
            # On Windows, we need to preserve file permissions before calling the tool
            # Create a temporary copy with correct permissions
            payload_path = self._ensure_permissions_preserved(payload_path)
            cmd.extend(["dir", payload_path])
        elif obj_type == "snapshot":
            # For snapshot: swhid git snapshot <REPO> [COMMIT]
            # Note: requires --features git, so we need to ensure binary was built with git feature
            # Uses positional arguments, not --repo flag
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
                cwd=project_root,
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
                        # Note: version and hash_algo not supported on main branch
                        alt_cmd.extend(["content", "--file", payload_path])
                        
                        alt_result = subprocess.run(
                            alt_cmd,
                            capture_output=True,
                            text=True,
                            cwd=project_root,
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
                        # Note: version and hash_algo not supported on main branch
                        alt_cmd.extend(["content", payload_path])
                        
                        alt_result = subprocess.run(
                            alt_cmd,
                            capture_output=True,
                            text=True,
                            cwd=project_root,
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
    
    def _ensure_permissions_preserved(self, source_path: str) -> str:
        """Ensure file permissions are preserved for external tools.
        
        On Windows, files lose executable bits when copied. This method creates
        a temporary copy with correct permissions set, which external tools
        (like the Rust swhid binary) can read correctly.
        
        Args:
            source_path: Path to source file or directory
        
        Returns:
            Path to use (may be temporary copy on Windows, or original on Unix)
        """
        import stat
        import tempfile
        import shutil
        import platform
        
        # On Unix-like systems, permissions are usually preserved
        # Only create temp copy on Windows
        if platform.system() != 'Windows':
            return source_path
        
        # Read source permissions
        # On Windows, check Git index first as filesystem may not preserve executable bits
        source_permissions = {}
        
        # On Windows, try to read permissions from Git index first
        # This is more reliable than filesystem permissions
        try:
            # Get absolute path to source_path
            abs_source_path = os.path.abspath(source_path)
            # Get repository root (walk up to find .git)
            repo_root = abs_source_path
            if os.path.isdir(repo_root):
                check_path = repo_root
            else:
                check_path = os.path.dirname(repo_root)
            
            while check_path != os.path.dirname(check_path):
                if os.path.exists(os.path.join(check_path, '.git')):
                    repo_root = check_path
                    break
                check_path = os.path.dirname(check_path)
            else:
                repo_root = None
            
            # If we found a repo, check Git index for permissions
            if repo_root:
                if os.path.isdir(source_path):
                    for root, dirs, files in os.walk(source_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            rel_path = os.path.relpath(file_path, source_path)
                            
                            # Get path relative to repo root
                            try:
                                repo_rel_path = os.path.relpath(file_path, repo_root)
                                # Check Git index
                                result = subprocess.run(
                                    ['git', 'ls-files', '--stage', repo_rel_path],
                                    cwd=repo_root,
                                    capture_output=True,
                                    text=True,
                                    timeout=2
                                )
                                if result.returncode == 0 and result.stdout.strip():
                                    # Format: <mode> <sha> <stage> <path>
                                    parts = result.stdout.strip().split()
                                    if parts:
                                        git_mode = parts[0]
                                        # Mode is octal string, e.g., '100755' for executable
                                        is_executable = git_mode.endswith('755')
                                        source_permissions[rel_path] = is_executable
                                        continue
                            except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
                                pass
                elif os.path.isfile(source_path):
                    try:
                        repo_rel_path = os.path.relpath(source_path, repo_root)
                        result = subprocess.run(
                            ['git', 'ls-files', '--stage', repo_rel_path],
                            cwd=repo_root,
                            capture_output=True,
                            text=True,
                            timeout=2
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            parts = result.stdout.strip().split()
                            if parts:
                                git_mode = parts[0]
                                is_executable = git_mode.endswith('755')
                                source_permissions['.'] = is_executable
                    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
                        pass
        except Exception:
            # If Git check fails, fall back to filesystem
            pass
        
        # Fall back to filesystem permissions (works on Unix, or if Git check failed)
        if os.path.isdir(source_path):
            for root, dirs, files in os.walk(source_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, source_path)
                    
                    # Skip if we already got permission from Git index
                    if rel_path in source_permissions:
                        continue
                    
                    try:
                        stat_info = os.stat(file_path)
                        is_executable = bool(stat_info.st_mode & stat.S_IEXEC)
                        source_permissions[rel_path] = is_executable
                    except OSError:
                        source_permissions[rel_path] = False
        elif os.path.isfile(source_path):
            # Skip if we already got permission from Git index
            if '.' not in source_permissions:
                try:
                    stat_info = os.stat(source_path)
                    is_executable = bool(stat_info.st_mode & stat.S_IEXEC)
                    source_permissions['.'] = is_executable  # Single file, use '.' as key
                except OSError:
                    source_permissions['.'] = False
        
        # If no executable files found, no need for temp copy
        if not any(source_permissions.values()):
            return source_path
        
        # Create temporary copy with permissions
        temp_dir = tempfile.mkdtemp(prefix="swhid-rs-tools-")
        self._temp_dirs = getattr(self, '_temp_dirs', [])
        self._temp_dirs.append(temp_dir)
        
        if os.path.isdir(source_path):
            # Copy directory
            temp_path = os.path.join(temp_dir, os.path.basename(source_path) or "dir")
            shutil.copytree(source_path, temp_path, symlinks=True)
            
            # Apply permissions
            for rel_path, is_executable in source_permissions.items():
                target_file = os.path.join(temp_path, rel_path)
                if os.path.exists(target_file):
                    try:
                        current_stat = os.stat(target_file)
                        if is_executable:
                            os.chmod(target_file, current_stat.st_mode | stat.S_IEXEC)
                        else:
                            os.chmod(target_file, current_stat.st_mode & ~stat.S_IEXEC)
                    except OSError:
                        # On Windows, chmod might not work - that's okay
                        pass
            
            return temp_path
        else:
            # Copy single file
            temp_path = os.path.join(temp_dir, os.path.basename(source_path))
            shutil.copy2(source_path, temp_path)
            
            # Apply permission
            if source_permissions.get('.', False):
                try:
                    current_stat = os.stat(temp_path)
                    os.chmod(temp_path, current_stat.st_mode | stat.S_IEXEC)
                except OSError:
                    pass
            
            return temp_path
    
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
        1. SWHID_RS_PATH environment variable (if set)
        2. Hardcoded known location (/home/dicosmo/code/swhid-rs)
        3. Search current directory and parents for Cargo.toml with name="swhid"
        """
        # 1. Check environment variable first (most flexible)
        env_path = os.environ.get("SWHID_RS_PATH")
        if env_path:
            env_path_obj = Path(env_path)
            if env_path_obj.exists() and (env_path_obj / "Cargo.toml").exists():
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
