#!/usr/bin/env python3
"""
Rust SWHID Implementation Runner

This module provides an interface to the Rust SWHID implementation
for the testing harness.
"""

import subprocess
import os
import tempfile
import shutil
from pathlib import Path
from typing import Optional

def compute_swhid_detailed(payload_path: str, obj_type: Optional[str] = None, 
                          archive: bool = False) -> str:
    """
    Compute SWHID for a payload using the Rust implementation.
    
    Args:
        payload_path: Path to the payload file/directory
        obj_type: Object type (content, directory, snapshot, auto)
        archive: Whether to treat file as archive
    
    Returns:
        SWHID string
    """
    # Convert to absolute path
    payload_path = os.path.abspath(payload_path)
    
    # Build the command
    cmd = ["cargo", "run", "--"]
    
    # Add object type if specified
    if obj_type:
        cmd.extend(["--obj-type", obj_type])
    
    # Add archive flag if requested
    if archive:
        cmd.append("--archive")
    
    # Add the payload path
    cmd.append(payload_path)
    
    # Run the command
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),  # Go to project root
            timeout=30
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Rust implementation failed: {result.stderr}")
        
        # Parse the output
        output = result.stdout.strip()
        if not output:
            raise RuntimeError("No output from Rust implementation")
        
        # The output format is: SWHID\tfilename (optional)
        # We want just the SWHID part
        swhid = output.split('\t')[0].strip()
        
        if not swhid.startswith("swh:"):
            raise RuntimeError(f"Invalid SWHID format: {swhid}")
        
        return swhid
        
    except subprocess.TimeoutExpired:
        raise RuntimeError("Rust implementation timed out")
    except FileNotFoundError:
        raise RuntimeError("Rust implementation not found (cargo not available)")
    except Exception as e:
        raise RuntimeError(f"Error running Rust implementation: {e}")

def detect_object_type(payload_path: str) -> str:
    """
    Detect the object type for a payload.
    
    Args:
        payload_path: Path to the payload
    
    Returns:
        Object type string
    """
    path = Path(payload_path)
    
    if not path.exists():
        raise ValueError(f"Payload does not exist: {payload_path}")
    
    if path.is_file():
        # Check if it's a Git repository
        git_dir = path / ".git"
        if git_dir.exists() and git_dir.is_dir():
            return "snapshot"
        
        # For files, default to content
        return "content"
    elif path.is_dir():
        # Check if it's a Git repository
        git_dir = path / ".git"
        if git_dir.exists() and git_dir.is_dir():
            return "snapshot"
        
        # For directories, default to directory
        return "directory"
    else:
        raise ValueError(f"Payload is neither file nor directory: {payload_path}")

def compute_swhid_auto(payload_path: str) -> str:
    """
    Compute SWHID with automatic object type detection.
    
    Args:
        payload_path: Path to the payload
    
    Returns:
        SWHID string
    """
    obj_type = detect_object_type(payload_path)
    return compute_swhid_detailed(payload_path, obj_type)

def compute_swhid_simple(payload_path: str) -> str:
    """Simple interface that auto-detects object type."""
    # For content files, explicitly specify the object type
    path = Path(payload_path)
    if path.is_file():
        return compute_swhid_detailed(payload_path, "content")
    elif path.is_dir():
        return compute_swhid_detailed(payload_path, "directory")
    else:
        # Fallback to auto-detection
        obj_type = detect_object_type(payload_path)
        return compute_swhid_detailed(payload_path, obj_type)

# Simple interface for the harness
def compute_swhid(payload_path: str) -> str:
    """Simple interface that the harness calls."""
    return compute_swhid_simple(payload_path)

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python rust_runner.py <payload_path>")
        sys.exit(1)
    
    payload_path = sys.argv[1]
    
    try:
        swhid = compute_swhid_auto(payload_path)
        print(swhid)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1) 