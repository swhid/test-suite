# TODO - Future Improvements

## Performance Optimizations

### 1. Recursive Hash Computation
- **Current**: Recursive traversal computes hashes in multiple passes (build tree → compute hashes → collect objects)
- **Goal**: Optimize to compute hashes in a single pass if possible
- **Benefit**: Reduce memory usage and improve performance for large directory trees
- **Approach**: Investigate if we can compute directory hashes while traversing, avoiding the need for a separate bottom-up pass

### 2. Archive Processing Without Decompression
- **Current**: Archives (tar, zip, etc.) are extracted to temporary directory before computing directory SWHID
- **Goal**: Compute directory SWHID directly from archive contents without decompressing to disk
- **Benefit**: Reduce disk I/O, avoid temporary file creation, improve performance
- **Approach**: 
  - For tar files: Stream and parse tar headers to build directory structure in memory
  - For zip files: Use zip::ZipArchive to iterate over entries without extracting
  - Compute hashes of file contents directly from archive streams
  - Build directory tree in memory and compute SWHID

## Implementation Notes
- Both optimizations require careful testing to ensure SWHID compatibility with Python reference
- Archive processing without decompression may need to handle large files and memory constraints
- Single-pass hash computation needs to maintain the same hash ordering as the current multi-pass approach 