"""
Unit tests for SHA256 expected results generation script.
"""

import pytest
import tempfile
import os
import subprocess
import yaml
import shutil
from pathlib import Path

from tools.generate_sha256_expected import (
    setup_sha256_repo,
    generate_content_sha256,
    generate_directory_sha256,
    generate_revision_sha256,
    generate_release_sha256,
    process_payload,
    run_git_command
)


class TestSetupSha256Repo:
    """Test SHA256 repository setup."""
    
    def test_setup_sha256_repo(self):
        """Test that setup_sha256_repo creates a SHA256 Git repo."""
        with tempfile.TemporaryDirectory() as temp_dir:
            setup_sha256_repo(temp_dir)
            
            # Verify .git directory exists
            assert os.path.exists(os.path.join(temp_dir, ".git"))
            
            # Verify object format is SHA256
            result = subprocess.run(
                ["git", "rev-parse", "--show-object-format"],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                check=True
            )
            assert result.stdout.strip() == "sha256"
            
            # Verify Git config
            result = subprocess.run(
                ["git", "config", "core.autocrlf"],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                check=True
            )
            assert result.stdout.strip() == "false"


class TestGenerateContentSha256:
    """Test content object SHA256 generation."""
    
    def test_generate_content_sha256_simple_file(self):
        """Test generating SHA256 for a simple text file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test file
            test_file = os.path.join(temp_dir, "test.txt")
            with open(test_file, "w") as f:
                f.write("Hello, world!\n")
            
            # Generate SHA256
            result = generate_content_sha256(test_file, temp_dir)
            
            assert result is not None
            assert result.startswith("swh:2:cnt:")
            # SHA256 hash is 64 hex characters
            hash_part = result.split(":")[-1]
            assert len(hash_part) == 64
            assert all(c in "0123456789abcdef" for c in hash_part)
    
    def test_generate_content_sha256_empty_file(self):
        """Test generating SHA256 for an empty file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, "empty.txt")
            Path(test_file).touch()
            
            result = generate_content_sha256(test_file, temp_dir)
            
            assert result is not None
            assert result.startswith("swh:2:cnt:")
    
    def test_generate_content_sha256_nonexistent_file(self):
        """Test that nonexistent file returns None."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = generate_content_sha256("nonexistent.txt", temp_dir)
            assert result is None
    
    def test_generate_content_sha256_relative_path(self):
        """Test generating SHA256 with relative path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, "test.txt")
            with open(test_file, "w") as f:
                f.write("test content")
            
            # Use relative path
            rel_path = "test.txt"
            result = generate_content_sha256(rel_path, temp_dir)
            
            assert result is not None
            assert result.startswith("swh:2:cnt:")


class TestGenerateDirectorySha256:
    """Test directory object SHA256 generation."""
    
    def test_generate_directory_sha256_simple_dir(self):
        """Test generating SHA256 for a simple directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test directory with files
            test_dir = os.path.join(temp_dir, "test_dir")
            os.makedirs(test_dir)
            
            with open(os.path.join(test_dir, "file1.txt"), "w") as f:
                f.write("content 1")
            with open(os.path.join(test_dir, "file2.txt"), "w") as f:
                f.write("content 2")
            
            result = generate_directory_sha256(test_dir, temp_dir)
            
            assert result is not None
            assert result.startswith("swh:2:dir:")
            hash_part = result.split(":")[-1]
            assert len(hash_part) == 64
    
    def test_generate_directory_sha256_empty_dir(self):
        """Test generating SHA256 for an empty directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_dir = os.path.join(temp_dir, "empty_dir")
            os.makedirs(test_dir)
            
            result = generate_directory_sha256(test_dir, temp_dir)
            
            assert result is not None
            assert result.startswith("swh:2:dir:")
    
    def test_generate_directory_sha256_with_executable(self):
        """Test generating SHA256 for directory with executable file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_dir = os.path.join(temp_dir, "test_dir")
            os.makedirs(test_dir)
            
            exec_file = os.path.join(test_dir, "script.sh")
            with open(exec_file, "w") as f:
                f.write("#!/bin/sh\necho hello")
            os.chmod(exec_file, 0o755)
            
            result = generate_directory_sha256(test_dir, temp_dir)
            
            assert result is not None
            assert result.startswith("swh:2:dir:")
    
    def test_generate_directory_sha256_nonexistent(self):
        """Test that nonexistent directory returns None."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = generate_directory_sha256("nonexistent", temp_dir)
            assert result is None


