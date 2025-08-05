#!/bin/bash
# Run SWHID Performance Test
# This script runs the performance comparison and saves results

set -e

echo "Building Rust implementation..."
cargo build --release

echo "Running performance test on swh-model directory..."
python scripts/performance_test.py > performance_results.txt 2>&1

echo "Performance test completed. Results saved to performance_results.txt"
echo ""
echo "Summary:"
tail -20 performance_results.txt 