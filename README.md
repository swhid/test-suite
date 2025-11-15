# SWHID Testing Harness

A technology-neutral testing harness for comparing different SWHID (Software Heritage Identifier) implementations on standardized test payloads.

## Quick Start

### Installation

```bash
pip install -e .[dev]
```

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

# Generate HTML table with color-coded results
python3 scripts/view_results.py results.json
```

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

- **[Developer Guide](DEVELOPER_GUIDE.md)** - Complete guide for running tests and adding implementations

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

## Output Format

Results are saved in canonical JSON format (v1.0.0) with:
- Run metadata (id, timestamp, branch, commit)
- Implementation details (version, capabilities)
- Test results (status, SWHID, metrics, errors)
- Aggregated statistics


## License

GPL-3.0 - See [LICENSE](LICENSE) file.