class TestGenerateRevisionSha256:
    """Test revision object SHA256 generation."""
    
    def test_generate_revision_sha256(self):
        """Test generating SHA256 for a revision."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a Git repo
            setup_sha256_repo(temp_dir)
            
            # Create a commit
            with open(os.path.join(temp_dir, "file.txt"), "w") as f:
                f.write("test content")
            run_git_command(["git", "add", "file.txt"], cwd=temp_dir)
            run_git_command(
                ["git", "commit", "-m", "Initial commit"],
                cwd=temp_dir,
                env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}
            )
            
            result = generate_revision_sha256(temp_dir, temp_dir)
            
            assert result is not None
            assert result.startswith("swh:2:rev:")
            hash_part = result.split(":")[-1]
            assert len(hash_part) == 64
    
    def test_generate_revision_sha256_specific_commit(self):
        """Test generating SHA256 for a specific commit."""
        with tempfile.TemporaryDirectory() as temp_dir:
            setup_sha256_repo(temp_dir)
            
            # Create two commits
            with open(os.path.join(temp_dir, "file1.txt"), "w") as f:
                f.write("content 1")
            run_git_command(["git", "add", "file1.txt"], cwd=temp_dir)
            env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}
            run_git_command(
                ["git", "commit", "-m", "Commit 1"],
                cwd=temp_dir,
                env=env
            )
            
            commit_hash = run_git_command(["git", "rev-parse", "HEAD"], cwd=temp_dir)
            
            with open(os.path.join(temp_dir, "file2.txt"), "w") as f:
                f.write("content 2")
            run_git_command(["git", "add", "file2.txt"], cwd=temp_dir)
            run_git_command(
                ["git", "commit", "-m", "Commit 2"],
                cwd=temp_dir,
                env=env
            )
            
            # Get first commit
            result = generate_revision_sha256(temp_dir, temp_dir, commit=commit_hash)
            
            assert result is not None
            assert result.startswith("swh:2:rev:")
            assert result.endswith(commit_hash)
    
    def test_generate_revision_sha256_not_git_repo(self):
        """Test that non-Git directory returns None."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = generate_revision_sha256(temp_dir, temp_dir)
            assert result is None


class TestGenerateReleaseSha256:
    """Test release object SHA256 generation."""
    
    def test_generate_release_sha256(self):
        """Test generating SHA256 for a release (annotated tag)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            setup_sha256_repo(temp_dir)
            
            # Create a commit
            with open(os.path.join(temp_dir, "file.txt"), "w") as f:
                f.write("test content")
            run_git_command(["git", "add", "file.txt"], cwd=temp_dir)
            run_git_command(
                ["git", "commit", "-m", "Initial commit"],
                cwd=temp_dir,
                env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}
            )
            
            # Create annotated tag
            env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}
            run_git_command(
                ["git", "tag", "-a", "v1.0.0", "-m", "Version 1.0.0"],
                cwd=temp_dir,
                env=env
            )
            
            result = generate_release_sha256(temp_dir, temp_dir, tag="v1.0.0")
            
            assert result is not None
            assert result.startswith("swh:2:rel:")
            hash_part = result.split(":")[-1]
            assert len(hash_part) == 64
    
    def test_generate_release_sha256_nonexistent_tag(self):
        """Test that nonexistent tag returns None."""
        with tempfile.TemporaryDirectory() as temp_dir:
            setup_sha256_repo(temp_dir)
            
            result = generate_release_sha256(temp_dir, temp_dir, tag="nonexistent")
            assert result is None


class TestProcessPayload:
    """Test payload processing."""
    
    def test_process_payload_content(self):
        """Test processing a content payload."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, "test.txt")
            with open(test_file, "w") as f:
                f.write("test content")
            
            payload = {
                "name": "test",
                "path": test_file
            }
            
            result = process_payload(payload, "content", temp_dir)
            
            assert result is not None
            assert result.startswith("swh:2:cnt:")
    
    def test_process_payload_directory(self):
        """Test processing a directory payload."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_dir = os.path.join(temp_dir, "test_dir")
            os.makedirs(test_dir)
            with open(os.path.join(test_dir, "file.txt"), "w") as f:
                f.write("content")
            
            payload = {
                "name": "test_dir",
                "path": test_dir
            }
            
            result = process_payload(payload, "directory", temp_dir)
            
            assert result is not None
            assert result.startswith("swh:2:dir:")
    
    def test_process_payload_revision(self):
        """Test processing a revision payload."""
        with tempfile.TemporaryDirectory() as temp_dir:
            setup_sha256_repo(temp_dir)
            
            with open(os.path.join(temp_dir, "file.txt"), "w") as f:
                f.write("content")
            run_git_command(["git", "add", "file.txt"], cwd=temp_dir)
            run_git_command(
                ["git", "commit", "-m", "Commit"],
                cwd=temp_dir,
                env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}
            )
            
            payload = {
                "name": "test_revision",
                "path": temp_dir
            }
            
            result = process_payload(payload, "revision", temp_dir)
            
            assert result is not None
            assert result.startswith("swh:2:rev:")
    
    def test_process_payload_release(self):
        """Test processing a release payload."""
        with tempfile.TemporaryDirectory() as temp_dir:
            setup_sha256_repo(temp_dir)
            
            with open(os.path.join(temp_dir, "file.txt"), "w") as f:
                f.write("content")
            run_git_command(["git", "add", "file.txt"], cwd=temp_dir)
            env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}
            run_git_command(
                ["git", "commit", "-m", "Commit"],
                cwd=temp_dir,
                env=env
            )
            run_git_command(
                ["git", "tag", "-a", "v1.0.0", "-m", "Tag"],
                cwd=temp_dir,
                env=env
            )
            
            payload = {
                "name": "test_release",
                "path": temp_dir,
                "tag": "v1.0.0"
            }
            
            result = process_payload(payload, "release", temp_dir)
            
            assert result is not None
            assert result.startswith("swh:2:rel:")
    
    def test_process_payload_skip_snapshot(self):
        """Test that snapshot payloads are skipped."""
        payload = {
            "name": "test_snapshot",
            "path": "/some/path"
        }
        
        result = process_payload(payload, "git", "/config/dir")
        
        assert result is None

