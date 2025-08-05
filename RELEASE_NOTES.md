# Release Notes

## v0.1.0 - Stable SWHID Implementation (2025-08-05)

This is the first stable release of the Rust SWHID implementation, featuring a complete, high-performance implementation of Software Heritage Identifiers.

### 🎯 Core Features

#### SWHID Object Types
- **Content SWHID**: Compute SWHIDs for individual files
- **Directory SWHID**: Compute SWHIDs for directory trees with recursive subdirectory support
- **Revision SWHID**: Git revision SWHID computation
- **Release SWHID**: Git release SWHID computation  
- **Snapshot SWHID**: Git snapshot SWHID computation

#### Technical Implementation
- **Git-compatible hashing**: Uses salted SHA1 identical to Git object hashes
- **Command-line interface**: Full CLI tool for SWHID computation
- **Rust library API**: Clean API for integration into other projects
- **Archive support**: Handle tar, tar.gz, tgz, tar.bz2, and zip files with `--archive` flag
- **Extended SWHID**: Support for extended object types (Origin, Raw Extrinsic Metadata)
- **Qualified SWHID**: Support for qualified SWHIDs with anchors, paths, and line ranges

### ⚡ Performance

#### Benchmark Results (swh-model directory: 20.6MB, 381 files)
| Implementation | Mean Time | Relative Speed | Notes |
|----------------|-----------|----------------|-------|
| **Rust (Binary)** | 0.020s | 1.0x | Pre-compiled binary |
| **Git Command** | 0.072s | 3.5x | Official Git tool |
| **Python (swh-model)** | 0.173s | 8.4x | Production implementation |
| **Rust (Subprocess)** | 0.226s | 11.0x | Subprocess overhead |
| **Git (dulwich)** | 1.437s | 70.2x | Pure Python library |

#### Key Performance Insights
- **8.4x faster than Python**: Significant speedup over reference implementation
- **3.5x faster than Git command**: Native performance advantage
- **Subprocess overhead**: 11x performance penalty when using subprocess calls
- **Real-world performance**: Tested on large directory structures

### 🧪 Testing & Quality

#### Comprehensive Test Suite
- **6+ complex directory structure tests**: Nested directories, mixed content, special characters
- **Technology-neutral testing harness**: Compare Rust, Python, and Git implementations
- **Hash consistency**: All implementations produce identical SWHID hashes for same content
- **Git compatibility**: Fixed directory entry sorting to match Git's `entry_sort_key` behavior
- **Recursive computation**: Proper subdirectory hash computation working correctly

#### Testing Infrastructure
- **Performance testing script**: `scripts/performance_test.py` for benchmarking
- **Automated testing**: `scripts/run_performance_test.sh` for convenience
- **Cross-implementation validation**: Ensures compatibility with Python swh-model

### 📚 Documentation

#### Complete Documentation
- **API documentation**: Comprehensive library API with examples
- **CLI usage**: Command-line interface documentation
- **Performance analysis**: Detailed performance comparison and insights
- **Extended SWHID**: Documentation for extended and qualified SWHIDs
- **Integration examples**: Real-world usage examples

### 🔧 Technical Details

#### Dependencies & Compatibility
- **Rust 2021 edition**: Modern Rust with latest features
- **MIT license**: Open source licensing
- **swh-model compatibility**: Compatible with Python reference implementation
- **Error handling**: Comprehensive error handling and edge case coverage
- **Archive extraction**: Safe temporary directory cleanup

#### Build & Installation
```bash
# Build from source
git clone <repository-url>
cd swhid-rs
cargo build --release

# Run performance tests
./scripts/run_performance_test.sh

# Use CLI
./target/release/swhid-cli /path/to/file
./target/release/swhid-cli /path/to/directory
./target/release/swhid-cli --archive /path/to/archive.tar.gz
```

### 🚀 What's New

This release represents a production-ready, high-performance SWHID implementation that:
- Maintains full compatibility with the Software Heritage ecosystem
- Provides significant performance improvements over existing implementations
- Includes comprehensive testing and validation infrastructure
- Offers both CLI and library interfaces for different use cases
- Supports all core SWHID object types and extended features

### 🔮 Future Roadmap

Potential future enhancements:
- Additional archive format support
- Parallel processing for large directories
- WebAssembly compilation for browser usage
- Integration with more Software Heritage tools
- Enhanced error reporting and diagnostics

---

**Release Date**: August 5, 2025  
**Version**: v0.1.0  
**License**: MIT  
**Compatibility**: Rust 1.70+, swh-model Python implementation 