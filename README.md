# SWHID Rust Library

A Rust implementation of Software Heritage Identifier (SWHID) computation, extracted from the Python `swh-model` package.

## Overview

SWHIDs are persistent identifiers for software artifacts that follow the format:
```
swh:1:<object_type>:<40_character_hex_hash>
```

Where:
- `swh` is the namespace (always "swh")
- `1` is the scheme version (always 1)
- `<object_type>` is one of: `cnt`, `dir`, `rev`, `rel`, `snp`
- `<40_character_hex_hash>` is the SHA1 hash of the object

## Features

- **Content SWHID**: Compute SWHIDs for individual files
- **Directory SWHID**: Compute SWHIDs for directory trees
- **Extended SWHID**: Support for extended object types (Origin, Raw Extrinsic Metadata)
- **Qualified SWHID**: Support for qualified SWHIDs with anchors, paths, and line ranges
- **Git-compatible**: Uses Git's object format for hashing
- **CLI tool**: Command-line interface for SWHID computation
- **Library API**: Rust library for integration into other projects

## Installation

### From Source

```bash
git clone <repository-url>
cd swhid-rs
cargo build --release
```

### Using Cargo

Add to your `Cargo.toml`:
```toml
[dependencies]
swhid = "0.1.0"
```

## Usage

### Command Line Interface

```bash
# Compute SWHID for a file
./target/release/swhid-cli /path/to/file.txt

# Compute SWHID for a directory
./target/release/swhid-cli /path/to/directory

# Compute SWHID from stdin
echo "Hello, World!" | ./target/release/swhid-cli -
```

### Library API

#### Basic SWHID Computation

```rust
use swhid::{SwhidComputer, Swhid};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let computer = SwhidComputer::new();
    
    // Compute SWHID for a file
    let file_swhid = computer.compute_file_swhid("/path/to/file.txt")?;
    println!("File SWHID: {}", file_swhid);
    
    // Compute SWHID for a directory
    let dir_swhid = computer.compute_directory_swhid("/path/to/directory")?;
    println!("Directory SWHID: {}", dir_swhid);
    
    // Auto-detect and compute SWHID
    let swhid = computer.compute_swhid("/path/to/object")?;
    println!("SWHID: {}", swhid);
    
    Ok(())
}
```

#### Extended SWHID Support

```rust
use swhid::{Swhid, ExtendedSwhid, ExtendedObjectType};

fn main() {
    let object_id = [0u8; 20];
    
    // Create Extended SWHID with Origin type
    let origin_swhid = ExtendedSwhid::new(ExtendedObjectType::Origin, object_id);
    println!("Origin SWHID: {}", origin_swhid);
    
    // Convert from Core SWHID
    let core_swhid = Swhid::new(ObjectType::Content, object_id);
    let extended_swhid = core_swhid.to_extended();
    
    // Parse from string
    let parsed = ExtendedSwhid::from_string("swh:1:ori:8ff44f081d43176474b267de5451f2c2e88089d0").unwrap();
}
```

#### Qualified SWHID Support

```rust
use swhid::{QualifiedSwhid, ObjectType};

fn main() {
    let object_id = [0u8; 20];
    
    // Create Qualified SWHID with qualifiers
    let qualified = QualifiedSwhid::new(ObjectType::Content, object_id)
        .with_origin("https://github.com/user/repo".to_string())
        .with_path(b"/src/main.rs".to_vec())
        .with_lines(10, Some(20));
    
    println!("Qualified SWHID: {}", qualified);
    
    // Parse from string
    let parsed = QualifiedSwhid::from_string(
        "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;origin=https://github.com/user/repo;path=/src/main.rs;lines=10-20"
    ).unwrap();
    
    // Access qualifiers
    println!("Origin: {:?}", parsed.origin());
    println!("Path: {:?}", parsed.path().map(|p| String::from_utf8_lossy(p)));
    println!("Lines: {:?}", parsed.lines());
}
```

## API Reference

### SwhidComputer

The main entry point for SWHID computation.

```rust
pub struct SwhidComputer {
    exclude_patterns: Vec<String>,
    follow_symlinks: bool,
    max_content_length: Option<usize>,
}
```

#### Methods

