#!/usr/bin/env python3
"""
pygit2-based SWHID runner using libgit2 library.

This runner uses pygit2 (Python bindings for libgit2) to compute Git-style hashes,
which should match our SWHID implementation for content and directory objects.
Note: Git doesn't support snapshot objects, so those are skipped.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
import pygit2


def compute_swhid(payload_path: str, obj_type: Optional[str] = None) -> str:
    """
    Compute SWHID using pygit2 (libgit2).
    
    Args:
        payload_path: Path to the payload file/directory
        obj_type: Object type (content, directory, etc.)
    
    Returns:
        SWHID string in format swh:1:obj_type:hash
    """
    payload_path = os.path.abspath(payload_path)
    
    if not os.path.exists(payload_path):
        raise FileNotFoundError(f"Payload not found: {payload_path}")
    
    # Auto-detect object type if not provided
    if obj_type is None:
        obj_type = detect_object_type(payload_path)
    
    # Skip snapshot objects as Git doesn't support them
    if obj_type == "snapshot":
        raise NotImplementedError("Git doesn't support snapshot objects")
    
    try:
        if obj_type == "content":
            return compute_content_swhid(payload_path)
        elif obj_type == "directory":
            return compute_directory_swhid(payload_path)
        elif obj_type == "revision":
            return compute_revision_swhid(payload_path)
        elif obj_type == "release":
            return compute_release_swhid(payload_path)
        else:
            raise ValueError(f"Unsupported object type: {obj_type}")
    except Exception as e:
        raise RuntimeError(f"Failed to compute Git SWHID: {e}")


def detect_object_type(payload_path: str) -> str:
    """Detect object type from payload path."""
    if os.path.isfile(payload_path):
        return "content"
    elif os.path.isdir(payload_path):
        return "directory"
    else:
        raise ValueError(f"Cannot detect object type for: {payload_path}")


def compute_content_swhid(file_path: str) -> str:
    """Compute content SWHID using pygit2 blob creation."""
    with open(file_path, 'rb') as f:
        content = f.read()
    
    # Create a temporary repository to use pygit2
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = os.path.join(temp_dir, "repo")
        repo = pygit2.init_repository(repo_path)
        
        # Create blob object
        blob_id = repo.create_blob(content)
        blob_id_str = str(blob_id)
        
        return f"swh:1:cnt:{blob_id_str}"


def compute_directory_swhid(dir_path: str) -> str:
    """Compute directory SWHID using pygit2 tree creation."""
    # Create a temporary Git repository
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = os.path.join(temp_dir, "repo")
        repo = pygit2.init_repository(repo_path)
        
        # Copy the directory contents to the repo
        target_path = os.path.join(repo_path, "target")
        if os.path.isdir(dir_path):
            shutil.copytree(dir_path, target_path)
        else:
            # If it's a file, create a directory and put the file in it
            os.makedirs(target_path)
            shutil.copy2(dir_path, target_path)
        
        # Create tree for the target directory
        tree_id = create_git_tree_pygit2(repo, target_path)
        tree_id_str = str(tree_id)
        
        return f"swh:1:dir:{tree_id_str}"


def create_git_tree_pygit2(repo, dir_path):
    """Recursively create Git tree objects for a directory using pygit2."""
    tree_builder = repo.TreeBuilder()
    
    # Get all entries in the directory
    entries = []
    for item in os.listdir(dir_path):
        item_path = os.path.join(dir_path, item)
        
        if os.path.isfile(item_path):
            # Handle file
            with open(item_path, 'rb') as f:
                content = f.read()
            
            blob_id = repo.create_blob(content)
            entries.append((item, pygit2.GIT_FILEMODE_BLOB, blob_id))
            
        elif os.path.isdir(item_path):
            # Handle subdirectory
            sub_tree_id = create_git_tree_pygit2(repo, item_path)
            entries.append((item, pygit2.GIT_FILEMODE_TREE, sub_tree_id))
    
    # Sort entries (Git requires sorted tree entries)
    entries.sort(key=lambda x: x[0])
    
    # Add entries to tree builder
    for name, mode, oid in entries:
        tree_builder.insert(name, oid, mode)
    
    # Create tree object
    tree_id = tree_builder.write()
    
    return tree_id


def compute_revision_swhid(repo_path: str) -> str:
    """Compute revision SWHID using pygit2 commit hash."""
    # This would require parsing Git repository and finding the HEAD commit
    # For now, we'll skip this as it's complex and not needed for basic testing
    raise NotImplementedError("Git revision SWHID computation not implemented")


def compute_release_swhid(repo_path: str) -> str:
    """Compute release SWHID using pygit2 tag hash."""
    # This would require parsing Git repository and finding tags
    # For now, we'll skip this as it's complex and not needed for basic testing
    raise NotImplementedError("Git release SWHID computation not implemented")


def compute_swhid_detailed(payload_path: str, obj_type: Optional[str] = None, 
                          archive: bool = False) -> str:
    """
    Compute SWHID with detailed parameters (for compatibility with other runners).
    
    Args:
        payload_path: Path to the payload
        obj_type: Object type
        archive: Whether this is an archive (not supported in Git)
    
    Returns:
        SWHID string
    """
    if archive:
        raise NotImplementedError("Git doesn't support archive processing")
    
    return compute_swhid(payload_path, obj_type)


def compute_swhid_auto(payload_path: str) -> str:
    """Auto-detect object type and compute SWHID."""
    return compute_swhid(payload_path)


def compute_swhid_simple(payload_path: str, obj_type: str) -> str:
    """Compute SWHID with explicit object type."""
    return compute_swhid(payload_path, obj_type)


if __name__ == "__main__":
    # Simple CLI interface for testing
    if len(sys.argv) < 2:
        print("Usage: python pygit2_runner.py <payload_path> [obj_type]")
        sys.exit(1)
    
    payload_path = sys.argv[1]
    obj_type = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        swhid = compute_swhid(payload_path, obj_type)
        print(swhid)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1) 