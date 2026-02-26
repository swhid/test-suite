#!/usr/bin/env python3
"""
Generate expected SHA256 SWHID results from Git.

This script iterates through all payloads in config.yaml (excluding snapshots)
and generates expected_swhid_sha256 values.

- Content and directory: use a temporary Git repo with --object-format=sha256
  so that blob/tree hashes are native SHA256.

- Revision and release: the SHA256 hash of a commit (or tag) depends on the
  SHA256 hashes of the objects it references (tree -> blobs, etc.). So we
  convert the payload repo to Git's SHA256 object format via fast-export /
  fast-import, then use git rev-parse to get the correct revision or release
  SWHID.

  Exception: for GPG-signed commits, fast-export/fast-import may re-serialize
  the commit (e.g. gpgsig header folding) so the resulting SHA256 differs from
  implementations that hash the commit as stored. The signed_revision_* tests
  therefore use expected_swhid_sha256 from the Rust implementation.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import tarfile
import yaml
from pathlib import Path
from typing import Dict, Any, Optional


def run_git_command(cmd: list, cwd: str, timeout: int = 60, env: Optional[Dict[str, str]] = None) -> str:
    """Run a git command and return stdout as string."""
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
    """Generate SHA256 SWHID for a directory object.

    The payload directory contents are placed at the repo root (not as a subdirectory),
    matching what swhid dir <path> hashes: the contents of the given directory.
    """
    import shutil
    import stat

    if not os.path.isabs(payload_path):
        abs_path = os.path.join(config_dir, payload_path)
    else:
        abs_path = payload_path

    if not os.path.exists(abs_path) or not os.path.isdir(abs_path):
        return None

    with tempfile.TemporaryDirectory(prefix="swhid_sha256_") as temp_dir:
        setup_sha256_repo(temp_dir)

        # Copy directory contents directly to temp repo root (not as a subdirectory).
        shutil.copytree(abs_path, temp_dir, symlinks=True, dirs_exist_ok=True)

        # Add all contents at repo root
        run_git_command(["git", "add", "."], cwd=temp_dir)

        # Apply executable bits from source (Git may not preserve from copy)
        for root, dirs, files in os.walk(temp_dir):
            if ".git" in dirs:
                dirs.remove(".git")
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, temp_dir)
                source_path = os.path.join(abs_path, rel_path)
                if os.path.exists(source_path) and os.path.isfile(source_path):
                    try:
                        source_stat = os.stat(source_path)
                        if source_stat.st_mode & stat.S_IEXEC:
                            git_rel_path = rel_path.replace("\\", "/")
                            run_git_command(
                                ["git", "update-index", "--chmod=+x", git_rel_path],
                                cwd=temp_dir,
                            )
                    except (OSError, subprocess.CalledProcessError):
                        pass

        tree_hash = run_git_command(["git", "write-tree"], cwd=temp_dir)
        return f"swh:2:dir:{tree_hash}"

    return None


def generate_revision_sha256(payload_path: str, config_dir: str, commit: Optional[str] = None) -> Optional[str]:
    """
    Generate SHA256 SWHID for a revision by converting the repo to Git's
    SHA256 object format (so commit -> tree -> blob hashes are all SHA256)
    and then reading the commit hash.
    """
    with tempfile.TemporaryDirectory(prefix="swhid_sha256_") as top:
        repo_path = _resolve_repo_path(payload_path, config_dir, extract_dir=top)
        if repo_path is None:
            return None

        commit_ref = commit if commit else "HEAD"
        export_ref = "refs/temp/rev-export"

        copy_path = os.path.join(top, "source")
        try:
            shutil.copytree(repo_path, copy_path)
        except OSError:
            return None

        try:
            run_git_command(
                ["git", "update-ref", export_ref, commit_ref],
                cwd=copy_path,
                timeout=30,
            )
        except subprocess.CalledProcessError:
            return None

        sha256_path = os.path.join(top, "sha256")
        os.makedirs(sha256_path, exist_ok=True)
        setup_sha256_repo(sha256_path)

        try:
            _run_fast_export_import(copy_path, sha256_path, [export_ref])
        except subprocess.CalledProcessError:
            return None

        try:
            rev_sha256 = run_git_command(
                ["git", "rev-parse", export_ref],
                cwd=sha256_path,
                timeout=10,
            )
        except subprocess.CalledProcessError:
            return None

        if len(rev_sha256) != 64:
            return None
        return f"swh:2:rev:{rev_sha256}"


def generate_release_sha256(payload_path: str, config_dir: str, tag: str) -> Optional[str]:
    """
    Generate SHA256 SWHID for a release by converting the repo to Git's
    SHA256 object format and then reading the tag object hash.
    """
    with tempfile.TemporaryDirectory(prefix="swhid_sha256_") as top:
        repo_path = _resolve_repo_path(payload_path, config_dir, extract_dir=top)
        if repo_path is None:
            return None

        tag_ref = f"refs/tags/{tag}"

        copy_path = os.path.join(top, "source")
        try:
            shutil.copytree(repo_path, copy_path)
        except OSError:
            return None

        try:
            obj_type = run_git_command(
                ["git", "cat-file", "-t", tag],
                cwd=copy_path,
                timeout=10,
            )
        except subprocess.CalledProcessError:
            return None
        if obj_type != "tag":
            return None

        sha256_path = os.path.join(top, "sha256")
        os.makedirs(sha256_path, exist_ok=True)
        setup_sha256_repo(sha256_path)

        try:
            _run_fast_export_import(
                copy_path,
                sha256_path,
                [tag_ref],
                extra_export_args=["--signed-tags=verbatim"],
            )
        except subprocess.CalledProcessError:
            try:
                _run_fast_export_import(
                    copy_path,
                    sha256_path,
                    [tag_ref],
                    extra_export_args=["--signed-tags=strip"],
                )
            except subprocess.CalledProcessError:
                return None

        try:
            tag_sha256 = run_git_command(
                ["git", "rev-parse", tag_ref],
                cwd=sha256_path,
                timeout=10,
            )
        except subprocess.CalledProcessError:
            return None

        if len(tag_sha256) != 64:
            return None
        return f"swh:2:rel:{tag_sha256}"


def _resolve_repo_path(
    payload_path: str,
    config_dir: str,
    extract_dir: Optional[str] = None,
) -> Optional[str]:
    """
    Resolve payload path to an absolute repo directory.
    For tarballs, extract into extract_dir (must be provided so the dir stays valid).
    """
    if not os.path.isabs(payload_path):
        abs_path = os.path.join(config_dir, payload_path)
    else:
        abs_path = payload_path

    if abs_path.endswith(".tar.gz"):
        if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
            return None
        if extract_dir is None or not os.path.isdir(extract_dir):
            return None
        try:
            with tarfile.open(abs_path, "r:gz") as tar:
                tar.extractall(extract_dir, filter="data")
        except Exception:
            return None
        items = os.listdir(extract_dir)
        if len(items) == 1 and os.path.isdir(os.path.join(extract_dir, items[0])):
            repo_path = os.path.join(extract_dir, items[0])
        else:
            repo_path = extract_dir
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            return None
        return repo_path

    if not os.path.exists(abs_path) or not os.path.isdir(abs_path):
        return None
    if not os.path.isdir(os.path.join(abs_path, ".git")):
        return None
    return abs_path


def _run_fast_export_import(
    source_repo: str,
    dest_repo: str,
    refs: list,
    extra_export_args: Optional[list] = None,
    timeout: int = 120,
) -> None:
    """Run git fast-export from source_repo for the given refs, pipe into fast-import in dest_repo."""
    export_args = ["git", "fast-export"] + (extra_export_args or []) + refs
    export_proc = subprocess.Popen(
        export_args,
        cwd=source_repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    import_proc = subprocess.run(
        ["git", "fast-import"],
        cwd=dest_repo,
        stdin=export_proc.stdout,
        capture_output=True,
        timeout=timeout,
        check=True,
    )
    export_proc.wait(timeout=5)
    if export_proc.returncode != 0:
        raise subprocess.CalledProcessError(export_proc.returncode or 1, export_args)


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

