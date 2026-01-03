"""
Direct tests of swh.model capabilities for computing revision and release SWHIDs.

These tests verify that swh.model correctly:
- Formats revision objects as Git commit objects
- Formats release objects as Git tag objects
- Computes correct hashes using hashutil.hash_git_data()
- Produces SWHIDs that match known-good implementations (git-cmd)
"""

import pytest
import subprocess
import re
import os
from pathlib import Path

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
    pytestmark = pytest.mark.skip("swh.model not available")

# Test data paths
TEST_REPOS = {
    'simple_revisions': Path(__file__).parent.parent.parent / 'payloads' / 'git-repository' / 'simple_revisions' / '.git',
    'comprehensive': Path(__file__).parent.parent.parent / 'payloads' / 'git-repository' / 'comprehensive' / '.git',
    'signed_releases': Path(__file__).parent.parent.parent / 'payloads' / 'git-repository' / 'signed_releases' / '.git',
}


def parse_git_person(line: str):
    """Parse Git person line: 'Name <email> timestamp offset'"""
    match = re.match(r'(.+?) <(.+?)> (\d+) ([+-]\d{4})', line)
    if match:
        name, email, ts, offset = match.groups()
        fullname_str = f"{name} <{email}>"
        return Person(
            fullname=fullname_str.encode('utf-8'),
            name=name.encode('utf-8'),
            email=email.encode('utf-8')
        ), int(ts), offset.encode('utf-8')
    return None, None, None


