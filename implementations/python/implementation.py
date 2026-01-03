"""
Python SWHID Implementation Plugin

This module provides an interface to the Python SWHID implementation
for the testing harness.
"""

import subprocess
import os
import sys
import re
from pathlib import Path
from typing import Optional

from harness.plugins.base import SwhidImplementation, ImplementationInfo, ImplementationCapabilities

try:
    from swh.model.model import (
        Revision, Release, Person, TimestampWithTimezone, RevisionType,
        Timestamp, ReleaseTargetType
    )
    from swh.model.git_objects import revision_git_object, release_git_object
    from swh.model import hashutil
    SWH_MODEL_AVAILABLE = True
except ImportError:
    SWH_MODEL_AVAILABLE = False

class Implementation(SwhidImplementation):
    """Python SWHID implementation plugin."""
    
    def get_info(self) -> ImplementationInfo:
        """Return implementation metadata."""
        return ImplementationInfo(
            name="python",
            version="1.0.0",
            language="python",
            description="Python SWHID implementation via swh.model.cli",
            test_command="python3 -m swh.model.cli --help",
            dependencies=["swh.model"]
        )
    
    def is_available(self) -> bool:
        """Check if Python implementation is available."""
        try:
            # Check if swh.model is available
            result = subprocess.run(
                ["python3", "-c", "import swh.model"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=5
            )
            if result.returncode != 0:
                return False
            
            # Check if CLI is available
            result = subprocess.run(
                ["python3", "-m", "swh.model.cli", "--help"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=10
            )
            return result.returncode == 0
            
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
                     commit: Optional[str] = None, tag: Optional[str] = None,
                     version: Optional[int] = None, hash_algo: Optional[str] = None) -> str:
        """Compute SWHID for a payload using the Python implementation.
        
        Note: version and hash_algo parameters are accepted for API compatibility
        but are ignored as the Python implementation only supports v1/SHA1.
        """
        # Route to appropriate computation method
        if obj_type == "revision":
            return self._compute_revision_swhid(payload_path, commit=commit)
        elif obj_type == "release":
            return self._compute_release_swhid(payload_path, tag=tag)
        
        # Build the command
        cmd = ["python3", "-m", "swh.model.cli"]
        
        # Add object type if specified
        if obj_type and obj_type != "auto":
            cmd.extend(["--type", obj_type])
        
        # Ensure snapshot type is passed for git repos
        if obj_type is None:
            obj_type = self.detect_object_type(payload_path)
            if obj_type and obj_type != "auto":
                # Reset and add again to ensure correct flag ordering
                cmd = ["python3", "-m", "swh.model.cli", "--type", obj_type]
        
        # Add the payload path
        cmd.append(payload_path)
        
        # Run the command
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
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
    
    def _compute_revision_swhid(self, repo_path: str, commit: Optional[str] = None) -> str:
        """Compute revision SWHID using swh.model Python API."""
        if not SWH_MODEL_AVAILABLE:
            raise RuntimeError("swh.model Python API not available")
        
        # Default to HEAD if no commit specified
        if commit is None:
            commit = "HEAD"
        
        # Resolve commit reference to full SHA
        result = subprocess.run(
            ["git", "rev-parse", commit],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )
        commit_sha = result.stdout.strip()
        
        # Get raw commit object (content only, no header) to extract GPG signature exactly
        raw_commit_result = subprocess.run(
            ["git", "cat-file", "commit", commit_sha],
            cwd=repo_path,
            capture_output=True,
            check=True
        )
        raw_commit_content = raw_commit_result.stdout
        
        # Get pretty-printed commit object for parsing other fields
        commit_result = subprocess.run(
            ["git", "cat-file", "-p", commit_sha],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )
        
        # Parse commit object
        lines = commit_result.stdout.split('\n')
        tree_sha = None
        parents = []
        author_line = None
        committer_line = None
        message_start = None
        
        for i, line in enumerate(lines):
            if line.startswith('tree '):
                tree_sha = line.split()[1]
            elif line.startswith('parent '):
                parents.append(line.split()[1])
            elif line.startswith('author '):
                author_line = line[7:]  # Skip 'author '
            elif line.startswith('committer '):
                committer_line = line[10:]  # Skip 'committer '
            elif line == '' and message_start is None:
                # Check if there's a GPG signature before this blank line
                # (we'll extract it from raw content)
                message_start = i + 1
                break
        
        # Extract GPG signature from raw content if present
        # Remove leading spaces from continuation lines (swh.model adds them back)
        gpgsig_bytes = None
        gpgsig_start = raw_commit_content.find(b'gpgsig ')
        if gpgsig_start >= 0:
            # Find where message starts (blank line after END PGP SIGNATURE)
            end_sig = raw_commit_content.find(b'-----END PGP SIGNATURE-----', gpgsig_start)
            if end_sig >= 0:
                # Find the blank line (two consecutive newlines)
                blank_line_pos = raw_commit_content.find(b'\n\n', end_sig)
                if blank_line_pos >= 0:
                    # Extract GPG signature value (without "gpgsig " prefix, up to but not including final \n)
                    # swh.model will add the blank line before message automatically
                    gpgsig_raw = raw_commit_content[gpgsig_start+7:blank_line_pos]  # +7 for "gpgsig ", don't include final \n
                    # Remove leading spaces from each line (swh.model adds them back for continuation lines)
                    gpgsig_lines = gpgsig_raw.split(b'\n')
                    processed_lines = [line.lstrip(b' ') for line in gpgsig_lines]
                    gpgsig_bytes = b'\n'.join(processed_lines)
        
        if not tree_sha:
            raise ValueError(f"Could not parse tree from commit {commit_sha}")
        
        # Parse author/committer (format: "Name <email> timestamp offset")
        def parse_person(line):
            """Parse Git person line: 'Name <email> timestamp offset'"""
            match = re.match(r'(.+?) <(.+?)> (\d+) ([+-]\d{4})', line)
            if match:
                name, email, ts, offset = match.groups()
                # fullname should be the complete "Name <email>" string
                fullname_str = f"{name} <{email}>"
                return Person(
                    fullname=fullname_str.encode('utf-8'),
                    name=name.encode('utf-8'),
                    email=email.encode('utf-8')
                ), int(ts), offset.encode('utf-8')
            return None, None, None
        
        author, author_ts, author_offset = parse_person(author_line) if author_line else (None, None, None)
        committer, committer_ts, committer_offset = parse_person(committer_line) if committer_line else (None, None, None)
        
        if not author or not committer:
            raise ValueError(f"Could not parse author/committer from commit {commit_sha}")
        
        # Get message (everything after blank line)
        message = '\n'.join(lines[message_start:]).encode('utf-8') if message_start else b''
        
        # Get directory SWHID for tree - we need to compute it
        # Use git write-tree to get tree hash, then format as directory SWHID
        # Actually, we can use the tree SHA directly (it's already a directory hash)
        tree_bytes = bytes.fromhex(tree_sha)
        
        # Create timestamps
        author_timestamp = TimestampWithTimezone(
            timestamp=Timestamp(seconds=author_ts, microseconds=0),
            offset_bytes=author_offset
        )
        
        committer_timestamp = TimestampWithTimezone(
            timestamp=Timestamp(seconds=committer_ts, microseconds=0),
            offset_bytes=committer_offset
        )
        
        # Prepare extra_headers for GPG signature if present
        # Use raw bytes extracted from Git object to preserve exact format
        extra_headers = ()
        if gpgsig_bytes:
            extra_headers = ((b'gpgsig', gpgsig_bytes),)
        
        # Create Revision object
        revision = Revision(
            message=message,
            author=author,
            committer=committer,
            date=author_timestamp,
            committer_date=committer_timestamp,
            type=RevisionType.GIT,
            directory=tree_bytes,
            synthetic=False,
            parents=tuple(bytes.fromhex(p) for p in parents),
            extra_headers=extra_headers
        )
        
        # Format as Git object
        git_obj = revision_git_object(revision)
        
        # Extract content (skip header) - hash_git_data expects just the content
        header_end = git_obj.find(b'\0')
        if header_end > 0:
            content = git_obj[header_end+1:]
        else:
            content = git_obj
        
        # Hash using swh.model hashutil (same as tested in standalone tests)
        hash_bytes = hashutil.hash_git_data(content, 'commit', base_algo='sha1')
        sha1 = hashutil.hash_to_hex(hash_bytes)
        
        return f"swh:1:rev:{sha1}"
    
    def _compute_release_swhid(self, repo_path: str, tag: Optional[str] = None) -> str:
        """Compute release SWHID using swh.model Python API."""
        if not SWH_MODEL_AVAILABLE:
            raise RuntimeError("swh.model Python API not available")
        
        if tag is None:
            raise ValueError("Tag name is required for release SWHID computation")
        
        # Check if it's an annotated tag
        result = subprocess.run(
            ["git", "cat-file", "-t", tag],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )
        tag_type = result.stdout.strip()
        
        if tag_type != "tag":
            raise ValueError(f"Tag '{tag}' is a lightweight tag, not an annotated tag. Releases require annotated tags.")
        
        # Get tag object
        tag_result = subprocess.run(
            ["git", "cat-file", "-p", tag],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True
        )
        
        # Parse tag object
        lines = tag_result.stdout.split('\n')
        object_sha = None
        object_type = None
        tag_name = None
        tagger_line = None
        message_start = None
        
        for i, line in enumerate(lines):
            if line.startswith('object '):
                object_sha = line.split()[1]
            elif line.startswith('type '):
                object_type = line.split()[1]
            elif line.startswith('tag '):
                tag_name = line.split()[1]
            elif line.startswith('tagger '):
                tagger_line = line[7:]  # Skip 'tagger '
            elif line == '' and message_start is None:
                message_start = i + 1
                break
        
        if not object_sha:
            raise ValueError(f"Could not parse tag object for tag '{tag}': missing object field")
        
        if not tag_name:
            tag_name = tag
        
        # For releases, the target should be the revision SWHID (commit hash)
        # For signed tags pointing to tags, we need to follow to the commit
        target_commit_sha = object_sha
        if object_type == 'tag':
            # Follow the chain: tag -> tag -> commit
            inner_tag_result = subprocess.run(
                ["git", "cat-file", "-p", object_sha],
                cwd=repo_path,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                check=True
            )
            inner_lines = inner_tag_result.stdout.split('\n')
            inner_object_sha = None
            inner_object_type = None
            for line in inner_lines:
                if line.startswith('object '):
                    inner_object_sha = line.split()[1]
                elif line.startswith('type '):
                    inner_object_type = line.split()[1]
                    break
            if inner_object_type == 'commit' and inner_object_sha:
                target_commit_sha = inner_object_sha
            else:
                raise ValueError(f"Tag '{tag}' points to a tag that doesn't point to a commit")
        elif object_type != 'commit':
            raise ValueError(f"Tag '{tag}' points to a {object_type}, not a commit. Releases require tags pointing to commits.")
        
        # Get revision SWHID for target commit (recursive call)
        # Use target_commit_sha which may have been resolved from nested tags
        target_revision_swhid = self._compute_revision_swhid(repo_path, commit=target_commit_sha)
        # Extract the SHA1 from the SWHID (this is the commit hash, 20 bytes)
        target_revision_sha = target_revision_swhid.split(':')[-1]
        target_revision_bytes = bytes.fromhex(target_revision_sha)
        
        # Parse tagger
        def parse_person(line):
            """Parse Git person line: 'Name <email> timestamp offset'"""
            match = re.match(r'(.+?) <(.+?)> (\d+) ([+-]\d{4})', line)
            if match:
                name, email, ts, offset = match.groups()
                # fullname should be the complete "Name <email>" string
                fullname_str = f"{name} <{email}>"
                return Person(
                    fullname=fullname_str.encode('utf-8'),
                    name=name.encode('utf-8'),
                    email=email.encode('utf-8')
                ), int(ts), offset.encode('utf-8')
            return None, None, None
        
        tagger, tagger_ts, tagger_offset = parse_person(tagger_line) if tagger_line else (None, None, None)
        
        # Get message (everything after blank line)
        message = '\n'.join(lines[message_start:]).encode('utf-8') if message_start else b''
        
        # Check if message contains GPG signature
        # For tags, GPG signatures are in the message, but swh.model's Release object
        # doesn't handle them correctly. Since we're testing swh.model, we skip signed tags.
        if b'-----BEGIN PGP SIGNATURE-----' in message:
            raise NotImplementedError(
                "Python implementation doesn't support signed tags "
                "(GPG signatures not handled by swh.model Release object)"
            )
        
        # Create timestamps
        tagger_timestamp = None
        if tagger_ts:
            tagger_timestamp = TimestampWithTimezone(
                timestamp=Timestamp(seconds=tagger_ts, microseconds=0),
                offset_bytes=tagger_offset
            )
        
        # Create Release object (for unsigned tags, swh.model works correctly)
        release = Release(
            name=tag_name.encode('utf-8'),
            target=target_revision_bytes,
            message=message,
            target_type=ReleaseTargetType.REVISION,
            author=tagger,
            date=tagger_timestamp,
            synthetic=False
        )
        
        # Format as Git object
        git_obj = release_git_object(release)
        
        # Extract content (skip header) - hash_git_data expects just the content
        header_end = git_obj.find(b'\0')
        if header_end > 0:
            content = git_obj[header_end+1:]
        else:
            content = git_obj
        
        # Hash using swh.model hashutil (same as tested in standalone tests)
        hash_bytes = hashutil.hash_git_data(content, 'tag', base_algo='sha1')
        sha1 = hashutil.hash_to_hex(hash_bytes)
        
        return f"swh:1:rel:{sha1}"
