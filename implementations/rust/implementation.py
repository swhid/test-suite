"""
Rust SWHID Implementation Plugin

This module provides an interface to the Rust SWHID implementation
for the testing harness.
"""

import subprocess
import os
import sys
from pathlib import Path
from typing import Optional

from harness.plugins.base import SwhidImplementation, ImplementationInfo, ImplementationCapabilities

class Implementation(SwhidImplementation):
    """Rust SWHID implementation plugin."""
    
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
        
        # Build the command based on object type
        # The Rust CLI uses subcommands: content, dir, git
        cmd = ["cargo", "run", "--release", "--"]
        
        if obj_type == "content":
            # For content: swhid content --file <path>
            cmd.extend(["content", "--file", payload_path])
        elif obj_type == "directory":
            # For directory: swhid dir <path>
            cmd.extend(["dir", payload_path])
        elif obj_type == "snapshot":
            # For snapshot: swhid git snapshot <REPO> [COMMIT]
            # Note: requires --features git, so we need to enable it
            # Uses positional arguments, not --repo flag
            cmd = ["cargo", "run", "--release", "--features", "git", "--"]
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
            
            cmd = ["cargo", "run", "--release", "--features", "git", "--"]
            cmd.extend(["git", "revision", payload_path])
            if resolved_commit:
                cmd.append(resolved_commit)
        elif obj_type == "release":
            # For release: swhid git release <REPO> <TAG>
            # Uses positional arguments: <REPO> <TAG>
            if not tag:
                raise ValueError("Release SWHID requires a tag name")
            cmd = ["cargo", "run", "--release", "--features", "git", "--"]
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
                timeout=30
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip()
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
