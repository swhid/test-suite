#!/usr/bin/env python3
"""
Python SWHID Implementation Runner

This module provides an interface to the Python SWHID implementation
for the testing harness.
"""

import subprocess
import os
import sys
from pathlib import Path
from typing import Optional

def compute_swhid(payload_path: str, obj_type: Optional[str] = None, 
                  archive: bool = False) -> str:
    """
    Compute SWHID for a payload using the Python implementation.
    
    Args:
        payload_path: Path to the payload file/directory
        obj_type: Object type (content, directory, snapshot, auto)
        archive: Whether to treat file as archive (not supported in Python impl)
    
    Returns:
        SWHID string
    """
    # Build the command
    cmd = ["python", "-m", "swh.model.cli"]
    
    # Add object type if specified
    if obj_type and obj_type != "auto":
        cmd.extend(["--type", obj_type])
    
    # Add archive flag if requested (note: Python impl may not support this)
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
            timeout=30
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Python implementation failed: {result.stderr}")
        
        # Parse the output
        output = result.stdout.strip()
        if not output:
            raise RuntimeError("No output from Python implementation")
        
        # The output format is: SWHID\tfilename (optional)
        # We want just the SWHID part
        swhid = output.split('\t')[0].strip()
        
        if not swhid.startswith("swh:"):
            raise RuntimeError(f"Invalid SWHID format: {swhid}")
        
        return swhid
        
    except subprocess.TimeoutExpired:
        raise RuntimeError("Python implementation timed out")
    except FileNotFoundError:
        raise RuntimeError("Python implementation not found (swh.model not available)")
    except Exception as e:
        raise RuntimeError(f"Error running Python implementation: {e}")

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
    return compute_swhid(payload_path, obj_type)

# For backward compatibility
def compute_swhid_simple(payload_path: str) -> str:
    """Simple interface that auto-detects object type."""
    return compute_swhid_auto(payload_path)

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python python_runner.py <payload_path>")
        sys.exit(1)
    
    payload_path = sys.argv[1]
    
    try:
        swhid = compute_swhid_auto(payload_path)
        print(swhid)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1) 