def get_git_cmd_swhid(repo_path: Path, obj_type: str, commit: str = None, tag: str = None) -> str:
    """Get SWHID from git-cmd implementation (known good reference)."""
    import sys
    import importlib.util
    from pathlib import Path
    
    # Add project root to path
    project_root = Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    
    # Import using direct file path to handle git-cmd vs git_cmd naming
    git_cmd_path = project_root / 'implementations' / 'git-cmd' / 'implementation.py'
    if not git_cmd_path.exists():
        # Try alternative naming
        git_cmd_path = project_root / 'implementations' / 'git_cmd' / 'implementation.py'
    
    if git_cmd_path.exists():
        spec = importlib.util.spec_from_file_location("git_cmd_impl", git_cmd_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        impl = module.Implementation()
        return impl.compute_swhid(str(repo_path), obj_type=obj_type, commit=commit, tag=tag)
    else:
        # Fallback: use git rev-parse directly
        if obj_type == "revision":
            result = subprocess.run(
                ["git", "rev-parse", commit or "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return f"swh:1:rev:{result.stdout.strip()}"
        elif obj_type == "release":
            result = subprocess.run(
                ["git", "rev-parse", tag],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return f"swh:1:rel:{result.stdout.strip()}"
        else:
            raise ValueError(f"Unknown object type: {obj_type}")


class TestSwhModelDirect:
    """Direct tests of swh.model capabilities."""
    
    def test_hash_git_data_with_commit(self):
        """Test that hashutil.hash_git_data() correctly hashes Git commit objects."""
        repo_path = TEST_REPOS['simple_revisions']
        if not repo_path.exists():
            pytest.skip(f"Test repo not found: {repo_path}")
        
        # Get a commit SHA
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        commit_sha = result.stdout.strip()
        
        # Get raw commit object (content only, no header)
        commit_result = subprocess.run(
            ["git", "cat-file", "commit", commit_sha],
            cwd=repo_path,
            capture_output=True
        )
        commit_content = commit_result.stdout
        
        # Hash using swh.model
        hash_bytes = hashutil.hash_git_data(commit_content, 'commit', base_algo='sha1')
        computed_sha = hashutil.hash_to_hex(hash_bytes)
        
        assert computed_sha == commit_sha, \
            f"hash_git_data() should produce same hash as Git: {computed_sha} != {commit_sha}"
    
    def test_hash_git_data_with_tag(self):
        """Test that hashutil.hash_git_data() correctly hashes Git tag objects."""
        repo_path = TEST_REPOS['comprehensive']
        if not repo_path.exists():
            pytest.skip(f"Test repo not found: {repo_path}")
        
        # Get a tag
        tag_result = subprocess.run(
            ["git", "tag", "-l"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        if not tag_result.stdout.strip():
            pytest.skip("No tags found in test repo")
        
        tag = tag_result.stdout.strip().split('\n')[0]
        
        # Get tag object SHA
        tag_sha_result = subprocess.run(
            ["git", "rev-parse", tag],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        tag_sha = tag_sha_result.stdout.strip()
        
        # Get raw tag object (content only, no header)
        tag_result = subprocess.run(
            ["git", "cat-file", "tag", tag],
            cwd=repo_path,
            capture_output=True
        )
        tag_content = tag_result.stdout
        
        # Hash using swh.model
        hash_bytes = hashutil.hash_git_data(tag_content, 'tag', base_algo='sha1')
        computed_sha = hashutil.hash_to_hex(hash_bytes)
        
        assert computed_sha == tag_sha, \
            f"hash_git_data() should produce same hash as Git: {computed_sha} != {tag_sha}"
    
    def test_revision_git_object_format(self):
        """Test that revision_git_object() produces Git-compatible format."""
        repo_path = TEST_REPOS['simple_revisions']
        if not repo_path.exists():
            pytest.skip(f"Test repo not found: {repo_path}")
        
        # Get a commit
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        commit_sha = result.stdout.strip()
        
        # Get commit object (pretty-printed for parsing)
        commit_result = subprocess.run(
            ["git", "cat-file", "-p", commit_sha],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse commit
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
                author_line = line[7:]
            elif line.startswith('committer '):
                committer_line = line[10:]
            elif line == '' and message_start is None:
                message_start = i + 1
                break
        
        # Parse person data
        author, author_ts, author_offset = parse_git_person(author_line)
        committer, committer_ts, committer_offset = parse_git_person(committer_line)
        
        # Get message
        message = '\n'.join(lines[message_start:]).encode('utf-8') if message_start else b''
        
        # Create Revision object
        revision = Revision(
            message=message,
            author=author,
            committer=committer,
            date=TimestampWithTimezone(
                timestamp=Timestamp(seconds=author_ts, microseconds=0),
                offset_bytes=author_offset
            ),
            committer_date=TimestampWithTimezone(
                timestamp=Timestamp(seconds=committer_ts, microseconds=0),
                offset_bytes=committer_offset
            ),
            type=RevisionType.GIT,
            directory=bytes.fromhex(tree_sha),
            synthetic=False,
            parents=tuple(bytes.fromhex(p) for p in parents)
        )
        
        # Format as Git object
        git_obj = revision_git_object(revision)
        
        # Extract content (skip header)
        header_end = git_obj.find(b'\0')
        assert header_end > 0, "Git object should have header"
        formatted_content = git_obj[header_end+1:]
        
        # Get actual Git commit content
        raw_result = subprocess.run(
            ["git", "cat-file", "commit", commit_sha],
            cwd=repo_path,
            capture_output=True
        )
        actual_content = raw_result.stdout
        
        # Compare content (should match byte-for-byte)
        assert formatted_content == actual_content, \
            f"revision_git_object() should produce Git-compatible format. " \
            f"Lengths: {len(formatted_content)} vs {len(actual_content)}"
    
    def test_release_git_object_format(self):
        """Test that release_git_object() produces Git-compatible format."""
        repo_path = TEST_REPOS['comprehensive']
        if not repo_path.exists():
            pytest.skip(f"Test repo not found: {repo_path}")
        
        # Get a tag
        tag_result = subprocess.run(
            ["git", "tag", "-l"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        if not tag_result.stdout.strip():
            pytest.skip("No tags found in test repo")
        
        tag = tag_result.stdout.strip().split('\n')[0]
        
        # Get tag object SHA
        tag_sha_result = subprocess.run(
            ["git", "rev-parse", tag],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        tag_sha = tag_sha_result.stdout.strip()
        
        # Get tag object (pretty-printed for parsing)
        tag_result = subprocess.run(
            ["git", "cat-file", "-p", tag],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse tag
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
                tag_name = line[4:].strip()
            elif line.startswith('tagger '):
                tagger_line = line[7:]
            elif line == '' and message_start is None:
                message_start = i + 1
                break
        
        if object_type != 'commit':
            pytest.skip(f"Tag points to {object_type}, not commit")
        
        # Get revision SWHID for target (simplified - just use the commit SHA)
        target_revision_bytes = bytes.fromhex(object_sha)
        
        # Parse tagger
        tagger, tagger_ts, tagger_offset = parse_git_person(tagger_line) if tagger_line else (None, None, None)
        
        # Get message
        message = '\n'.join(lines[message_start:]).encode('utf-8') if message_start else b''
        if message and not message.endswith(b'\n'):
            message += b'\n'
        
        # Create Release object
        release = Release(
            name=(tag_name or tag).encode('utf-8'),
            target=target_revision_bytes,
            message=message,
            target_type=ReleaseTargetType.REVISION,
            author=tagger,
            date=TimestampWithTimezone(
                timestamp=Timestamp(seconds=tagger_ts, microseconds=0),
                offset_bytes=tagger_offset
            ) if tagger_ts else None,
            synthetic=False
        )
        
        # Format as Git object
        git_obj = release_git_object(release)
        
        # Extract content (skip header)
        header_end = git_obj.find(b'\0')
        assert header_end > 0, "Git object should have header"
        formatted_content = git_obj[header_end+1:]
        
        # Get actual Git tag content
        raw_result = subprocess.run(
            ["git", "cat-file", "tag", tag],
            cwd=repo_path,
            capture_output=True
        )
        actual_content = raw_result.stdout
        
        # Compare content (should match byte-for-byte)
        assert formatted_content == actual_content, \
            f"release_git_object() should produce Git-compatible format. " \
            f"Lengths: {len(formatted_content)} vs {len(actual_content)}"
    
    def test_revision_swhid_computation(self):
        """Test computing revision SWHID using swh.model matches git-cmd."""
        repo_path = TEST_REPOS['simple_revisions']
        if not repo_path.exists():
            pytest.skip(f"Test repo not found: {repo_path}")
        
        # Get a commit
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        commit_sha = result.stdout.strip()
        
        # Compute using swh.model (same logic as implementation.py)
        # Parse commit
        commit_result = subprocess.run(
            ["git", "cat-file", "-p", commit_sha],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        
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
                author_line = line[7:]
            elif line.startswith('committer '):
                committer_line = line[10:]
            elif line == '' and message_start is None:
                message_start = i + 1
                break
        
        author, author_ts, author_offset = parse_git_person(author_line)
        committer, committer_ts, committer_offset = parse_git_person(committer_line)
        message = '\n'.join(lines[message_start:]).encode('utf-8') if message_start else b''
        
        revision = Revision(
            message=message,
            author=author,
            committer=committer,
            date=TimestampWithTimezone(
                timestamp=Timestamp(seconds=author_ts, microseconds=0),
                offset_bytes=author_offset
            ),
            committer_date=TimestampWithTimezone(
                timestamp=Timestamp(seconds=committer_ts, microseconds=0),
                offset_bytes=committer_offset
            ),
            type=RevisionType.GIT,
            directory=bytes.fromhex(tree_sha),
            synthetic=False,
            parents=tuple(bytes.fromhex(p) for p in parents)
        )
        
        # Format and hash
        git_obj = revision_git_object(revision)
        import hashlib
        sha1 = hashlib.sha1(git_obj).hexdigest()
        swh_model_swhid = f"swh:1:rev:{sha1}"
        
        # Compare with git-cmd (known good)
        git_cmd_swhid = get_git_cmd_swhid(repo_path, "revision", commit=commit_sha)
        
        assert swh_model_swhid == git_cmd_swhid, \
            f"swh.model SWHID should match git-cmd: {swh_model_swhid} != {git_cmd_swhid}"
    
    def test_release_swhid_computation(self):
        """Test computing release SWHID using swh.model matches git-cmd."""
        repo_path = TEST_REPOS['comprehensive']
        if not repo_path.exists():
            pytest.skip(f"Test repo not found: {repo_path}")
        
        # Get a tag
        tag_result = subprocess.run(
            ["git", "tag", "-l"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        if not tag_result.stdout.strip():
            pytest.skip("No tags found in test repo")
        
        tag = tag_result.stdout.strip().split('\n')[0]
        
        # Compute using swh.model
        # Get tag object
        tag_result = subprocess.run(
            ["git", "cat-file", "-p", tag],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        
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
                tag_name = line[4:].strip()
            elif line.startswith('tagger '):
                tagger_line = line[7:]
            elif line == '' and message_start is None:
                message_start = i + 1
                break
        
        if object_type != 'commit':
            pytest.skip(f"Tag points to {object_type}, not commit")
        
        target_revision_bytes = bytes.fromhex(object_sha)
        tagger, tagger_ts, tagger_offset = parse_git_person(tagger_line) if tagger_line else (None, None, None)
        message = '\n'.join(lines[message_start:]).encode('utf-8') if message_start else b''
        if message and not message.endswith(b'\n'):
            message += b'\n'
        
        release = Release(
            name=(tag_name or tag).encode('utf-8'),
            target=target_revision_bytes,
            message=message,
            target_type=ReleaseTargetType.REVISION,
            author=tagger,
            date=TimestampWithTimezone(
                timestamp=Timestamp(seconds=tagger_ts, microseconds=0),
                offset_bytes=tagger_offset
            ) if tagger_ts else None,
            synthetic=False
        )
        
        # Format and hash
        git_obj = release_git_object(release)
        import hashlib
        sha1 = hashlib.sha1(git_obj).hexdigest()
        swh_model_swhid = f"swh:1:rel:{sha1}"
        
        # Compare with git-cmd (known good)
        git_cmd_swhid = get_git_cmd_swhid(repo_path, "release", tag=tag)
        
        assert swh_model_swhid == git_cmd_swhid, \
            f"swh.model SWHID should match git-cmd: {swh_model_swhid} != {git_cmd_swhid}"
    
    def test_model_objects_from_git(self):
        """Test creating Revision/Release objects from Git data with edge cases."""
        repo_path = TEST_REPOS['simple_revisions']
        if not repo_path.exists():
            pytest.skip(f"Test repo not found: {repo_path}")
        
        # Test that we can create Revision objects from various commits
        commits = []
        result = subprocess.run(
            ["git", "rev-list", "--all"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            commits = result.stdout.strip().split('\n')[:3]  # Test first 3 commits
        
        for commit_sha in commits:
            if not commit_sha:
                continue
            
            # Get commit object
            commit_result = subprocess.run(
                ["git", "cat-file", "-p", commit_sha],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Parse and create Revision
            lines = commit_result.stdout.split('\n')
            tree_sha = [l.split()[1] for l in lines if l.startswith('tree ')][0]
            parents = [l.split()[1] for l in lines if l.startswith('parent ')]
            author_line = [l[7:] for l in lines if l.startswith('author ')][0]
            committer_line = [l[10:] for l in lines if l.startswith('committer ')][0]
            message_start = next(i+1 for i, l in enumerate(lines) if l == '')
            
            author, author_ts, author_offset = parse_git_person(author_line)
            committer, committer_ts, committer_offset = parse_git_person(committer_line)
            message = '\n'.join(lines[message_start:]).encode('utf-8')
            
            # Create Revision object - should not raise exceptions
            revision = Revision(
                message=message,
                author=author,
                committer=committer,
                date=TimestampWithTimezone(
                    timestamp=Timestamp(seconds=author_ts, microseconds=0),
                    offset_bytes=author_offset
                ),
                committer_date=TimestampWithTimezone(
                    timestamp=Timestamp(seconds=committer_ts, microseconds=0),
                    offset_bytes=committer_offset
                ),
                type=RevisionType.GIT,
                directory=bytes.fromhex(tree_sha),
                synthetic=False,
                parents=tuple(bytes.fromhex(p) for p in parents)
            )
            
            # Should be able to format it
            git_obj = revision_git_object(revision)
            assert len(git_obj) > 0, "revision_git_object() should produce output"
            
            # Should be able to hash it
            import hashlib
            sha1 = hashlib.sha1(git_obj).hexdigest()
            assert len(sha1) == 40, "SHA1 should be 40 hex characters"
            assert sha1 == commit_sha, f"Hash should match commit SHA: {sha1} != {commit_sha}"

