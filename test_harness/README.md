# SWHID Testing Harness

A technology-neutral testing harness for comparing different SWHID implementations on standardized test payloads.

## Purpose

This testing harness allows you to:
- Compare SWHID outputs from different implementations (Rust, Python, etc.)
- Validate that implementations produce identical results for the same inputs
- Test edge cases and complex scenarios consistently across implementations
- Ensure compatibility with the Software Heritage specification

## Structure

```
test_harness/
├── README.md              # This file
├── payloads/              # Test payloads (files, directories, archives)
├── expected/              # Expected SWHID results for each payload
├── runners/               # Implementation-specific runners
│   ├── rust_runner.py     # Rust implementation runner
│   └── python_runner.py   # Python implementation runner
├── harness.py             # Main testing harness
├── config.yaml            # Configuration file
└── results/               # Test results output
```

## Test Payloads

The harness includes various test payloads to validate different SWHID types:

### Content Objects
- Empty files
- Small text files
- Large binary files
- Files with special characters
- Files with Unicode content

### Directory Objects
- Empty directories
- Directories with files
- Directories with subdirectories
- Directories with symlinks
- Directories with special permissions

### Archive Objects
- Tar archives
- Zip archives
- Compressed archives (tar.gz, tar.bz2)
- Archives with nested structures

### Git Objects
- Simple Git repositories
- Repositories with branches
- Repositories with tags
- Repositories with complex history

## Usage

### Basic Usage

```bash
# Run all tests
python test_harness/harness.py

# Run specific implementation
python test_harness/harness.py --impl rust

# Run specific test category
python test_harness/harness.py --category content

# Generate expected results
python test_harness/harness.py --generate-expected
```

### Configuration

Edit `config.yaml` to configure:
- Available implementations
- Test payloads to include/exclude
- Output formats
- Comparison tolerances

### Adding New Implementations

1. Create a runner in `runners/`
2. Implement the required interface
3. Add to configuration
4. Test with existing payloads

## Output

The harness produces:
- Detailed test reports
- Comparison summaries
- Performance metrics
- Compatibility matrices

## Contributing

To add new test payloads:
1. Add files to `payloads/`
2. Update `config.yaml`
3. Generate expected results
4. Test with all implementations 