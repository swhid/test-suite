# SWHID Implementation Guide

This document provides a comprehensive overview of all SWHID implementations available in the test harness, including their technology stack, purpose, supported features, and known limitations.

**Current Test Suite Status**: See the [live test results dashboard](https://www.swhid.org/test-suite/) for up-to-date statistics across all platforms and implementations.

## Quick Reference

| Implementation | Technology | Language | Supported Types | Platforms | Pass Rate |
|---------------|------------|----------|----------------|-----------|-----------|
| **rust** | swhid-rs binary | Rust | cnt, dir, rev, rel, snp | All | 100% (79/79) |
| **ruby** | swhid gem | Ruby | cnt, dir, rev, rel, snp | All | 100% (Ubuntu/macOS), 92.4% (Windows) |
| **git** | dulwich library | Python | cnt, dir, rev, rel | All | 78.5% (62/79, 17 skip) |
| **git-cmd** | Git CLI | Shell | cnt, dir, rev, rel | All | 78.5% (62/79, 17 skip) |
| **pygit2** | libgit2 (pygit2) | Python | cnt, dir, rev, rel | All | 78.5% (Ubuntu/macOS), 74.7% (Windows) |
| **python** | swh.model.cli | Python | cnt, dir, rev, rel, snp | Ubuntu/macOS | 96.2% (76/79, 3 skip) |

## Why Multiple Implementations?

The test harness includes multiple implementations for several important reasons:

1. **Cross-validation**: Agreement across different libraries and tools increases confidence in correctness. When multiple implementations produce identical SWHIDs, we can be confident the result is correct.

2. **Availability**: Different environments may have different tools available. Some systems may have Git CLI but not Python libraries, or vice versa.

3. **Bug detection**: Different libraries may expose edge cases or implementation bugs that would go unnoticed with a single implementation.

4. **Performance comparison**: Different backends have different performance characteristics, allowing us to understand trade-offs.

5. **Reference implementation**: The Rust implementation serves as a reference with full cross-platform support and all features.

---

## Git-Based Implementations

The harness includes three Git-based implementations that all compute SWHIDs using Git's hashing algorithm. They should produce identical results for the same inputs.

### git (dulwich)

**Technology Stack:**
- **Library**: [dulwich](https://www.dulwich.io/) - Pure Python Git implementation
- **Language**: Python
- **Dependencies**: `dulwich` Python package
- **Invocation**: Direct Python library calls (`dulwich.objects`, `dulwich.repo`)

**Purpose:**
- Pure Python implementation, no external Git binary required
- Useful in environments where Git CLI is not available or cannot be installed
- Cross-platform compatibility through Python

**Supported SWHID Types:**
- ✅ Content (`cnt`)
- ✅ Directory (`dir`)
- ✅ Revision (`rev`)
- ✅ Release (`rel`)
- ❌ Snapshot (`snp`) - **Not supported** (17 tests skipped)

**Limitations:**
- Does not support snapshot objects (Git has no native snapshot concept)
- Requires Python and dulwich library installation

**Platform Status:**
- **All platforms**: 78.5% pass rate (62/79 pass, 17 skip)
- Consistent behavior across Ubuntu, Windows, and macOS

**Implementation Details:**
- Uses `dulwich.objects.Blob` for content hashing
- Creates temporary Git repositories for directory tree computation
- Reads permissions from Git index on Windows for cross-platform consistency
- Handles symlinks by storing target as blob with mode `0o120000`

---

### git-cmd

**Technology Stack:**
- **Tool**: Git command-line interface
- **Language**: Shell (subprocess calls)
- **Dependencies**: `git` binary in PATH
- **Invocation**: Subprocess calls to `git` commands (`git hash-object`, `git write-tree`, `git rev-parse`)

**Purpose:**
- Uses the official Git CLI, ensuring compatibility with standard Git behavior
- Most widely available Git implementation
- Useful for validating that other implementations match Git's native behavior

**Supported SWHID Types:**
- ✅ Content (`cnt`)
- ✅ Directory (`dir`)
- ✅ Revision (`rev`)
- ✅ Release (`rel`)
- ❌ Snapshot (`snp`) - **Not supported** (17 tests skipped)

**Limitations:**
- Does not support snapshot objects (Git has no native snapshot concept)
- Requires Git binary to be installed and available in PATH
- Creates temporary Git repositories for directory computation

**Platform Status:**
- **All platforms**: 78.5% pass rate (62/79 pass, 17 skip)
- Consistent behavior across Ubuntu, Windows, and macOS

**Implementation Details:**
- Uses `git hash-object --no-filters` for content hashing (preserves line endings)
- Configures `core.autocrlf=false`, `core.filemode=true`, `core.precomposeunicode=false` in test repos
- Uses `git update-index --chmod=+x` to set executable bits on Windows
- Reads permissions from Git index for cross-platform consistency

---

### pygit2

**Technology Stack:**
- **Library**: [libgit2](https://libgit2.org/) via [pygit2](https://www.pygit2.org/) Python bindings
- **Language**: Python (C library bindings)
- **Dependencies**: `pygit2` Python package (requires libgit2 C library)
- **Invocation**: Python library calls to `pygit2` module

**Purpose:**
- Uses libgit2, a portable C library implementation of Git
- Provides a different codebase than dulwich for cross-validation
- Useful in environments where libgit2 is available but Git CLI is not

**Supported SWHID Types:**
- ✅ Content (`cnt`)
- ✅ Directory (`dir`)
- ✅ Revision (`rev`)
- ✅ Release (`rel`)
- ❌ Snapshot (`snp`) - **Not supported** (17 tests skipped)

**Limitations:**
- Does not support snapshot objects (Git has no native snapshot concept)
- Requires libgit2 C library and pygit2 Python bindings
- **Windows-specific issues**: 3 test failures on Windows (likely related to permission handling or path resolution)

**Platform Status:**
- **Ubuntu/macOS**: 78.5% pass rate (62/79 pass, 17 skip)
- **Windows**: 74.7% pass rate (59/79 pass, 3 fail, 17 skip)

**Implementation Details:**
- Uses `pygit2.init_repository()` to create temporary repositories
- Uses `repo.create_blob()` for content hashing
- Uses `repo.TreeBuilder()` for directory tree creation
- Handles symlinks using `pygit2.GIT_FILEMODE_LINK`
- Detects executable files using filesystem permissions (may have issues on Windows)

**Known Issues:**
- Windows: 3 test failures (investigation needed for permission handling or path resolution)

---

## Python Implementation

**Technology Stack:**
- **Library**: `swh.model` Python package (Software Heritage official library)
- **Language**: Python
- **Dependencies**: `swh.model` Python package (Software Heritage official library)
- **Invocation**: 
  - Content, directory, snapshot: Subprocess call to `python3 -m swh.model.cli`
  - Revision, release: Direct Python API calls to `swh.model` library

**Purpose:**
- Official Software Heritage Python implementation
- Provides reference implementation from the Software Heritage project
- Useful for validating against the official SWHID computation logic
- Uses both CLI and Python API depending on object type

**Supported SWHID Types:**
- ✅ Content (`cnt`) - via `swh.model.cli`
- ✅ Directory (`dir`) - via `swh.model.cli`
- ✅ Revision (`rev`) - via `swh.model` Python API
- ✅ Release (`rel`) - via `swh.model` Python API
- ✅ Snapshot (`snp`) - via `swh.model.cli`

**Implementation Details:**
- **Content, Directory, Snapshot**: Invoked via `python3 -m swh.model.cli --type <obj_type> <payload_path>`
  - Auto-detects object type if not specified
  - Output format: `SWHID\tfilename` (SWHID is extracted from first column)
- **Revision**: Uses `swh.model` Python API directly
  - Parses Git commit objects using `git cat-file`
  - For **unsigned commits**: Creates `swh.model.model.Revision` objects and uses `swh.model.git_objects.revision_git_object()` to format for hashing
  - For **signed commits (GPG)**: Extracts GPG signature from raw Git object and passes via `extra_headers` to `Revision` object
    - Removes leading spaces from GPG signature continuation lines (swh.model adds them back automatically)
    - Uses `swh.model.hashutil.hash_git_data()` to compute SHA1 hash
  - Uses `swh.model.hashutil.hash_to_hex()` to convert hash bytes to hex string
  - Formats as SWHID
- **Release**: Uses `swh.model` Python API for unsigned tags, skips signed tags
  - For **unsigned tags**: Uses `swh.model` Python API directly
    - Parses Git tag objects using `git cat-file`
    - Creates `swh.model.model.Release` objects and uses `swh.model.git_objects.release_git_object()` to format for hashing
    - Uses `swh.model.hashutil.hash_git_data()` to compute SHA1 hash
  - For **signed tags (GPG)**: Tests are skipped (raises `NotImplementedError`)
    - **Note**: `swh.model`'s `Release` object doesn't support `extra_headers` like `Revision` does, and GPG signatures in tag messages aren't handled correctly by `swh.model`
    - Since the goal is to test `swh.model`, we skip signed tags rather than using a fallback that bypasses `swh.model`

**Testing:**
- Comprehensive standalone tests in `tests/unit/test_swh_model_direct.py` verify that `swh.model` correctly:
  - Formats revision/release objects as Git objects (byte-for-byte match)
  - Computes correct hashes using `hashutil.hash_git_data()`
  - Produces SWHIDs that match git-cmd implementation (known good reference)

**Limitations:**
- **Not available on Windows** (only Ubuntu and macOS)
- **Signed releases (tags)**: Tests are skipped (3 tests) because `swh.model`'s `Release` object doesn't properly handle GPG signatures in tag messages. Since the goal is to test `swh.model`, we skip these tests rather than using a fallback that bypasses `swh.model`. Unsigned tags are fully supported via `swh.model`.
- Signed tags pointing to other tags (nested tags) are fully supported via recursive resolution for unsigned tags

**Platform Status:**
- **Ubuntu/macOS**: 96.2% pass rate (76/79 pass, 3 skip)
  - 3 signed release tests are skipped (signed_release_v1, signed_release_v2, signed_release_v2_1)
- **Windows**: Not available

---

## Ruby Implementation

**Technology Stack:**
- **Tool**: `swhid` Ruby gem (external binary)
- **Language**: Ruby
- **Dependencies**: `swhid` Ruby gem installed via `gem install swhid`
- **Invocation**: Subprocess call to `swhid` binary with various commands

**Purpose:**
- Official Software Heritage Ruby implementation
- Provides reference implementation from the Software Heritage project
- Full support for all SWHID object types

**Supported SWHID Types:**
- ✅ Content (`cnt`)
- ✅ Directory (`dir`)
- ✅ Revision (`rev`)
- ✅ Release (`rel`)
- ✅ Snapshot (`snp`)

**SWHID Version Support:**
- ✅ v1/SHA1 only (v2/SHA256 not supported)

**Platform Status:**
- **Ubuntu/macOS**: 100% pass rate (79/79 pass)
- **Windows**: 92.4% pass rate (73/79 pass, 6 fail)

**Implementation Details:**
- Binary detection: Searches gem-specific paths first (`~/.gem/ruby/*/bin/swhid`, `GEM_HOME/bin/swhid`)
- On Windows, handles `.bat` and `.cmd` wrapper files
- Content files are read in binary mode and passed via stdin
- Creates temporary copies with preserved permissions on Windows

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

---

## Rust Implementation

**Technology Stack:**
- **Tool**: `swhid-rs` binary (Rust implementation)
- **Language**: Rust
- **Dependencies**: Rust toolchain (`cargo`, `rustc`) or pre-built `swhid` binary
- **Invocation**: Subprocess call to `swhid` binary with various commands

**Purpose:**
- **Reference implementation** with full cross-platform support
- Most complete and reliable implementation
- Supports both SWHID v1 and v2

**Supported SWHID Types:**
- ✅ Content (`cnt`)
- ✅ Directory (`dir`)
- ✅ Revision (`rev`)
- ✅ Release (`rel`)
- ✅ Snapshot (`snp`)

**SWHID Version Support:**
- ✅ v1/SHA1 (default)
- ✅ v2/SHA256 (via `--version 2 --hash sha256` flags) as an experimental feature towards SWHID v2

**Platform Status:**
- **All platforms**: 100% pass rate (79/79 pass)
- Consistent behavior across Ubuntu, Windows, and macOS

**Special Features:**

1. **SWHID v2/SHA256 Support**: Unique among implementations, supports SWHID v2 with SHA256 hashing
   - Invoked with `--version 2 --hash sha256` flags
   - Enables testing of experimental next-generation SWHID formats

2. **Auto-detection of Content Command Format**: 
   - Supports both experimental format (`swhid content <path>`) and published format (`swhid content --file <path>`)
   - Automatically detects which format the binary supports

3. **Advanced Permission Handling on Windows**:
   - Creates temporary Git repositories with permissions set in Git index
   - Uses `--permissions-source auto` to discover and use Git index
   - Ensures cross-platform consistency for executable file permissions

4. **Git Feature Support**:
   - Requires `--features git` when building from source
   - Supports revision, release, and snapshot computation for Git repositories

**Implementation Details:**
- Binary resolution: Checks `SWHID_RS_PATH` environment variable first, then PATH, then builds from source
- Content: Supports both positional argument and `--file` flag formats
- Directory: Uses `--permissions-source auto` to discover Git repo and use Git index
- Git operations: Uses `swhid git <command> <repo> [args]` format
- Short SHA resolution: Uses `git rev-parse` to resolve short SHAs to full SHAs before passing to Rust tool

**Limitations:**
- None (reference implementation)

---

## Cross-Platform Compatibility Matrix

| Implementation | Ubuntu | macOS | Windows | Notes |
|---------------|--------|-------|---------|-------|
| **rust** | ✅ 100% | ✅ 100% | ✅ 100% | Reference implementation |
| **ruby** | ✅ 100% | ✅ 100% | ⚠️ 92.4% | 6 Windows failures (upstream issues) |
| **git** | ✅ 78.5% | ✅ 78.5% | ✅ 78.5% | 17 skips (no snapshot support) |
| **git-cmd** | ✅ 78.5% | ✅ 78.5% | ✅ 78.5% | 17 skips (no snapshot support) |
| **pygit2** | ✅ 78.5% | ✅ 78.5% | ⚠️ 74.7% | 17 skips + 3 Windows failures |
| **python** | ✅ 96.2% | ✅ 96.2% | ❌ N/A | 3 skips (signed tags), Windows not available |

**Legend:**
- ✅ Full support (or expected skips only)
- ⚠️ Partial support (some failures)
- ❌ Not available

---

## SWHID Object Type Support Matrix

| Implementation | Content | Directory | Revision | Release | Snapshot |
|---------------|---------|-----------|----------|---------|----------|
| **rust** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **ruby** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **git** | ✅ | ✅ | ✅ | ✅ | ❌ |
| **git-cmd** | ✅ | ✅ | ✅ | ✅ | ❌ |
| **pygit2** | ✅ | ✅ | ✅ | ✅ | ❌ |
| **python** | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## SWHID Version Support

| Implementation | v1/SHA1 | v2/SHA256 |
|---------------|---------|-----------|
| **rust** | ✅ | ✅ |
| **ruby** | ✅ | ❌ |
| **git** | ✅ | ❌ |
| **git-cmd** | ✅ | ❌ |
| **pygit2** | ✅ | ❌ |
| **python** | ✅ | ❌ |

**Note**: Only the Rust implementation currently supports SWHID v2 with SHA256 hashing. This is a forward-looking feature for testing the next generation of SWHID identifiers.

---

## Choosing an Implementation

### For Development and Testing
- **Use Rust**: Reference implementation with 100% pass rate and full feature support
- **Use Ruby**: Good alternative on Unix systems, but has Windows limitations

### For Cross-Validation
- **Use Git-based implementations**: When you need to validate against Git's native hashing algorithm
- **Use multiple implementations**: Run tests with multiple implementations to increase confidence

### For Specific Use Cases
- **Content/Directory only**: Python implementation is sufficient (but limited to Unix)
- **Full Git repository support**: Use Rust or Ruby
- **SWHID v2 testing**: Only Rust supports this

### Platform Considerations
- **Windows**: Rust is the most reliable (100% pass rate)
- **Unix systems**: All implementations work, but Python is not available on Windows
- **Minimal dependencies**: Git-CMD requires only Git CLI, dulwich requires only Python

---

## Implementation Discovery

All implementations are auto-discovered from the `implementations/` directory. Each implementation must:

1. Provide a class named `Implementation` that extends `SwhidImplementation`
2. Implement required methods: `get_info()`, `is_available()`, `get_capabilities()`, `compute_swhid()`
3. Declare supported SWHID object types in `get_capabilities()`

See [Developer Guide](DEVELOPER_GUIDE.md) for details on adding new implementations.

---

## Related Documentation

- **[Platform Limitations](PLATFORM_LIMITATIONS.md)** - Detailed platform-specific issues and expected test skips
- **[Developer Guide](DEVELOPER_GUIDE.md)** - Guide for running tests and adding implementations
- **[Test Suite Dashboard](https://www.swhid.org/test-suite/)** - Live test results across all platforms

