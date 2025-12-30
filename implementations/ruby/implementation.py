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
    
    def __init__(self):
        """Initialize Ruby implementation and find swhid command path."""
        super().__init__()
        self._swhid_path = None
        self._temp_dirs: list = []  # Track temp directories for cleanup
        self._find_swhid_path()
    
    def _find_swhid_path(self) -> Optional[str]:
        """Find the swhid command path and cache it."""
        if self._swhid_path:
            return self._swhid_path
        
        import shutil
        
        # First, try to find swhid command in PATH
        swhid_path = shutil.which("swhid")
        if swhid_path:
            self._swhid_path = swhid_path
            return swhid_path
        
        # If not in PATH, try common gem locations
        import os
        import glob
        home = os.path.expanduser("~")
        gem_paths = [
            os.path.join(home, ".gem", "ruby", "*", "bin", "swhid"),
            os.path.join(home, ".local", "share", "gem", "ruby", "*", "bin", "swhid"),
        ]
        
        # Also try system gem locations
        try:
            import subprocess as sp
            gem_env_result = sp.run(
                ["ruby", "-e", "puts Gem.user_dir"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=2
            )
            if gem_env_result.returncode == 0:
                gem_dir = gem_env_result.stdout.strip()
                if gem_dir:
                    gem_paths.append(os.path.join(gem_dir, "bin", "swhid"))
        except Exception:
            pass
        
        # Try to find swhid in any of these locations
        for pattern in gem_paths:
            matches = glob.glob(pattern)
            for swhid_cmd in matches:
                if os.path.isfile(swhid_cmd) and os.access(swhid_cmd, os.X_OK):
                    self._swhid_path = swhid_cmd
                    return swhid_cmd
        
        return None

    def get_info(self) -> ImplementationInfo:
        """Return implementation metadata."""
        return ImplementationInfo(
            name="ruby",
            version="0.3.1",
            language="ruby",
            description="Ruby SWHID implementation via swhid gem",
            test_command="swhid --help",
            dependencies=["swhid"]
        )

    def is_available(self) -> bool:
        """Check if Ruby implementation is available."""
        swhid_path = self._find_swhid_path()
        if not swhid_path:
            return False
        
        # Test that the command actually works
        try:
            result = subprocess.run(
                [swhid_path, "help"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, Exception):
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
        """Compute SWHID for a payload using the Ruby implementation.
        
        Note: version and hash_algo parameters are accepted for API compatibility
        but are ignored as the Ruby implementation only supports v1/SHA1.
        """
        
        # Get the swhid command path
        swhid_path = self._find_swhid_path()
        if not swhid_path:
            raise RuntimeError("Ruby implementation not found (swhid gem not installed)")
        
        # Build the command
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
                # On Windows, we need to preserve file permissions before calling the tool
                # Create a temporary copy with correct permissions
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
            finally:
                # Cleanup temporary directories if created
                self._cleanup_temp_dirs()
    
    def _ensure_permissions_preserved(self, source_path: str) -> str:
        """Ensure file permissions are preserved for external tools.
        
        On Windows, files lose executable bits when copied. This method creates
        a temporary copy with correct permissions set, which external tools
        (like the Ruby swhid gem) can read correctly.
        
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
                            # Normalize path separators to forward slashes for cross-platform consistency
                            rel_path = rel_path.replace(os.sep, '/')
                            
                            # Get path relative to repo root
                            try:
                                repo_rel_path = os.path.relpath(file_path, repo_root)
                                # Normalize for Git command (Git uses forward slashes)
                                repo_rel_path = repo_rel_path.replace(os.sep, '/')
                                # Check Git index
                                result = subprocess.run(
                                    ['git', 'ls-files', '--stage', repo_rel_path],
                                    cwd=repo_root,
                                    capture_output=True,
                                    text=True,
                                    encoding='utf-8',
                                    errors='replace',
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
                            encoding='utf-8',
                            errors='replace',
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
                    # Normalize path separators to forward slashes for cross-platform consistency
                    rel_path = rel_path.replace(os.sep, '/')
                    
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
        temp_dir = tempfile.mkdtemp(prefix="swhid-ruby-")
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
    
    def _cleanup_temp_dirs(self):
        """Clean up temporary directories created for permission preservation."""
        import shutil
        for temp_dir in self._temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
            except Exception:
                pass
        self._temp_dirs.clear()
