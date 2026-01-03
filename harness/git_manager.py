"""
Git management for the SWHID Testing Harness.

This module handles Git repository operations including repository creation,
commit resolution, and branch/tag discovery.
"""

import subprocess
import os
from pathlib import Path
from typing import Optional
import logging

from .utils.git_utils import resolve_commit_reference, discover_branches, discover_annotated_tags, is_git_repository

logger = logging.getLogger(__name__)


class GitManager:
    """Manages Git repository operations."""
    
    def create_minimal_git_repo(self, repo_path: str) -> None:
        """
        Create a small git repository with one commit, one tag, and default HEAD.
        This is used to test snapshot identifiers.
        
        Uses fixed timestamps to ensure deterministic commit hashes across runs.
        All operations use fixed dates and explicit configurations for reproducibility.
        
        Args:
            repo_path: Path where to create the Git repository
        """
        path = Path(repo_path)
        path.mkdir(parents=True, exist_ok=True)

        # Fixed timestamp for deterministic commits and tags
        # Use Unix timestamp format like Git's test suite (1112911993 = 2005-04-07)
        test_tick = 1112911993
        env = os.environ.copy()
        env["TZ"] = "UTC"

        # Initialize repo with explicit default branch name for consistency
        subprocess.run(["git", "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True)
        # Configure user (required for commits)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)
        # Disable GPG signing for commits and tags to ensure deterministic objects
        subprocess.run(["git", "config", "commit.gpgSign", "false"], cwd=repo_path, check=True)
        subprocess.run(["git", "config", "tag.gpgSign", "false"], cwd=repo_path, check=True)
        
        # Configure Git for cross-platform consistency (critical for Windows)
        # This ensures line endings, Unicode, and file modes are handled consistently
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "core.filemode", "true"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "core.precomposeunicode", "false"], cwd=repo_path, check=True, capture_output=True)

        # Create a file and commit (first timestamp)
        # Write files in binary mode with explicit LF line endings and UTF-8 encoding
        # to ensure cross-platform consistency (pathlib.write_text() may use CRLF on Windows)
        env["GIT_AUTHOR_DATE"] = f"{test_tick} +0000"
        env["GIT_COMMITTER_DATE"] = f"{test_tick} +0000"
        with open(path / "README.md", "wb") as f:
            f.write("# Sample Repo\n".encode("utf-8"))
        subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=True,
                      capture_output=True, env=env)

        # Create a branch 'feature' and second commit (increment timestamp)
        test_tick += 60
        env["GIT_AUTHOR_DATE"] = f"{test_tick} +0000"
        env["GIT_COMMITTER_DATE"] = f"{test_tick} +0000"
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo_path, check=True, capture_output=True)
        with open(path / "FEATURE.txt", "wb") as f:
            f.write("feature\n".encode("utf-8"))
        subprocess.run(["git", "add", "FEATURE.txt"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add feature"], cwd=repo_path, check=True,
                      capture_output=True, env=env)

        # Switch back to main
        subprocess.run(["git", "checkout", "-B", "main"], cwd=repo_path, check=True, capture_output=True)

        # Create an annotated tag (increment timestamp)
        test_tick += 60
        env["GIT_AUTHOR_DATE"] = f"{test_tick} +0000"
        env["GIT_COMMITTER_DATE"] = f"{test_tick} +0000"
        subprocess.run(["git", "tag", "-a", "v1.0", "-m", "Release v1.0"], cwd=repo_path, check=True,
                      env=env, capture_output=True)
    
    def resolve_commit(self, repo_path: str, commit: Optional[str] = None) -> Optional[str]:
        """
        Resolve a commit reference to a full SHA.
        
        Args:
            repo_path: Path to Git repository
            commit: Commit reference (branch, tag, short SHA, or None for HEAD)
            
        Returns:
            Full SHA or original commit if resolution fails
        """
        return resolve_commit_reference(repo_path, commit)
    
    def get_branches(self, repo_path: str) -> list[str]:
        """
        Get all branches in a repository.
        
        Args:
            repo_path: Path to Git repository
            
        Returns:
            List of branch names
        """
        return discover_branches(repo_path)
    
    def get_annotated_tags(self, repo_path: str) -> list[str]:
        """
        Get all annotated tags in a repository.
        
        Args:
            repo_path: Path to Git repository
            
        Returns:
            List of annotated tag names
        """
        return discover_annotated_tags(repo_path)
    
    def check_is_repository(self, path: str) -> bool:
        """
        Check if a path is a Git repository.
        
        Args:
            path: Path to check
            
        Returns:
            True if path is a Git repository
        """
        return is_git_repository(path)

