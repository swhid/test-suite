"""
Git Command SWHID Implementation Plugin

This module provides an interface to Git-based SWHID computation using git commands.
"""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from harness.plugins.base import SwhidImplementation, ImplementationInfo, ImplementationCapabilities

class Implementation(SwhidImplementation):
    """Git command SWHID implementation plugin."""
    
    def get_info(self) -> ImplementationInfo:
        """Return implementation metadata."""
        return ImplementationInfo(
            name="git-cmd",
            version="1.0.0",
            language="shell",
            description="Git SWHID implementation using git command directly",
            dependencies=["git"]
        )
    
    def is_available(self) -> bool:
        """Check if Git command implementation is available."""
        try:
            result = subprocess.run(
                ["git", "--version"],
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
            supported_qualifiers=["origin", "visit", "anchor", "path", "lines"],
            api_version="1.0",
            max_payload_size_mb=1000,
            supports_unicode=True,
            supports_percent_encoding=True
        )
    
    def compute_swhid(self, payload_path: str, obj_type: Optional[str] = None,
                     commit: Optional[str] = None, tag: Optional[str] = None) -> str:
        """Compute SWHID using Git command directly."""
        payload_path = os.path.abspath(payload_path)
        
        if not os.path.exists(payload_path):
            raise FileNotFoundError(f"Payload not found: {payload_path}")
        
        # Auto-detect object type if not provided
        if obj_type is None:
            obj_type = self.detect_object_type(payload_path)
        
        # Skip snapshot objects as Git doesn't support them
        if obj_type == "snapshot":
            raise NotImplementedError("Git doesn't support snapshot objects")
        
        try:
            if obj_type == "content":
                return self._compute_content_swhid(payload_path)
            elif obj_type == "directory":
                return self._compute_directory_swhid(payload_path)
            elif obj_type == "revision":
                return self._compute_revision_swhid(payload_path, commit=commit)
            elif obj_type == "release":
                return self._compute_release_swhid(payload_path, tag=tag)
            else:
                raise ValueError(f"Unsupported object type: {obj_type}")
        except Exception as e:
            raise RuntimeError(f"Failed to compute Git SWHID: {e}")
    
    def _compute_content_swhid(self, file_path: str) -> str:
        """Compute content SWHID using git hash-object command."""
        try:
            # Use --no-filters to bypass line ending conversion (important for Windows)
            # This ensures CRLF line endings are preserved as-is
            result = subprocess.run(
                ["git", "hash-object", "--no-filters", file_path],
                capture_output=True,
                text=True,
                check=True
            )
            blob_id = result.stdout.strip()
            return f"swh:1:cnt:{blob_id}"
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"git hash-object failed: {e}")
    
    def _get_source_permissions(self, source_dir):
        """Read intended permissions from source files before copying.
        
        This preserves the executable bit information from source files,
        which is critical on Windows where filesystem permissions may not
        be preserved during copy operations.
        
        On Windows, we check the Git index for the intended permissions,
        as the filesystem may not preserve executable bits.
        """
        import stat
        import platform
        
        permissions = {}
        
        # On Windows, try to read permissions from Git index first
        # This is more reliable than filesystem permissions
        if platform.system() == 'Windows':
            try:
                # Get absolute path to source_dir
                abs_source_dir = os.path.abspath(source_dir)
                # Get repository root (walk up to find .git)
                repo_root = abs_source_dir
                while repo_root != os.path.dirname(repo_root):
                    if os.path.exists(os.path.join(repo_root, '.git')):
                        break
                    repo_root = os.path.dirname(repo_root)
                else:
                    repo_root = None
                
                # If we found a repo, check Git index for permissions
                if repo_root:
                    for root, dirs, files in os.walk(source_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            rel_path = os.path.relpath(file_path, source_dir)
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
                                    timeout=2
                                )
                                if result.returncode == 0 and result.stdout.strip():
                                    # Format: <mode> <sha> <stage> <path>
                                    parts = result.stdout.strip().split()
                                    if parts:
                                        git_mode = parts[0]
                                        # Mode is octal string, e.g., '100755' for executable
                                        is_executable = git_mode.endswith('755')
                                        permissions[rel_path] = is_executable
                                        continue
                            except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
                                pass
            except Exception:
                # If Git check fails, fall back to filesystem
                pass
        
        # Fall back to filesystem permissions (works on Unix, or if Git check failed)
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, source_dir)
                
                # Skip if we already got permission from Git index
                if rel_path in permissions:
                    continue
                
                try:
                    # Normalize path separators to forward slashes for cross-platform consistency
                    rel_path = rel_path.replace(os.sep, '/')
                    stat_info = os.stat(file_path)
                    is_executable = bool(stat_info.st_mode & stat.S_IEXEC)
                    permissions[rel_path] = is_executable
                except OSError:
                    # If we can't stat the file, assume not executable
                    permissions[rel_path] = False
        
        return permissions
    
    def _compute_directory_swhid(self, dir_path: str) -> str:
        """Compute directory SWHID using git commands."""
        # Read source permissions BEFORE copying (critical for Windows)
        # This preserves the intended permissions from source files
        source_permissions = self._get_source_permissions(dir_path) if os.path.isdir(dir_path) else {}
        
        # Create a temporary Git repository
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = os.path.join(temp_dir, "repo")
            os.makedirs(repo_path)
            
            # Initialize Git repository
            subprocess.run(["git", "init"], cwd=repo_path, check=True, 
                         capture_output=True)
            
            # Configure Git for SWHID testing (preserve line endings and permissions)
            # This is critical for cross-platform consistency
            subprocess.run(["git", "config", "core.autocrlf", "false"], 
                         cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "core.filemode", "true"], 
                         cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "core.precomposeunicode", "false"], 
                         cwd=repo_path, check=True, capture_output=True)
            
            # Copy the directory contents maintaining the structure
            # Use a target subdirectory to avoid conflicts with .git
            target_path = os.path.join(repo_path, "target")
            if os.path.isdir(dir_path):
                # Copy the entire directory structure, preserving symlinks
                # On Windows, symlinks may not be supported, so handle gracefully
                try:
                    shutil.copytree(dir_path, target_path, symlinks=True)
                except (OSError, NotImplementedError) as e:
                    # If symlink copy fails (e.g., on Windows without privileges),
                    # fall back to copying without symlinks
                    # This is a known limitation on Windows
                    shutil.copytree(dir_path, target_path, symlinks=False)
            else:
                # If it's a file, create target directory and copy file
                os.makedirs(target_path)
                shutil.copy2(dir_path, target_path)
            
            # Move contents from target to repo root (Git tree is for repo root)
            # We need to move the contents, not the directory itself
            for item in os.listdir(target_path):
                src = os.path.join(target_path, item)
                dst = os.path.join(repo_path, item)
                if os.path.isdir(src):
                    shutil.move(src, dst)
                else:
                    shutil.move(src, dst)
            os.rmdir(target_path)
            
            # Add all files to Git
            # Note: We configure core.autocrlf=false in the repo, so line endings are preserved
            # The --no-filters flag is only valid for git hash-object, not git add
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True,
                         capture_output=True)
            
            # Apply executable bits based on source permissions
            # This is critical on Windows where filesystem permissions may not be preserved
            # We use git update-index to set executable bits, which works cross-platform
            for rel_path, is_executable in source_permissions.items():
                if is_executable:
                    # Check if file exists in repo (handle nested paths)
                    file_path = os.path.join(repo_path, rel_path)
                    if os.path.exists(file_path):
                        try:
                            subprocess.run(
                                ["git", "update-index", "--chmod=+x", rel_path],
                                cwd=repo_path, check=True, capture_output=True
                            )
                        except subprocess.CalledProcessError:
                            # If update-index fails, continue (file might not be in index)
                            pass
            
            # Get the tree hash for the root directory
            result = subprocess.run(
                ["git", "write-tree"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            tree_id = result.stdout.strip()
            
            return f"swh:1:dir:{tree_id}"
    
    def _compute_revision_swhid(self, repo_path: str, commit: Optional[str] = None) -> str:
        """Compute revision SWHID using Git commit hash."""
        # Default to HEAD if no commit specified
        if commit is None:
            commit = "HEAD"
        
        # Get the commit hash
        result = subprocess.run(
            ["git", "rev-parse", commit],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        commit_id = result.stdout.strip()
        
        return f"swh:1:rev:{commit_id}"
    
    def _compute_release_swhid(self, repo_path: str, tag: Optional[str] = None) -> str:
        """Compute release SWHID using Git tag hash."""
        if tag is None:
            raise ValueError("Tag name is required for release SWHID computation")
        
        # Get the tag object hash (for annotated tags) or commit hash (for lightweight tags)
        # First check if it's an annotated tag
        result = subprocess.run(
            ["git", "cat-file", "-t", tag],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        tag_type = result.stdout.strip()
        
        if tag_type == "tag":
            # Annotated tag - get the tag object hash
            result = subprocess.run(
                ["git", "rev-parse", tag],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            tag_id = result.stdout.strip()
            return f"swh:1:rel:{tag_id}"
        else:
            # Lightweight tag - points to a commit, not a tag object
            # For releases, we need the tag object, so this is not a valid release
            raise ValueError(f"Tag '{tag}' is a lightweight tag, not an annotated tag. Releases require annotated tags.")
