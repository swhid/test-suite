"""
Git SWHID Implementation Plugin (dulwich)

This module provides an interface to Git-based SWHID computation using dulwich.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from harness.plugins.base import SwhidImplementation, ImplementationInfo, ImplementationCapabilities

try:
    import dulwich.objects
    import dulwich.repo
    DULWICH_AVAILABLE = True
except ImportError:
    DULWICH_AVAILABLE = False

class Implementation(SwhidImplementation):
    """Git SWHID implementation plugin using dulwich."""
    
    def get_info(self) -> ImplementationInfo:
        """Return implementation metadata."""
        return ImplementationInfo(
            name="git",
            version="1.0.0",
            language="python",
            description="Git SWHID implementation using dulwich library",
            dependencies=["dulwich"]
        )
    
    def is_available(self) -> bool:
        """Check if Git implementation is available."""
        return DULWICH_AVAILABLE
    
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
        """Compute SWHID using Git's hashing algorithm via dulwich."""
        if not DULWICH_AVAILABLE:
            raise RuntimeError("dulwich library not available")
        
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
        """Compute content SWHID using Git blob hash."""
        with open(file_path, 'rb') as f:
            content = f.read()
        
        # Create Git blob object
        blob = dulwich.objects.Blob()
        blob.data = content
        
        # Get the hash
        blob_id = blob.id.decode('ascii')
        
        return f"swh:1:cnt:{blob_id}"
    
    def _compute_directory_swhid(self, dir_path: str) -> str:
        """Compute directory SWHID using Git tree hash."""
        # Create a temporary Git repository
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = os.path.join(temp_dir, "repo")
            os.makedirs(repo_path)
            
            # Initialize Git repository
            repo = dulwich.repo.Repo.init(repo_path)
            
            # Copy the directory contents maintaining the structure
            if os.path.isdir(dir_path):
                # Copy the entire directory structure, ignoring symlinks
                for root, dirs, files in os.walk(dir_path):
                    # Create corresponding directory in repo
                    rel_path = os.path.relpath(root, dir_path)
                    repo_dir = os.path.join(repo_path, rel_path)
                    os.makedirs(repo_dir, exist_ok=True)
                    
                    # Copy files and symlinks
                    for file in files:
                        src_file = os.path.join(root, file)
                        dst_file = os.path.join(repo_dir, file)
                        
                        # Handle symlinks - copy them as symlinks
                        # On Windows, symlinks require special privileges
                        if os.path.islink(src_file):
                            try:
                                link_target = os.readlink(src_file)
                                # On Windows, check if we can create symlinks
                                import platform
                                if platform.system() == 'Windows':
                                    # Try to create symlink, fall back to copying if it fails
                                    try:
                                        os.symlink(link_target, dst_file)
                                    except (OSError, NotImplementedError):
                                        # If symlink creation fails, copy the target file instead
                                        # This is a limitation on Windows without admin/dev mode
                                        if os.path.exists(link_target):
                                            shutil.copy2(link_target, dst_file)
                                        else:
                                            # If target doesn't exist, create empty file
                                            # This matches Git's behavior for broken symlinks
                                            with open(dst_file, 'wb') as f:
                                                f.write(link_target.encode('utf-8'))
                                else:
                                    os.symlink(link_target, dst_file)
                            except (OSError, NotImplementedError):
                                # If symlink operations fail, skip it
                                continue
                        # Copy regular files
                        elif os.path.isfile(src_file):
                            shutil.copy2(src_file, dst_file)
            else:
                # If it's a file, copy it to the repo root
                shutil.copy2(dir_path, repo_path)
            
            # Create tree for the root directory
            # Pass source directory for permission preservation (critical on Windows)
            # Read source permissions once and pass to tree creation
            source_permissions = self._get_source_permissions(dir_path) if os.path.isdir(dir_path) else {}
            tree = self._create_git_tree(repo, repo_path, repo_root=repo_path, source_dir=dir_path, source_permissions=source_permissions)
            
            tree_id_str = tree.id.decode('ascii')
            return f"swh:1:dir:{tree_id_str}"
    
    def _get_source_permissions(self, source_dir):
        """Read intended permissions from source files.
        
        This preserves the executable bit information from source files,
        which is critical on Windows where filesystem permissions may not
        be preserved during copy operations.
        
        Args:
            source_dir: Original source directory path
        
        Returns:
            Dict mapping relative file paths to executable status
        """
        import stat
        permissions = {}
        if not os.path.exists(source_dir) or not os.path.isdir(source_dir):
            return permissions
        
        # Walk the source directory and read permissions
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    # Calculate relative path from source_dir
                    rel_path = os.path.relpath(file_path, source_dir)
                    # Normalize path separators to forward slashes for cross-platform consistency
                    # This ensures lookup works correctly when paths are normalized in _create_git_tree
                    rel_path = rel_path.replace(os.sep, '/')
                    stat_info = os.stat(file_path)
                    is_executable = bool(stat_info.st_mode & stat.S_IEXEC)
                    permissions[rel_path] = is_executable
                except (OSError, ValueError):
                    # If we can't stat or compute relative path, skip
                    pass
        return permissions
    
    def _create_git_tree(self, repo, dir_path, repo_root=None, source_dir=None, source_permissions=None):
        """Recursively create Git tree objects for a directory.
        
        Args:
            repo: Dulwich repository object
            dir_path: Directory path in the temporary repo
            repo_root: Root path of the temporary repo (for calculating relative paths)
            source_dir: Original source directory (for calculating relative paths)
            source_permissions: Dict of relative paths to executable status
        """
        # If repo_root not provided, use dir_path as root (for backward compatibility)
        if repo_root is None:
            repo_root = dir_path
        tree = dulwich.objects.Tree()
        
        # Use provided source_permissions or read from source_dir
        if source_permissions is None and source_dir:
            source_permissions = self._get_source_permissions(source_dir)
        elif source_permissions is None:
            source_permissions = {}
        
        # Get all entries in the directory
        entries = []
        for item in os.listdir(dir_path):
            # Skip .git directory (Git automatically excludes it)
            if item == '.git':
                continue
                
            item_path = os.path.join(dir_path, item)
            
            if os.path.islink(item_path):
                # Handle symlink - Git stores symlinks as blob with mode 0o120000
                link_target = os.readlink(item_path)
                blob = dulwich.objects.Blob()
                blob.data = link_target.encode('utf-8')
                repo.object_store.add_object(blob)
                entries.append((item.encode(), 0o120000, blob.id))
                
            elif os.path.isfile(item_path):
                # Handle file - check if executable
                with open(item_path, 'rb') as f:
                    content = f.read()
                
                blob = dulwich.objects.Blob()
                blob.data = content
                repo.object_store.add_object(blob)
                
                # Determine if file is executable
                # Priority: 1. Source permissions, 2. Filesystem detection
                import stat
                import platform
                
                # Calculate relative path for permission lookup
                # We need to map from repo path back to source path
                rel_path = None
                if source_dir:
                    try:
                        # Calculate relative path from repo root to current file
                        # repo_root is the root of the repo
                        # item_path is the full path to the file in repo
                        # We need the relative path from repo root
                        repo_rel_path = os.path.relpath(item_path, repo_root)
                        # This should match the relative path in source_permissions
                        rel_path = repo_rel_path.replace(os.sep, '/')  # Normalize separators
                    except ValueError:
                        # If paths are on different drives (Windows), use item name
                        rel_path = item
                else:
                    rel_path = item
                
                is_executable = False
                if rel_path and rel_path in source_permissions:
                    # Use source permission (most reliable, especially on Windows)
                    is_executable = source_permissions[rel_path]
                else:
                    # Fall back to filesystem detection
                    file_mode = os.stat(item_path).st_mode
                    if platform.system() == 'Windows':
                        # On Windows, check file extension for common executables
                        ext = os.path.splitext(item_path)[1].lower()
                        executable_extensions = {'.exe', '.bat', '.cmd', '.com', '.ps1', '.sh'}
                        is_executable = ext in executable_extensions
                        # Also check if file has .sh extension (shell script)
                        if not is_executable and item.endswith('.sh'):
                            is_executable = True
                    else:
                        # On Unix-like systems, check executable bit
                        is_executable = bool(file_mode & stat.S_IEXEC)
                
                mode = 0o100755 if is_executable else 0o100644
                entries.append((item.encode(), mode, blob.id))
                
            elif os.path.isdir(item_path):
                # Handle subdirectory
                sub_tree = self._create_git_tree(repo, item_path, repo_root=repo_root, source_dir=source_dir, source_permissions=source_permissions)
                entries.append((item.encode(), 0o40000, sub_tree.id))
        
        # Sort entries (Git requires sorted tree entries)
        entries.sort(key=lambda x: x[0])
        
        # Add entries to tree
        for name, mode, sha in entries:
            tree.add(name, mode, sha)
        
        # Add tree to object store
        repo.object_store.add_object(tree)
        
        return tree
    
    def _compute_revision_swhid(self, repo_path: str, commit: Optional[str] = None) -> str:
        """Compute revision SWHID using Git commit hash."""
        # Open the repository
        repo = dulwich.repo.Repo(repo_path)
        
        # Default to HEAD if no commit specified
        if commit is None:
            commit = "HEAD"
        
        # Resolve commit reference
        commit_sha = None
        
        if commit == "HEAD":
            # Try HEAD first
            try:
                head_ref = repo.refs[b"HEAD"]
                # HEAD might be a symbolic ref (bytes starting with "refs/") or direct SHA
                if isinstance(head_ref, bytes) and head_ref.startswith(b"refs/"):
                    # Symbolic ref - resolve it
                    commit_sha = repo.refs[head_ref]
                else:
                    # Direct SHA
                    commit_sha = head_ref
            except KeyError:
                # Try to get from refs/heads/main
                try:
                    commit_sha = repo.refs[b"refs/heads/main"]
                except KeyError:
                    # Get first branch
                    branches = [ref for ref in repo.refs.keys() if ref.startswith(b"refs/heads/")]
                    if branches:
                        commit_sha = repo.refs[branches[0]]
                    else:
                        raise ValueError("No commits found in repository")
        elif len(commit) == 40:
            # Full SHA - dulwich expects hex-encoded bytes (40 bytes), not raw bytes (20 bytes)
            try:
                # Convert hex string to hex-encoded bytes (what dulwich expects)
                commit_sha = commit.encode('ascii')
                # Verify it exists and is a commit
                commit_obj = repo.get_object(commit_sha)
                # dulwich returns type_name as bytes, not string
                if commit_obj.type_name != b"commit":
                    raise ValueError(f"Object '{commit}' is not a commit")
            except (KeyError, ValueError, AssertionError) as e:
                raise ValueError(f"Commit '{commit}' not found: {e}")
        elif len(commit) == 7:
            # Short SHA - search for matching commit by walking commit graph from all refs
            # This is more reliable than searching object store
            from dulwich.walk import Walker
            
            # Try all refs and walk their commit history
            for ref in repo.refs.keys():
                try:
                    ref_sha = repo.refs[ref]
                    # Walk commits from this ref
                    walker = Walker(repo.object_store, [ref_sha], follow=True)
                    for entry in walker:
                        # Convert commit SHA to hex string
                        if isinstance(entry.commit.id, bytes):
                            commit_hex = entry.commit.id.decode('ascii')
                        elif hasattr(entry.commit.id, 'hex'):
                            commit_hex = entry.commit.id.hex()
                        else:
                            commit_hex = str(entry.commit.id)
                        
                        if commit_hex.startswith(commit):
                            commit_sha = entry.commit.id
                            break
                    
                    if commit_sha is not None:
                        break
                except:
                    continue
            
            if commit_sha is None:
                raise ValueError(f"Could not resolve short SHA '{commit}'")
        else:
            # Try as ref name (branch name)
            try:
                # Try refs/heads/<name>
                commit_sha = repo.refs[b"refs/heads/" + commit.encode()]
            except KeyError:
                try:
                    # Try as full ref
                    commit_sha = repo.refs[commit.encode()]
                except KeyError:
                    raise ValueError(f"Commit/ref '{commit}' not found")
        
        # Verify commit_sha is set
        if commit_sha is None:
            raise ValueError(f"Could not resolve commit '{commit}'")
        
        # Get commit object to verify it's a commit
        try:
            commit_obj = repo.get_object(commit_sha)
        except KeyError:
            raise ValueError(f"Commit '{commit}' not found in repository")
        
        # Check if it's a commit (dulwich uses bytes for type_name)
        type_name = commit_obj.type_name
        if isinstance(type_name, bytes):
            type_name = type_name.decode('ascii')
        if type_name != "commit":
            raise ValueError(f"Object '{commit}' is not a commit (type: {type_name})")
        
        # Convert to hex string
        # dulwich returns SHA1 objects or bytes (which are hex strings as bytes)
        # Check bytes first, as bytes objects also have a .hex() method
        if isinstance(commit_sha, bytes):
            # Bytes are already hex-encoded as ASCII, just decode
            commit_id = commit_sha.decode('ascii')
        elif hasattr(commit_sha, 'hex'):
            commit_id = commit_sha.hex()
        else:
            commit_id = str(commit_sha)
        
        return f"swh:1:rev:{commit_id}"
    
    def _compute_release_swhid(self, repo_path: str, tag: Optional[str] = None) -> str:
        """Compute release SWHID using Git tag hash."""
        if tag is None:
            raise ValueError("Tag name is required for release SWHID computation")
        
        # Open the repository
        repo = dulwich.repo.Repo(repo_path)
        
        # Resolve tag reference
        tag_ref = b"refs/tags/" + tag.encode()
        try:
            tag_sha = repo.refs[tag_ref]
        except KeyError:
            raise ValueError(f"Tag '{tag}' not found")
        
        # Get the tag object
        tag_obj = repo.get_object(tag_sha)
        
        # Check if it's an annotated tag (tag object) or lightweight tag (commit)
        type_name = tag_obj.type_name
        if isinstance(type_name, bytes):
            type_name = type_name.decode('ascii')
        
        if type_name == "tag":
            # Annotated tag - use the tag object hash
            if isinstance(tag_sha, bytes):
                # Bytes are already hex-encoded as ASCII, just decode
                tag_id = tag_sha.decode('ascii')
            elif hasattr(tag_sha, 'hex'):
                tag_id = tag_sha.hex()
            else:
                tag_id = str(tag_sha)
            return f"swh:1:rel:{tag_id}"
        else:
            # Lightweight tag - points to a commit, not a tag object
            raise ValueError(f"Tag '{tag}' is a lightweight tag, not an annotated tag. Releases require annotated tags.")
