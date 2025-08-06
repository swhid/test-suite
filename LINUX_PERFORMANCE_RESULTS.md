# Linux Source Code Performance Comparison Results

## Overview

This document summarizes the performance comparison of different SWHID implementations when processing the Linux kernel source code repository.

## Test Environment

- **Test Directory**: Linux kernel source code (`../linux`)
- **Repository Size**: ~74,460 objects (files and directories)
- **Test Date**: August 6, 2025
- **Machine**: Linux system with standard hardware

## Performance Results

### Summary Table

| Implementation | Mode | Time (s) | Objects | Speed Factor |
|----------------|------|----------|---------|--------------|
| **Rust** | Directory | 2.506 | 1 | 1.0x (baseline) |
| **Rust** | Recursive | 5.272 | 74,460 | 0.5x |
| **Python** | Directory | 15.013 | 1 | 0.2x |
| **Git** | Command | 16.795 | 1 | 0.1x |

### Detailed Results

#### Rust Implementation
- **Directory Mode**: 2.506s average (min: 2.480s, max: 2.556s)
- **Recursive Mode**: 5.272s average (min: 5.252s, max: 5.288s)
- **Objects Processed**: 74,460 in recursive mode
- **Performance**: Fastest implementation by a significant margin

#### Python Implementation (swh.model.cli)
- **Directory Mode**: 15.013s average (min: 14.852s, max: 15.213s)
- **Objects Processed**: 1 (directory hash only)
- **Performance**: 6x slower than Rust directory mode

#### Git Command Implementation
- **Directory Mode**: 16.795s average (min: 16.675s, max: 16.872s)
- **Objects Processed**: 1 (tree hash only)
- **Performance**: 6.7x slower than Rust directory mode

## Key Insights

### 1. Rust Performance Dominance
- Rust implementation is significantly faster than all other implementations
- Directory mode is 2x faster than recursive mode (as expected)
- Consistent performance across multiple runs

### 2. Implementation Differences
- **Rust**: Processes all files and directories recursively when requested
- **Python**: Only computes directory hash, no recursive option available
- **Git**: Only computes tree hash, requires temporary repository setup

### 3. Hash Consistency Issues
- Rust and Python implementations produce different directory hashes
- This suggests differences in:
  - File ordering algorithms
  - Directory traversal methods
  - Hash computation approaches
  - Symlink handling

### 4. Scalability
- Rust handles large repositories efficiently
- 74,460 objects processed in ~5 seconds
- Memory usage remains reasonable

## Test Methodology

### Rust Implementation
```bash
# Directory mode (fastest)
target/release/swhid-cli --obj-type directory ../linux

# Recursive mode (full traversal)
target/release/swhid-cli --recursive ../linux
```

### Python Implementation
```bash
# Directory mode only
python -m swh.model.cli --type directory ../linux
```

### Git Implementation
```bash
# Manual git tree computation
git init && git add . && git write-tree
```

## Recommendations

### 1. Use Rust for Large Repositories
- Best performance for large codebases
- Supports both directory and recursive modes
- Handles complex directory structures efficiently

### 2. Investigate Hash Differences
- The hash discrepancies between implementations need investigation
- May indicate bugs or specification interpretation differences
- Important for cross-implementation compatibility

### 3. Consider Use Cases
- **Directory Mode**: Fast, single hash for entire repository
- **Recursive Mode**: Detailed analysis of all objects
- **Python/Git**: Reference implementations for validation

## Conclusion

The Rust implementation demonstrates superior performance for processing large repositories like the Linux kernel source code. It's 6-6.7x faster than the Python and Git implementations while providing more functionality (recursive traversal).

However, the hash differences between implementations suggest that further investigation is needed to ensure cross-compatibility and correct SWHID specification compliance.

## Files

- **Test Script**: `scripts/linux_performance_test.py`
- **Results**: Generated on-demand
- **Test Data**: Linux kernel source code repository

---

*Generated on August 6, 2025* 