- `new()` - Create a new SWHID computer with default settings
- `with_exclude_patterns(patterns)` - Set patterns to exclude from directory processing
- `with_follow_symlinks(follow)` - Configure symlink following behavior
- `with_max_content_length(length)` - Set maximum content size limit
- `compute_file_swhid(path)` - Compute SWHID for a file
- `compute_directory_swhid(path)` - Compute SWHID for a directory
- `compute_swhid(path)` - Auto-detect object type and compute SWHID
- `verify_swhid(expected, path)` - Verify a SWHID against a path

### Extended SWHID Types

#### ExtendedObjectType

Extended object types beyond the core SWHID specification:

- `Content` - File content
- `Directory` - Directory tree
- `Revision` - Git revision
- `Release` - Git release
- `Snapshot` - Git snapshot
- `Origin` - Software origin (extended)
- `RawExtrinsicMetadata` - Raw extrinsic metadata (extended)

#### ExtendedSwhid

Extended SWHID structure supporting extended object types:

```rust
pub struct ExtendedSwhid {
    namespace: String,
    scheme_version: u32,
    object_type: ExtendedObjectType,
    object_id: [u8; 20],
}
```

### Qualified SWHID Types

#### QualifiedSwhid

Qualified SWHID structure with qualifier support:

```rust
pub struct QualifiedSwhid {
    namespace: String,
    scheme_version: u32,
    object_type: ObjectType,
    object_id: [u8; 20],
    origin: Option<String>,
    visit: Option<Swhid>,
    anchor: Option<Swhid>,
    path: Option<Vec<u8>>,
    lines: Option<(u32, Option<u32>)>,
}
```

#### Supported Qualifiers

- `origin` - Software origin URI
- `visit` - Snapshot visit SWHID
- `anchor` - Anchor SWHID (directory, revision, release, or snapshot)
- `path` - File path relative to anchor
- `lines` - Line range (start-end or single line)

## Examples

See the `examples/` directory for complete working examples:

- `extended_swhid_example.rs` - Extended and Qualified SWHID usage

## Security

### SHA1DC Compliance

This implementation uses **SHA1DC (SHA-1 with detection of collision)** as required by the SWHID specification to prevent SHATTERED-style attacks. This is a **mandatory security requirement** that ensures:

- **Collision Detection**: Automatically detects known collision patterns
- **Attack Prevention**: Prevents malicious actors from fabricating SWHID objects
- **Specification Compliance**: Meets SWHID security requirements (Section 5.8)
- **Git Compatibility**: Matches Git's SHA1DC usage since 2017

The implementation uses the `sha1-checked` crate which provides SHA-1 with built-in collision detection, ensuring that SWHID identifiers remain unique and secure even in the presence of SHA-1 collision attacks.

## Performance

The Rust implementation provides excellent performance compared to other SWHID implementations. Performance benchmarks were conducted on the `swh-model` directory (20.6 MB, 381 files) using multiple iterations to ensure accuracy.

### Performance Comparison

| Implementation | Mean Time | Relative Speed | Notes |
|----------------|-----------|----------------|-------|
| **Rust (Binary)** | 0.020s | 1.0x | Pre-compiled binary |
| **Git Command** | 0.072s | 3.5x | Official Git tool |
| **Python (swh-model)** | 0.173s | 8.4x | Production implementation |
| **Rust (Subprocess)** | 0.226s | 11.0x | Subprocess overhead |
| **Git (dulwich)** | 1.437s | 70.2x | Pure Python library |

### Key Performance Insights

- **Rust Binary**: Fastest implementation at 0.020s average
- **3.5x faster than Git command**: Native performance advantage
- **8.4x faster than Python**: Significant speedup over reference implementation
- **Subprocess overhead**: 11x performance penalty when using subprocess calls

### Running Performance Tests

To run performance comparisons:

```bash
# Build the Rust implementation
cargo build --release

# Run performance test (uses swh-model directory by default)
python scripts/performance_test.py

# Test on a different directory
python scripts/performance_test.py /path/to/test/directory

# Or use the automated script (builds and runs test)
./scripts/run_performance_test.sh
```

Requirements for performance testing:
- Rust implementation built: `cargo build --release`
- Python swh-model installed: `pip install swh-model`
- Git tools available: `git`, `dulwich`, `pygit2`

## Testing

Run the test suite:

```bash
cargo test
```

The test suite includes comprehensive coverage for:

- Core SWHID functionality
- Extended SWHID parsing and formatting
- Qualified SWHID qualifier handling
- Error conditions and edge cases
- Compatibility with Python reference implementation 