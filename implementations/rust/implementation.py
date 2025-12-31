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
        # Directory operations may need git feature for --permissions-source git-index
        # (though auto-detection will work without it if no Git repo is found)
        needs_git = obj_type in ("snapshot", "revision", "release") or obj_type == "directory"
        
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
            # Use new permission handling features from swhid-rs
            # Create a temporary Git repo with permissions set in index if needed
            payload_path, use_git_index = self._ensure_permissions_preserved(payload_path)
            cmd.extend(["dir", payload_path])
            
            # Use auto-detection which will discover Git repo by walking up
            # This works even when payload_path is a subdirectory of the Git repo
            # Auto will use Git index if repo found, otherwise filesystem
            cmd.extend(["--permissions-source", "auto"])
            if use_git_index:
                logger.info("Using --permissions-source auto (Git repo created, will use Git index)")
            else:
                logger.debug("Using --permissions-source auto (will auto-detect)")
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
        
        # Read source permissions from filesystem or existing Git repo
        source_permissions = self._get_source_permissions(source_path)
        
        # If no executable files found, no need for Git repo
        if not any(source_permissions.values()):
            return source_path, False
        
        # Create temporary Git repository with permissions set in index
        # This is the recommended approach: use Git index which swhid-rs can read
        temp_dir = tempfile.mkdtemp(prefix="swhid-rs-tools-")
        self._temp_dirs = getattr(self, '_temp_dirs', [])
        self._temp_dirs.append(temp_dir)
        
        repo_path = os.path.join(temp_dir, "repo")
        os.makedirs(repo_path)
        
        # Initialize Git repository
        subprocess.run(
            ["git", "init"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            encoding='utf-8',
            errors='replace'
        )
        
        # Configure Git for SWHID testing (preserve line endings and permissions)
        subprocess.run(
            ["git", "config", "core.autocrlf", "false"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            encoding='utf-8',
            errors='replace'
        )
        subprocess.run(
            ["git", "config", "core.filemode", "true"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            encoding='utf-8',
            errors='replace'
        )
        
        # Copy directory or file directly into repo root
        # swhid-rs with --permissions-source git-index uses Repository::open(root)
        # which expects root to be the repository root (where .git is)
        # So we copy files directly into repo root and pass repo_path to swhid-rs
        if os.path.isdir(source_path):
            # Copy directory contents directly into repo root (not a subdirectory)
            # This way, when we pass repo_path to swhid-rs, it can find .git immediately
            for item in os.listdir(source_path):
                src_item = os.path.join(source_path, item)
                dst_item = os.path.join(repo_path, item)
                if os.path.isdir(src_item):
                    shutil.copytree(src_item, dst_item, symlinks=True)
                else:
                    shutil.copy2(src_item, dst_item)
            
            # Add all files to Git index
            subprocess.run(
                ["git", "add", "."],
                cwd=repo_path,
                check=True,
                capture_output=True,
                encoding='utf-8',
                errors='replace'
            )
            
            # Apply executable permissions to Git index
            for rel_path, is_executable in source_permissions.items():
                if is_executable:
                    # Path relative to source directory, which is now relative to repo root
                    git_path = rel_path.replace(os.sep, '/')
                    try:
                        subprocess.run(
                            ["git", "update-index", "--chmod=+x", git_path],
                            cwd=repo_path,
                            check=True,
                            capture_output=True,
                            encoding='utf-8',
                            errors='replace'
                        )
                    except subprocess.CalledProcessError:
                        # If update-index fails, continue (file might not be in index)
                        pass
            
            # Return the repo root path - swhid-rs can find .git here
            return repo_path, True
        else:
            # Copy single file
            target_file = os.path.join(repo_path, os.path.basename(source_path))
            shutil.copy2(source_path, target_file)
            
            # Add to Git index
            file_name = os.path.basename(source_path)
            subprocess.run(
                ["git", "add", file_name],
                cwd=repo_path,
                check=True,
                capture_output=True,
                encoding='utf-8',
                errors='replace'
            )
            
            # Apply executable permission if needed
            if source_permissions.get('.', False):
                try:
                    subprocess.run(
                        ["git", "update-index", "--chmod=+x", file_name],
                        cwd=repo_path,
                        check=True,
                        capture_output=True,
                        encoding='utf-8',
                        errors='replace'
                    )
                except subprocess.CalledProcessError:
                    pass
            
            return target_file, True
    
    def _get_source_permissions(self, source_path: str) -> dict:
        """Read source file permissions.
        
        Returns a dictionary mapping relative paths to executable status.
        """
        import stat
        source_permissions = {}
        
        # First, try to read from existing Git repository if available
        try:
            abs_source_path = os.path.abspath(source_path)
            check_path = abs_source_path if os.path.isdir(abs_source_path) else os.path.dirname(abs_source_path)
            repo_root = None
            
            while check_path != os.path.dirname(check_path):
                if os.path.exists(os.path.join(check_path, '.git')):
                    repo_root = check_path
                    break
                check_path = os.path.dirname(check_path)
            
            if repo_root:
                # Read permissions from Git index
                if os.path.isdir(source_path):
                    for root, dirs, files in os.walk(source_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            rel_path = os.path.relpath(file_path, source_path)
                            rel_path = rel_path.replace(os.sep, '/')
                            
                            try:
                                repo_rel_path = os.path.relpath(file_path, repo_root)
                                repo_rel_path = repo_rel_path.replace(os.sep, '/')
                                result = subprocess.run(
                                    ['git', 'ls-files', '--stage', repo_rel_path],
                                    cwd=repo_root,
                                    capture_output=True,
                                    text=True,
                                    timeout=2,
                                    encoding='utf-8',
                                    errors='replace'
                                )
                                if result.returncode == 0 and result.stdout.strip():
                                    parts = result.stdout.strip().split()
                                    if parts:
                                        git_mode = parts[0]
                                        is_executable = git_mode.endswith('755')
                                        source_permissions[rel_path] = is_executable
                                        continue
                            except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
                                pass
                elif os.path.isfile(source_path):
                    try:
                        repo_rel_path = os.path.relpath(source_path, repo_root)
                        repo_rel_path = repo_rel_path.replace(os.sep, '/')
                        result = subprocess.run(
                            ['git', 'ls-files', '--stage', repo_rel_path],
                            cwd=repo_root,
                            capture_output=True,
                            text=True,
                            timeout=2,
                            encoding='utf-8',
                            errors='replace'
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
            pass
        
        # Fall back to filesystem permissions
        if os.path.isdir(source_path):
            for root, dirs, files in os.walk(source_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, source_path)
                    rel_path = rel_path.replace(os.sep, '/')
                    
                    if rel_path not in source_permissions:
                        try:
                            stat_info = os.stat(file_path)
                            is_executable = bool(stat_info.st_mode & stat.S_IEXEC)
                            source_permissions[rel_path] = is_executable
                        except OSError:
                            source_permissions[rel_path] = False
        elif os.path.isfile(source_path):
            if '.' not in source_permissions:
                try:
                    stat_info = os.stat(source_path)
                    is_executable = bool(stat_info.st_mode & stat.S_IEXEC)
                    source_permissions['.'] = is_executable
                except OSError:
                    source_permissions['.'] = False
        
        return source_permissions
    
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
