#!/usr/bin/env python3
"""
SWHID Performance Comparison Script

This script compares the performance of different SWHID implementations
on a large directory structure to measure relative performance.

Usage:
    python scripts/performance_test.py [test_directory]

Requirements:
    - Rust implementation built: cargo build --release
    - Python swh-model installed: pip install swh-model
    - Git tools available: git, dulwich, pygit2
"""

import os
import sys
import time
import statistics
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Add test_harness to path for runners
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
test_harness_path = os.path.join(project_root, "test_harness")
sys.path.insert(0, test_harness_path)

# Import runners
try:
    from runners.rust_bin_runner import compute_swhid_simple as rust_compute
    from runners.python_runner import compute_swhid_simple as python_compute
    from runners.git_runner import compute_swhid_simple as git_compute
    from runners.git_cmd_runner import compute_swhid_simple as git_cmd_compute
    from runners.pygit2_runner import compute_swhid_simple as pygit2_compute
except ImportError as e:
    print(f"Error importing runners: {e}")
    print("Make sure you're running from the project root and test_harness is available")
    sys.exit(1)


def get_directory_info(test_dir: str) -> Tuple[str, int]:
    """Get directory size and file count."""
    total_size = 0
    file_count = 0
    
    for root, dirs, files in os.walk(test_dir):
        for file in files:
            file_path = os.path.join(root, file)
            if os.path.isfile(file_path):
                total_size += os.path.getsize(file_path)
                file_count += 1
    
    # Convert to MB
    size_mb = total_size / (1024 * 1024)
    return f"{size_mb:.1f} MB", file_count


def test_implementation(name: str, compute_func, test_dir: str, 
                       iterations: int = 5) -> Optional[Dict]:
    """Test a single implementation and return performance data."""
    print(f"Testing {name}...")
    
    times = []
    swhid_result = None
    
    for i in range(iterations):
        try:
            start_time = time.time()
            result = compute_func(test_dir, "directory")
            end_time = time.time()
            
            duration = end_time - start_time
            times.append(duration)
            swhid_result = result
            
            print(f"  Iteration {i+1}: {duration:.3f}s -> {result}")
            
        except Exception as e:
            print(f"  Iteration {i+1}: ERROR - {e}")
            return None
    
    if not times:
        return None
    
    return {
        'name': name,
        'times': times,
        'mean': statistics.mean(times),
        'median': statistics.median(times),
        'min': min(times),
        'max': max(times),
        'std': statistics.stdev(times) if len(times) > 1 else 0,
        'swhid': swhid_result
    }


def format_results(results: List[Dict]) -> str:
    """Format results into a readable string."""
    if not results:
        return "No successful results"
    
    # Sort by mean time (fastest first)
    results.sort(key=lambda x: x['mean'])
    
    output = []
    output.append("=" * 80)
    output.append("PERFORMANCE COMPARISON RESULTS")
    output.append("=" * 80)
    output.append("")
    
    # Successful implementations
    successful = [r for r in results if r is not None]
    failed = [r for r in results if r is None]
    
    if successful:
        output.append(f"Successful implementations ({len(successful)}):")
        output.append("-" * 80)
        
        for i, result in enumerate(successful, 1):
            output.append(f" {i}. {result['name']:<15} "
                         f"Mean: {result['mean']:6.3f}s "
                         f"Median: {result['median']:6.3f}s "
                         f"Min: {result['min']:6.3f}s "
                         f"Max: {result['max']:6.3f}s "
                         f"Std: {result['std']:6.3f}s")
            output.append(f"    SWHID: {result['swhid']}")
            output.append("")
    
    if failed:
        output.append(f"Failed implementations ({len(failed)}):")
        output.append("-" * 80)
        for result in failed:
            output.append(f"❌ {result['name']}: {result.get('error', 'Unknown error')}")
        output.append("")
    
    # Summary
    if successful:
        fastest = successful[0]
        slowest = successful[-1]
        speedup = slowest['mean'] / fastest['mean']
        
        output.append("SUMMARY:")
        output.append("-" * 80)
        output.append(f"Fastest:  {fastest['name']} ({fastest['mean']:.3f}s)")
        output.append(f"Slowest:  {slowest['name']} ({slowest['mean']:.3f}s)")
        output.append(f"Speedup:  {speedup:.1f}x")
        output.append("")
        
        output.append("Relative Performance (normalized to fastest):")
        for result in successful:
            relative = result['mean'] / fastest['mean']
            output.append(f" {result['name']:<15} {relative:5.1f}x")
    
    return "\n".join(output)


def main():
    """Main function."""
    # Default test directory
    default_test_dir = os.path.join(project_root, "swh-model")
    
    if len(sys.argv) > 1:
        test_dir = sys.argv[1]
    else:
        test_dir = default_test_dir
    
    if not os.path.exists(test_dir):
        print(f"Error: Test directory not found: {test_dir}")
        print(f"Usage: python scripts/performance_test.py [test_directory]")
        print(f"Default: {default_test_dir}")
        sys.exit(1)
    
    # Get directory info
    size_str, file_count = get_directory_info(test_dir)
    print(f"Testing performance on: {test_dir}")
    print(f"Directory size: {size_str}")
    print(f"File count: {file_count}")
    print()
    
    # Define implementations to test
    implementations = [
        ("rust", rust_compute),
        ("rust-lib", rust_compute),  # Same as rust but different name for clarity
        ("python", python_compute),
        ("git", git_compute),
        ("git-cmd", git_cmd_compute),
        ("pygit2", pygit2_compute),
    ]
    
    # Test each implementation
    results = []
    for name, compute_func in implementations:
        result = test_implementation(name, compute_func, test_dir)
        results.append(result)
        print()
    
    # Print results
    print(format_results(results))


if __name__ == "__main__":
    main() 