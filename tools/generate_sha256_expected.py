#!/usr/bin/env python3
"""
Generate expected SHA256 SWHID results from Git.

This script iterates through all payloads in config.yaml (excluding snapshots)
and generates expected_swhid_sha256 values by computing Git SHA256 object hashes.

For each payload type:
- Content: Creates SHA256 Git repo, adds file, gets blob hash
- Directory: Creates SHA256 Git repo, adds directory, gets tree hash
- Revision: Creates SHA256 Git repo with commits, gets commit hash
- Release: Creates SHA256 Git repo with tags, gets tag hash

Output: Updated config.yaml with expected_swhid_sha256 fields.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import tarfile
import yaml
from pathlib import Path
from typing import Dict, Any, Optional


def run_git_command(cmd: list, cwd: str, timeout: int = 30, env: Optional[Dict[str, str]] = None) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
        env=env
    )
    return result.stdout.strip()


def setup_sha256_repo(repo_path: str) -> None:
    """Initialize a Git repository with SHA256 object format."""
    # Initialize with SHA256
    run_git_command(["git", "init", "--object-format=sha256"], cwd=repo_path)
    
    # Configure Git for consistency (match workflow settings)
    run_git_command(["git", "config", "core.autocrlf", "false"], cwd=repo_path)
    run_git_command(["git", "config", "core.filemode", "true"], cwd=repo_path)
    run_git_command(["git", "config", "core.precomposeunicode", "false"], cwd=repo_path)
    run_git_command(["git", "config", "core.quotepath", "false"], cwd=repo_path)


def generate_content_sha256(payload_path: str, config_dir: str) -> Optional[str]:
    """Generate SHA256 SWHID for a content object."""
    # Resolve absolute path
    if not os.path.isabs(payload_path):
        abs_path = os.path.join(config_dir, payload_path)
    else:
        abs_path = payload_path
    
    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        return None
    
    with tempfile.TemporaryDirectory(prefix="swhid_sha256_") as temp_dir:
        setup_sha256_repo(temp_dir)
        
        # Copy file to temp repo
        filename = os.path.basename(abs_path)
        dest_path = os.path.join(temp_dir, filename)
        import shutil
        shutil.copy2(abs_path, dest_path)
        
        # Add to Git
        run_git_command(["git", "add", filename], cwd=temp_dir)
        
        # Get blob hash
        result = run_git_command(["git", "ls-files", "--stage", filename], cwd=temp_dir)
        # Format: <mode> <sha> <stage> <path>
        parts = result.split()
        if parts:
            blob_hash = parts[1]  # SHA256 hash (64 chars)
            return f"swh:2:cnt:{blob_hash}"
    
    return None


def generate_directory_sha256(payload_path: str, config_dir: str) -> Optional[str]:
    """Generate SHA256 SWHID for a directory object."""
    # Resolve absolute path
    if not os.path.isabs(payload_path):
        abs_path = os.path.join(config_dir, payload_path)
    else:
        abs_path = payload_path
    
    if not os.path.exists(abs_path) or not os.path.isdir(abs_path):
        return None
    
    with tempfile.TemporaryDirectory(prefix="swhid_sha256_") as temp_dir:
        setup_sha256_repo(temp_dir)
        
        # Copy directory contents to temp repo
        import shutil
        dirname = os.path.basename(abs_path) or "dir"
        dest_dir = os.path.join(temp_dir, dirname)
        shutil.copytree(abs_path, dest_dir, symlinks=True)
        
        # Add to Git (preserve permissions)
        run_git_command(["git", "add", dirname], cwd=temp_dir)
        
        # Apply executable bits from source
        for root, dirs, files in os.walk(dest_dir):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, dest_dir)
                source_path = os.path.join(abs_path, rel_path)
                
                if os.path.exists(source_path):
                    try:
                        import stat
                        source_stat = os.stat(source_path)
                        if source_stat.st_mode & stat.S_IEXEC:
                            # File should be executable
                            git_rel_path = os.path.join(dirname, rel_path).replace("\\", "/")
                            run_git_command(["git", "update-index", "--chmod=+x", git_rel_path], cwd=temp_dir)
                    except (OSError, subprocess.CalledProcessError):
                        pass
        
        # Get tree hash
        tree_hash = run_git_command(["git", "write-tree"], cwd=temp_dir)
        return f"swh:2:dir:{tree_hash}"
    
    return None


def generate_revision_sha256(payload_path: str, config_dir: str, commit: Optional[str] = None) -> Optional[str]:
    """Generate SHA256 SWHID for a revision object."""
    # Resolve absolute path
    if not os.path.isabs(payload_path):
        abs_path = os.path.join(config_dir, payload_path)
    else:
        abs_path = payload_path
    
    # Handle tarballs
    if abs_path.endswith('.tar.gz'):
        with tempfile.TemporaryDirectory(prefix="swhid_sha256_") as temp_dir:
            with tarfile.open(abs_path, "r:gz") as tar:
                tar.extractall(temp_dir)
            extracted_items = os.listdir(temp_dir)
            if len(extracted_items) == 1 and os.path.isdir(os.path.join(temp_dir, extracted_items[0])):
                abs_path = os.path.join(temp_dir, extracted_items[0])
            else:
                abs_path = temp_dir
    
    if not os.path.exists(abs_path) or not os.path.isdir(abs_path):
        return None
    
    # Check if it's a Git repo
    git_dir = os.path.join(abs_path, ".git")
    if not os.path.exists(git_dir):
        # Not a Git repo - can't generate revision
        return None
    
    # Get commit hash (use provided commit or HEAD)
    try:
        commit_ref = commit or "HEAD"
        commit_hash = run_git_command(["git", "rev-parse", commit_ref], cwd=abs_path)
        return f"swh:2:rev:{commit_hash}"
    except subprocess.CalledProcessError:
        return None


def generate_release_sha256(payload_path: str, config_dir: str, tag: str) -> Optional[str]:
    """Generate SHA256 SWHID for a release object."""
    # Resolve absolute path
    if not os.path.isabs(payload_path):
        abs_path = os.path.join(config_dir, payload_path)
    else:
        abs_path = payload_path
    
    # Handle tarballs
    if abs_path.endswith('.tar.gz'):
        with tempfile.TemporaryDirectory(prefix="swhid_sha256_") as temp_dir:
            with tarfile.open(abs_path, "r:gz") as tar:
                tar.extractall(temp_dir)
            extracted_items = os.listdir(temp_dir)
            if len(extracted_items) == 1 and os.path.isdir(os.path.join(temp_dir, extracted_items[0])):
                abs_path = os.path.join(temp_dir, extracted_items[0])
            else:
                abs_path = temp_dir
    
    if not os.path.exists(abs_path) or not os.path.isdir(abs_path):
        return None
    
    # Check if it's a Git repo
    git_dir = os.path.join(abs_path, ".git")
    if not os.path.exists(git_dir):
        # Not a Git repo - can't generate release
        return None
    
    # Get tag object hash (use ^{} to get tag object, not commit)
    try:
        tag_hash = run_git_command(["git", "rev-parse", f"{tag}^{{}}"], cwd=abs_path)
        return f"swh:2:rel:{tag_hash}"
    except subprocess.CalledProcessError:
        return None


def process_payload(payload: Dict[str, Any], category: str, config_dir: str) -> Optional[str]:
    """Process a single payload and return SHA256 SWHID if successful."""
    payload_path = payload.get("path")
    if not payload_path:
        return None
    
    # Skip snapshots (not supported by Git)
    if category == "git" or category.startswith("git"):
        return None
    
    # Determine object type from category
    if category == "content" or category.startswith("content/"):
        return generate_content_sha256(payload_path, config_dir)
    elif category == "directory" or category.startswith("directory/"):
        return generate_directory_sha256(payload_path, config_dir)
    elif category == "revision":
        commit = payload.get("commit")
        return generate_revision_sha256(payload_path, config_dir, commit)
    elif category == "release":
        tag = payload.get("tag")
        if not tag:
            return None
        return generate_release_sha256(payload_path, config_dir, tag)
    
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Generate expected SHA256 SWHID results from Git"
    )
    parser.add_argument(
        "config_file",
        nargs="?",
        default="config.yaml",
        help="Path to config.yaml file (default: config.yaml)"
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path (default: overwrites input file)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write output, just show what would be generated"
    )
    
    args = parser.parse_args()
    
    # Read config
    config_path = os.path.abspath(args.config_file)
    config_dir = os.path.dirname(config_path)
    
    if not os.path.exists(config_path):
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        return 1
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    if "payloads" not in config:
        print("Error: No 'payloads' section in config", file=sys.stderr)
        return 1
    
    # Process each payload
    updated_count = 0
    skipped_count = 0
    error_count = 0
    
    for category, payloads in config["payloads"].items():
        if not isinstance(payloads, list):
            continue
        
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            
            name = payload.get("name", "unknown")
            print(f"Processing {category}/{name}...", end=" ", flush=True)
            
            try:
                sha256_swhid = process_payload(payload, category, config_dir)
                
                if sha256_swhid:
                    payload["expected_swhid_sha256"] = sha256_swhid
                    updated_count += 1
                    print(f"✓ {sha256_swhid}")
                else:
                    skipped_count += 1
                    print("⊘ skipped (not supported or not found)")
            except Exception as e:
                error_count += 1
                print(f"✗ error: {e}")
    
    # Summary
    print(f"\nSummary:")
    print(f"  Updated: {updated_count}")
    print(f"  Skipped: {skipped_count}")
    print(f"  Errors: {error_count}")
    
    # Write output
    if not args.dry_run:
        output_path = args.output or config_path
        with open(output_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        print(f"\nUpdated config written to: {output_path}")
    else:
        print("\nDry run - no changes written")
    
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

