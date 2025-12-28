# Developer Guide

Complete guide for running tests and adding new SWHID implementations.

## Quick Start

### Installation

```bash
pip install -e .[dev]
```

### Optional: Install Implementation Dependencies

Some implementations require additional dependencies:

**Ruby Implementation:**
```bash
# Install Ruby (if not already installed)
# On Ubuntu/Debian: sudo apt-get install ruby
# On macOS: ruby is usually pre-installed

# Install the swhid gem
gem install swhid

# Add gem bin directory to PATH (add to ~/.bashrc or ~/.zshrc)
export PATH="$HOME/.gem/ruby/$(ruby -e 'puts RUBY_VERSION.split(".")[0..1].join(".")')/bin:$PATH"
```

**Rust Implementation:**
- Requires Rust toolchain (installed automatically in CI)
- For local development, install via: `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`

**Python Implementations:**
- Python implementations are included automatically
- `swh.model` and `swh.core` are optional but recommended for full coverage

### Run Tests

```bash
# Run all tests with all implementations
swhid-harness --dashboard-output results.json

# Test specific categories
swhid-harness --category content --dashboard-output results.json
swhid-harness --category content,directory,git --dashboard-output results.json

# Test specific implementations
swhid-harness --impl python,rust --category content --dashboard-output results.json
```

### View Results

```bash
# Validate results
python3 -m harness.models results.json

# View JSON
cat results.json | python3 -m json.tool | less
```

## Adding a New Implementation

### Step 1: Create Directory Structure

```bash
mkdir -p implementations/my-impl
cd implementations/my-impl
touch __init__.py
```

### Step 2: Create Implementation

Create `implementation.py`:

```python
from harness.plugins.base import (
    SwhidImplementation, ImplementationInfo, ImplementationCapabilities
)
from typing import Optional
import hashlib
import os

class Implementation(SwhidImplementation):
    def get_info(self) -> ImplementationInfo:
        return ImplementationInfo(
            name="my-impl",
            version="1.0.0",
            language="python",
            description="My SWHID implementation",
            dependencies=[]
        )
    
    def is_available(self) -> bool:
        return True  # Check for dependencies here
    
    def get_capabilities(self) -> ImplementationCapabilities:
        return ImplementationCapabilities(
            supported_types=["cnt", "dir"],  # What you support
            supported_qualifiers=[],
            api_version="1.0",
            max_payload_size_mb=100,
            supports_unicode=True,
            supports_percent_encoding=False
        )
    
    def compute_swhid(self, payload_path: str, obj_type: Optional[str] = None) -> str:
        """Compute SWHID for a payload."""
        # Your implementation logic here
        if obj_type == "content":
            with open(payload_path, 'rb') as f:
                content = f.read()
            sha1 = hashlib.sha1(content).hexdigest()
            return f"swh:1:cnt:{sha1}"
        # Add other object types...
        raise ValueError(f"Unsupported object type: {obj_type}")
```

### Step 3: Test Your Implementation

```bash
# List implementations (should see yours)
swhid-harness --list-impls

# Test it
swhid-harness --impl my-impl --category content --dashboard-output test.json
python3 -m harness.models test.json
```

### Implementation Requirements

Your `Implementation` class must:

1. **Inherit from `SwhidImplementation`**
2. **Implement required methods**:
   - `get_info()` - Return implementation metadata
   - `is_available()` - Check if implementation can run
   - `get_capabilities()` - Declare supported features
   - `compute_swhid()` - Compute SWHID for a payload

3. **Handle object types**: The `obj_type` parameter can be:
   - `"content"` - File content
   - `"directory"` - Directory structure
   - `"snapshot"` - Git snapshot
   - `"revision"` - Git revision
   - `None` - Auto-detect from payload

### Example: Content-Only Implementation

```python
def compute_swhid(self, payload_path: str, obj_type: Optional[str] = None) -> str:
    if obj_type is None:
        obj_type = "content" if os.path.isfile(payload_path) else "directory"
    
    if obj_type == "content":
        with open(payload_path, 'rb') as f:
            content = f.read()
        sha1 = hashlib.sha1(content).hexdigest()
        return f"swh:1:cnt:{sha1}"
    else:
        raise ValueError(f"Only content objects supported")
```

