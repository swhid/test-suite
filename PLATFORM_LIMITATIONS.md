# Platform Limitations and Expected Skips

This document describes known platform limitations and expected test skips for the SWHID Testing Harness.

**Current Test Suite Status**: See the [live test results dashboard](https://www.swhid.org/test-suite/) for up-to-date statistics across all platforms and implementations.

## Expected Test Skips

**Note**: The test suite currently includes 79 tests per implementation. Skip counts are based on the latest test run data.

### Git and Git-CMD Implementations

**17 skips** (78.5% pass rate: 62/79 tests) - Snapshot objects are not supported by Git-based implementations.

Git implementations (both `git` and `git-cmd`) compute SWHIDs using Git's hashing algorithm, which supports:
- Content objects (`cnt`)
- Directory objects (`dir`)
- Revision objects (`rev`)
- Release objects (`rel`)

However, Git does not have a native concept of snapshots (`snp`), which are Software Heritage-specific objects that represent the state of a repository at a point in time. Therefore, all snapshot tests are skipped for Git implementations.

**Current status**: Both implementations show consistent 78.5% pass rate (62/79 pass, 17 skip) across all platforms (Ubuntu, Windows, macOS).

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

**3 skips** (96.2% pass rate: 76/79 tests) - Full support for all object types using the `swh.model` Python API, except signed tags.

The Python implementation supports:
- Content objects (`cnt`) - via `swh.model.cli`
- Directory objects (`dir`) - via `swh.model.cli`
- Revision objects (`rev`) - via `swh.model` Python API (direct model object creation)
  - **Signed commits (GPG)**: Fully supported via `extra_headers` in `Revision` objects
- Release objects (`rel`) - via `swh.model` Python API (direct model object creation)
  - **Signed tags (GPG)**: **Not supported** (3 tests skipped)
  - **Unsigned tags**: Fully supported
- Snapshot objects (`snp`) - via `swh.model.cli`

**Implementation details:**
- Content, directory, and snapshot objects are computed using the `swh.model.cli` command-line interface
- Revision and release objects are computed using the `swh.model` Python API directly, since the CLI does not expose these as separate `--type` options
- The implementation parses Git commit and tag objects, creates `swh.model.model.Revision` and `swh.model.model.Release` objects, and uses `swh.model.git_objects.revision_git_object()` and `release_git_object()` to format them for hashing
- For signed commits, GPG signatures are extracted and passed via `extra_headers` to `Revision` objects
- For signed tags, tests are skipped because `swh.model`'s `Release` object doesn't properly handle GPG signatures in tag messages

**Current status**: 96.2% pass rate (76/79 pass, 3 skip) on Ubuntu and macOS. Not available on Windows.

**Affected tests (3 skips):**
- `signed_release_v1`: Signed tag v1.0.0
- `signed_release_v2`: Signed tag v2.0.0
- `signed_release_v2_1`: Signed tag v2.1.0

**Note**: Signed tags pointing to other tags (nested tags) are fully supported for unsigned tags. Signed tags are skipped to ensure we're testing `swh.model` rather than using fallback methods.

### Rust Implementation

**0 skips** (100% pass rate: 79/79 tests) - Full support across all platforms.

The Rust implementation using `swhid-rs` binary provides complete coverage:
- Content objects (`cnt`)
- Directory objects (`dir`)
- Revision objects (`rev`)
- Release objects (`rel`)
- Snapshot objects (`snp`)

**Current status**: 100% pass rate (79/79 pass) on all platforms (Ubuntu, Windows, macOS). This is the reference implementation with full cross-platform support.

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
- **Current status**: 78.5% pass rate (62/79 pass, 17 skip) across all platforms

### PyGit2 Implementation

- Uses libgit2 via pygit2 Python bindings
- **Current status**: 
  - Ubuntu/macOS: 78.5% pass rate (62/79 pass, 17 skip)
  - Windows: 74.7% pass rate (59/79 pass, 3 fail, 17 skip)
- **Windows-specific issues**: 3 test failures on Windows (likely related to permission handling or path resolution)

### Rust Implementation

- Uses external `swhid-rs` binary
- Supports both experimental (positional args) and published (--file flag) versions
- Creates temporary copies with preserved permissions on Windows

### Ruby Implementation

- Uses external `swhid` gem
- Reads content files in binary mode and passes via stdin
- Creates temporary copies with preserved permissions on Windows

**Current status**:
- Ubuntu/macOS: 100% pass rate (79/79 pass)
- Windows: 92.4% pass rate (73/79 pass, 6 fail)

**Known Windows Limitations (6 failures):**

1. **Line Ending Handling** (2 failures):
   - `crlf_line_endings`: Ruby normalizes CRLF to LF, producing different SWHID
   - `mixed_line_endings`: Ruby normalizes mixed line endings, producing different SWHID
   - **Root Cause**: The `swhid` gem likely normalizes line endings when reading files, while the SWHID spec requires preserving original line endings as part of content.

2. **Binary File Handling** (1 failure):
   - `binary_file`: Ruby produces different SWHID for binary content
   - **Root Cause**: Ruby may be applying text mode encoding/transcoding when reading binary files.

3. **File Permissions** (2 failures):
   - `permissions_dir`: Ruby cannot detect/preserve Unix-style executable permissions on Windows
   - `comprehensive_permissions`: Same issue with various permission combinations
   - **Root Cause**: Ruby's `swhid` gem on Windows likely cannot read permissions from Git index or detect executable bits, defaulting to non-executable for all files.

4. **Symlink Handling** (1 failure):
   - `mixed_types`: Ruby produces different SWHID for directories containing symlinks
   - **Root Cause**: Ruby may be following symlinks instead of preserving them, or handling symlink targets differently on Windows.

**Note**: These limitations are in the upstream `swhid` gem and would need to be fixed there, similar to how we fixed Rust by using Git index for permissions and preserving symlinks explicitly.

### Python Implementation

- Uses `swh.model.cli` module
- Does not support revision or release object types
- Limited to content, directory, and snapshot objects

## Current Test Suite Statistics

Based on the latest test run data from the [test suite dashboard](https://www.swhid.org/test-suite/):

- **Total tests**: 79 per implementation
- **Overall pass rate**: ~78-85% depending on platform
- **Platform breakdown**:
  - Ubuntu: 81.9% pass (388/474 total tests across all implementations)
  - Windows: 84.8% pass (335/395 total tests), 2.3% fail (9 failures)
  - macOS: 81.9% pass (388/474 total tests)

**Implementation summary**:
- **Rust**: 100% pass on all platforms (79/79)
- **Ruby**: 100% pass on Ubuntu/macOS (79/79), 92.4% on Windows (73/79, 6 fail)
- **Git/Git-CMD**: 78.5% pass on all platforms (62/79, 17 skip)
- **PyGit2**: 78.5% pass on Ubuntu/macOS (62/79, 17 skip), 74.7% on Windows (59/79, 3 fail, 17 skip)
- **Python**: 55.7% pass on Ubuntu/macOS (44/79, 35 skip), not available on Windows

## Testing Recommendations

1. **Windows Testing**: Ensure Developer Mode is enabled for symlink tests
2. **Permission Tests**: Verify Git index contains correct permissions for test payloads
3. **Line Ending Tests**: Ensure `.gitattributes` is respected and `core.autocrlf=false` is set
4. **Cross-Platform**: Expected SWHIDs are computed on Unix; Windows may produce different results for permission-based tests if permissions aren't preserved correctly
5. **Monitor Dashboard**: Check the [live test results dashboard](https://www.swhid.org/test-suite/) for up-to-date status across all platforms

