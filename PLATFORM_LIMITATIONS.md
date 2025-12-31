# Platform Limitations and Expected Skips

This document describes known platform limitations and expected test skips for the SWHID Testing Harness.

## Expected Test Skips

### Git and Git-CMD Implementations

**18 skips** - Snapshot objects are not supported by Git-based implementations.

Git implementations (both `git` and `git-cmd`) compute SWHIDs using Git's hashing algorithm, which supports:
- Content objects (`cnt`)
- Directory objects (`dir`)
- Revision objects (`rev`)
- Release objects (`rel`)

However, Git does not have a native concept of snapshots (`snp`), which are Software Heritage-specific objects that represent the state of a repository at a point in time. Therefore, all snapshot tests are skipped for Git implementations.

**Affected tests:**
- `alias_branches`
- `branch_ordering`
- `case_rename`
- `complex_merges`
- `dangling_branches`
- `lightweight_vs_annotated`
- `merge_commits`
- `snapshot_branch_order`
- `synthetic_repo`
- `tag_types`
- `timezone_extremes`
- `with_tags`
- And other snapshot-related tests

### Python Implementation

**36 skips** - Revision and release objects are not supported by the Python `swh.model.cli` implementation.

The Python implementation via `swh.model.cli` supports:
- Content objects (`cnt`)
- Directory objects (`dir`)
- Snapshot objects (`snp`)

However, it does not support:
- Revision objects (`rev`)
- Release objects (`rel`)

**Affected tests:**
- All revision tests (e.g., `simple_revision`, `simple_revisions_head`, `merge_revision`)
- All release tests (e.g., `annotated_release_v1`, `signed_release_v1`, `comprehensive_tag_v1.0.0`)

See `implementations/python/implementation.py` lines 69-72 for the implementation.

### Rust and Ruby Implementations

**1 skip each** - These are typically negative tests or edge cases that may not be handled by the external tools.

The specific skip may vary, but common cases include:
- Negative tests (e.g., `nonexistent_file`) if the implementation doesn't handle error cases
- Edge cases that the external tool doesn't support

## Windows-Specific Issues

### File Permissions

Windows uses ACLs (Access Control Lists) instead of Unix-style permissions. The implementations attempt to preserve executable bits by:
1. Reading permissions from the Git index (most reliable on Windows)
2. Falling back to filesystem detection
3. Applying permissions when creating Git trees or temporary copies

**Fixed issues:**
- Path normalization for permission lookups (all implementations)
- Git index permission reading (git, git-cmd, rust, ruby)

### Symlinks

Windows requires administrator privileges or Developer Mode to create symlinks. The implementations handle this by:
1. Attempting to create symlinks
2. Falling back to copying target files if symlink creation fails
3. For Git implementations, storing symlink targets as Git blob objects with mode `0o120000`

**Known limitations:**
- On Windows without Developer Mode, symlinks may be copied as regular files, which can affect SWHID computation for tests like `mixed_types`

### Line Endings

Test files with CRLF or mixed line endings are preserved as-is. The implementations:
- Read files in binary mode to preserve line endings
- Use `core.autocrlf=false` in Git repositories to prevent conversion
- Pass raw bytes to external tools via stdin

**Note:** The `.gitattributes` file marks `crlf.txt` and `mixed_line_endings.txt` as `-text` to prevent Git from converting them.

## Implementation-Specific Notes

### Git Implementation (dulwich)

- Uses dulwich library for Git operations
- Handles symlinks by storing target as blob with mode `0o120000`
- Preserves permissions by reading from source files before copying

### Git-CMD Implementation

- Uses Git command-line tools
- Configures `core.autocrlf=false` and `core.filemode=true` in test repositories
- Uses `git update-index --chmod=+x` to set executable bits on Windows

### Rust Implementation

- Uses external `swhid-rs` binary
- Supports both experimental (positional args) and published (--file flag) versions
- Creates temporary copies with preserved permissions on Windows

### Ruby Implementation

- Uses external `swhid` gem
- Reads content files in binary mode and passes via stdin
- Creates temporary copies with preserved permissions on Windows

### Python Implementation

- Uses `swh.model.cli` module
- Does not support revision or release object types
- Limited to content, directory, and snapshot objects

## Testing Recommendations

1. **Windows Testing**: Ensure Developer Mode is enabled for symlink tests
2. **Permission Tests**: Verify Git index contains correct permissions for test payloads
3. **Line Ending Tests**: Ensure `.gitattributes` is respected and `core.autocrlf=false` is set
4. **Cross-Platform**: Expected SWHIDs are computed on Unix; Windows may produce different results for permission-based tests if permissions aren't preserved correctly