### Example: Using External Commands

```python
import subprocess

def compute_swhid(self, payload_path: str, obj_type: Optional[str] = None) -> str:
    # Call external tool
    result = subprocess.run(
        ["my-swhid-tool", payload_path],
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout.strip()
```

See `implementations/example/implementation.py` for a complete example.

## Running Tests

### Basic Usage

```bash
# All tests, all implementations
swhid-harness --dashboard-output results.json

# Specific categories
swhid-harness --category content,directory,git --dashboard-output results.json

# Specific implementations
swhid-harness --impl python,rust --dashboard-output results.json

# Single category, single implementation
swhid-harness --impl python --category content --dashboard-output results.json
```

### Available Categories

- `content` - Content object tests
- `content/edge_cases` - Edge cases (line endings, null bytes, etc.)
- `content/qualifiers` - Lines qualifier tests
- `directory` - Directory object tests
- `directory/edge_cases` - Directory edge cases
- `git` - Git repository tests (snapshots, revisions)

### Command Options

```bash
swhid-harness --help  # Full help

# Key options:
--category CATEGORIES    # Comma-separated categories
--impl IMPLS            # Comma-separated implementations
--dashboard-output FILE  # Save results to file
--fail-fast             # Stop on first failure
--summary-only          # Show only summary
--list-impls            # List available implementations
--list-payloads         # List test payloads
```

### Viewing Results

```bash
# Validate schema
python3 -m harness.models results.json

# Pretty print JSON
cat results.json | python3 -m json.tool | less

# Extract pass rate
cat results.json | jq '.aggregates.overall.pass_rate'

# Find failures
cat results.json | jq '.tests[] | select(.results[] | .status == "FAIL")'

# Generate HTML table with color-coded results
python scripts/view_results.py results.json
python scripts/view_results.py results.json --output custom.html
```

#### HTML Results Viewer

The `scripts/view_results.py` script generates a color-coded HTML table from test results:

- **Color-coded cells**: Each cell uses a background color to indicate status:
  - Green: Conformant (PASS with matching expected SWHID)
  - Red: Non-conformant (wrong SWHID or FAIL with expected) - shows full wrong SWHID
  - Blue: Executed OK (PASS but no expected to compare)
  - Yellow: Executed Error (FAIL without expected)
  - Gray: Skipped (test was skipped)
- **Compact design**: Cells are color-only (no text labels) except for non-conformant cases which show the full wrong SWHID
- **Tooltips**: Hover over any cell to see full details (status, SWHID, expected value, errors)
- **Legend**: Color code explanation at the top of the page

The HTML table makes it easy to:
- Quickly identify which implementations disagree
- See the exact wrong SWHIDs for non-conformant cases
- Compare results across all implementations at a glance
- Share results with others (HTML is self-contained)

## Troubleshooting

### Implementation Not Found

**Problem**: Implementation doesn't appear in `--list-impls`

**Solutions**:
1. Check directory: `implementations/my-impl/implementation.py` exists
2. Verify class name: Must be `Implementation` (capital I)
3. Check inheritance: Must inherit from `SwhidImplementation`
4. Check `is_available()`: Must return `True`

### Import Errors

**Problem**: `ModuleNotFoundError` or import errors

**Solutions**:
1. Install package: `pip install -e .`
2. Check Python path: Run from project root
3. Verify imports: All imports must be available

### Payload Not Found

**Problem**: `FileNotFoundError` for payloads

**Solutions**:
1. Check `config.yaml`: Verify paths are correct
2. Check payloads exist: `ls payloads/content/`
3. Use absolute paths in config if needed

### Implementation Crashes

**Problem**: Implementation raises exception during test

**Solutions**:
1. Check error handling in `compute_swhid()`
2. Validate inputs before processing
3. Handle edge cases (empty files, permissions, etc.)
4. Check logs for detailed error messages

### Results Don't Match

**Problem**: Your implementation produces different SWHIDs

**Solutions**:
1. Verify object type detection
2. Check hash computation (SHA1 for content)
3. Verify directory entry ordering (must be sorted)
4. Check for encoding issues (UTF-8 vs bytes)
5. Compare with reference: `swh identify <payload>`

