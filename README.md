# SWHID Testing Harness

A technology-neutral testing harness for comparing different SWHID (SoftWare Hash Identifier) implementations on standardized test payloads.

## Quick Start

### Installation

```bash
pip install -e .[dev]
```

### Optional: Install Implementation Dependencies

Some implementations require additional dependencies:

- **Ruby**: `gem install swhid` (add `~/.gem/ruby/*/bin` to PATH)
- **Rust**: Install Rust toolchain if testing Rust implementation
- **Python**: `swh.model` and `swh.core` packages are optional but recommended

### Basic Usage

```bash
# Run all tests with all implementations
swhid-harness --category content --dashboard-output results.json

# Test specific implementations
swhid-harness --impl rust,python --category content

# Test specific categories
swhid-harness --category content,directory,git
```

### Validate Results

```bash
# Validate results
python3 -m harness.models results.json

# Generate HTML table (single table, backward compatible)
python3 scripts/view_results.py results.json

# Generate separate tables per variant (recommended for v2)
python3 scripts/view_results.py results.json --output-dir output/
```

The table generator automatically detects SWHID variants (v1, v2, etc.) and can generate separate tables for each variant, making it easy to compare results across different SWHID versions, hash algorithms, and serialization formats.

## Project Structure

```
swhid-rs-tools/
├── harness/             # Core harness (plugin system, test runner)
├── implementations/     # SWHID implementation plugins
├── payloads/            # Test payloads (content, directory, archive, git)
├── tests/               # Test suite (unit, integration, property, negative)
├── tools/               # Utility scripts (merge_results, json_diff, test scripts)
├── config.yaml          # Configuration (payloads, settings)
├── DEVELOPER_GUIDE.md   # Documentation
└── README.md            # This file
```

## Adding Implementations

Implementations are auto-discovered from `implementations/`. See [Developer Guide](DEVELOPER_GUIDE.md) for details.

### Multiple Git-Based Implementations

The harness includes three Git-based implementations (`git-cmd`, `git` (dulwich), and `pygit2`) that all compute Git hashes. While they produce identical results, each serves a purpose:

- **Cross-validation**: Agreement across different libraries increases confidence in correctness
- **Availability**: Different environments may have different tools available (git CLI, dulwich, or libgit2)
- **Bug detection**: Different libraries may expose edge cases or implementation bugs
- **Performance comparison**: Different backends have different performance characteristics

These implementations are wrappers around Git's hashing algorithm and should always agree. Disagreements indicate bugs in either the harness or the underlying libraries.

## Documentation

- **[Implementation Guide](IMPLEMENTATIONS.md)** - Comprehensive overview of all SWHID implementations, their technology stack, features, and limitations
- **[Developer Guide](DEVELOPER_GUIDE.md)** - Complete guide for running tests and adding implementations
- **[Architecture](docs/architecture.md)** - System architecture, component design, and data flow
- **[Troubleshooting](docs/troubleshooting.md)** - Common issues, solutions, and debugging tips

## Testing

```bash
# Run test suite
pytest

# With coverage
pytest --cov=harness
```

## Configuration

Edit `config.yaml` to:
- Add/modify test payloads
- Adjust test settings (timeout, parallelism)
- Configure output options

### Negative Tests

Negative tests verify that implementations correctly reject invalid inputs. Add tests to the `negative` category with an `expected_error` field:

```yaml
negative:
  - description: Test file that doesn't exist (triggers IO_ERROR)
    expected_error: IO_ERROR
    name: nonexistent_file
    path: payloads/negative/nonexistent_file.txt
```

A negative test passes when all supporting implementations correctly fail (reject the invalid input). Implementations that don't support the object type are automatically skipped and don't affect the result.

### Commit Reference Resolution

The harness automatically resolves branch names, tag names, and short SHAs to full commit SHAs before passing them to implementations. This ensures all implementations receive consistent input regardless of their internal reference resolution capabilities.

### Autodiscovery expectations

For Git archives that enable `discover_branches` and/or `discover_tags`, provide
expected SWHIDs per discovered reference using the `expected` section:

```
  - name: comprehensive
    path: payloads/git-repository/comprehensive.tar.gz
    discover_branches: true
    discover_tags: true
    expected:
      branches:
        main: swh:1:rev:...
        feature-a: swh:1:rev:...
      tags:
        v1.0.0: swh:1:rel:...
```

During a run the harness looks up these values and compares the consensus SWHID
from all successful implementations with the configured expectation. Missing
entries are reported so new branches/tags can be documented explicitly.

### Unsupported payloads

Each implementation declares the SWHID object types it supports. The harness
checks those capabilities before running a test and marks incompatible payloads
as `SKIPPED` instead of counting them as failures. The run summary still lists
which implementations were skipped so that coverage gaps remain visible.

## Output Format

Results are saved in canonical JSON format (v1.0.0) with:
- Run metadata (id, timestamp, branch, commit)
- Implementation details (version, capabilities)
- Test results (status, SWHID, metrics, errors)
- Aggregated statistics


## License

GPL-3.0 - See [LICENSE](LICENSE) file.

