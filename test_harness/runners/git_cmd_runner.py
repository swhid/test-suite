#!/usr/bin/env python3
"""
Git command-based SWHID runner.

This runner uses the git command directly to compute Git-style hashes,
which should match our SWHID implementation for content and directory objects.
Note: Git doesn't support snapshot objects, so those are skipped.
"""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Dict, Any


def compute_swhid(payload_path: str, obj_type: Optional[str] = None) -> str:
    """
    Compute SWHID using Git command directly.
    
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
    """Compute content SWHID using git hash-object command."""
    try:
        result = subprocess.run(
            ["git", "hash-object", file_path],
            capture_output=True,
            text=True,
            check=True
        )
        blob_id = result.stdout.strip()
        return f"swh:1:cnt:{blob_id}"
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"git hash-object failed: {e}")


def compute_directory_swhid(dir_path: str) -> str:
    """Compute directory SWHID using git commands."""
    # Create a temporary Git repository
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = os.path.join(temp_dir, "repo")
        os.makedirs(repo_path)
        
        # Initialize Git repository
        subprocess.run(["git", "init"], cwd=repo_path, check=True)
        
        # Copy the directory contents maintaining the structure
        if os.path.isdir(dir_path):
            # Copy the entire directory structure
            shutil.copytree(dir_path, repo_path, dirs_exist_ok=True)
        else:
            # If it's a file, copy it to the repo root
            shutil.copy2(dir_path, repo_path)
        
        # Add all files to Git
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
        
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


def compute_revision_swhid(repo_path: str) -> str:
    """Compute revision SWHID using Git commit hash."""
    # This would require parsing Git repository and finding the HEAD commit
    # For now, we'll skip this as it's complex and not needed for basic testing
    raise NotImplementedError("Git revision SWHID computation not implemented")


def compute_release_swhid(repo_path: str) -> str:
    """Compute release SWHID using Git tag hash."""
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
        print("Usage: python git_cmd_runner.py <payload_path> [obj_type]")
        sys.exit(1)
    
    payload_path = sys.argv[1]
    obj_type = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        swhid = compute_swhid(payload_path, obj_type)
        print(swhid)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1) 