### Permission Errors

**Problem**: `PermissionError` when reading files

**Solutions**:
1. Check file permissions: `ls -l payloads/`
2. Some test payloads have special permissions (read-only, write-only)
3. Handle permission errors gracefully in your implementation

## Configuration

Test payloads are configured in `config.yaml`:

```yaml
payloads:
  content:
  - name: hello_world
    path: payloads/content/hello.txt
    expected_swhid: swh:1:cnt:...
```

To add new test payloads:
1. Add payload file to `payloads/` directory
2. Add entry to `config.yaml`
3. Optionally add `expected_swhid` for validation

## Test Payloads

Test payloads are organized by category:

- `payloads/content/` - Content object tests
- `payloads/content/edge_cases/` - Edge cases
- `payloads/content/qualifiers/` - Qualifier tests
- `payloads/directory/` - Directory tests
- `payloads/directory/edge_cases/` - Directory edge cases
- `payloads/git/` - Git repository tests

Each payload can have an `expected_swhid` in `config.yaml` for validation.

## Expected SWHIDs

Some payloads have `expected_swhid` values in `config.yaml`. These are "golden" values computed using a reference implementation. Your implementation should produce the same SWHIDs for these payloads.

To compute expected SWHIDs:
```bash
swh identify payloads/content/hello.txt
```

## Testing SWHID v2 with SHA256

The harness supports testing SWHID v2 with SHA256 hash functions alongside v1 tests.

### Generating Expected SHA256 Results

To generate expected SHA256 SWHID results from Git:

```bash
python3 tools/generate_sha256_expected.py config.yaml
```

This script:
- Creates SHA256 Git repositories for each payload
- Computes Git SHA256 object hashes (blobs, trees, commits, tags)
- Adds `expected_swhid_sha256` fields to `config.yaml`
- Preserves existing `expected_swhid` (v1) values

The script supports:
- Content objects (files)
- Directory objects (directories with files)
- Revision objects (Git commits)
- Release objects (Git annotated tags)
- Tarball extraction for git-repository payloads

**Note**: Snapshot objects are excluded as Git doesn't support snapshot object format.

### Configuring v2 Testing

In `config.yaml`, add `expected_swhid_sha256` for payloads that support v2:

```yaml
payloads:
  content:
  - name: hello_world
    path: payloads/content/hello.txt
    expected_swhid: swh:1:cnt:...  # v1 (SHA1)
    expected_swhid_sha256: swh:2:cnt:...  # v2 (SHA256)
```

Optional per-payload configuration:

```yaml
  - name: test_v2_only
    path: payloads/content/test.txt
    expected_swhid_sha256: swh:2:cnt:...
    rust_config:
      version: 2
      hash: sha256
```

### Running v2 Tests

**Run v1 tests (default)**:
```bash
swhid-harness --impl rust --category content
```

**Run v2 tests only**:
```bash
swhid-harness --impl rust --version 2 --hash sha256 --category content
```

**Run both v1 and v2 tests**:
```bash
swhid-harness --impl rust --test-both-versions --category content
```

This runs both versions when both `expected_swhid` and `expected_swhid_sha256` are present.

### CLI Flags

- `--version {1,2}`: Override SWHID version (overrides config)
- `--hash {sha1,sha256}`: Override hash algorithm (overrides config)
- `--test-both-versions`: Run both v1 and v2 when both expected values present

### Version Determination Priority

The harness determines which version(s) to test using this priority:

1. **CLI flags** (`--version`, `--hash`) - highest priority
2. **Payload rust_config** (per-payload config in `config.yaml`)
3. **Expected values presence** (`expected_swhid_sha256` indicates v2 support)
4. **Default** - v1 only

### Implementation Support

Currently, the Rust implementation supports v2/SHA256 via `--version 2 --hash sha256` flags
passed to the `swhid` binary. Other implementations will be extended as needed.

## Getting Help

- Check existing implementations in `implementations/` for examples
- See `implementations/example/` for a complete example
- Review error messages in test results JSON
- Check `config.yaml` for payload configuration

