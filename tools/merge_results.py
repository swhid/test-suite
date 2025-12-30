#!/usr/bin/env python3
"""
Merge canonical results into dashboard layout.

This script takes canonical results files and creates the proper dashboard structure:
- site/data/runs/<run-id>.json (full canonical file)
- site/data/index.json (roll-up with metadata)
- site/data/latest.json (compatibility)
"""

import json
import argparse
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

def load_canonical_results(file_path: str) -> Dict[str, Any]:
    """Load a canonical results file."""
    with open(file_path, 'r') as f:
        return json.load(f)

def normalize_platform_name(os_string: str) -> str:
    """Normalize OS string to a friendly platform name."""
    os_lower = os_string.lower()
    if "ubuntu" in os_lower or "linux" in os_lower:
        return "Ubuntu"
    elif "macos" in os_lower or "darwin" in os_lower:
        return "macOS"
    elif "windows" in os_lower:
        return "Windows"
    else:
        return os_string.split("-")[0] if "-" in os_string else os_string

def create_index_data(results_files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create index.json data from multiple results files."""
    runs = []
    total_tests = 0
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    implementations = set()
    
    for results in results_files:
        # Extract platform info
        runner_info = results.get("run", {}).get("runner", {})
        platform_name = normalize_platform_name(runner_info.get("os", "Unknown"))
        
        run_data = {
            "id": results["run"]["id"],
            "created_at": results["run"]["created_at"],
            "branch": results["run"]["branch"],
            "commit": results["run"]["commit"],
            "platform": platform_name,
            "pass_rate": 0.0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0
        }
        
        # Calculate pass/fail/skip counts
        test_count = len(results["tests"])
        passed_count = 0
        failed_count = 0
        skipped_count = 0
        
        for test in results["tests"]:
            for result in test["results"]:
                if result["status"] == "PASS":
                    passed_count += 1
                elif result["status"] == "FAIL":
                    failed_count += 1
                elif result["status"] == "SKIPPED":
                    skipped_count += 1
        
        total_result_count = test_count * len(results["implementations"])
        
        if total_result_count > 0:
            run_data["pass_rate"] = round(passed_count / total_result_count * 100, 2)
            run_data["failed_rate"] = round(failed_count / total_result_count * 100, 2)
            run_data["skipped_rate"] = round(skipped_count / total_result_count * 100, 2)
        
        run_data["passed"] = passed_count
        run_data["failed"] = failed_count
        run_data["skipped"] = skipped_count
        run_data["total"] = total_result_count
        
        runs.append(run_data)
        total_tests += test_count
        total_passed += passed_count
        total_failed += failed_count
        total_skipped += skipped_count
        
        # Collect implementations
        for impl in results["implementations"]:
            implementations.add(impl["id"])
    
    # Sort runs by created_at (newest first)
    runs.sort(key=lambda x: x["created_at"], reverse=True)
    
    # Group runs by platform for aggregation
    platform_stats = {}
    for run in runs:
        platform = run["platform"]
        if platform not in platform_stats:
            platform_stats[platform] = {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0
            }
        platform_stats[platform]["total"] += run["total"]
        platform_stats[platform]["passed"] += run["passed"]
        platform_stats[platform]["failed"] += run["failed"]
        platform_stats[platform]["skipped"] += run["skipped"]
    
    # Calculate per-platform rates
    for platform, stats in platform_stats.items():
        if stats["total"] > 0:
            stats["pass_rate"] = round(stats["passed"] / stats["total"] * 100, 2)
            stats["fail_rate"] = round(stats["failed"] / stats["total"] * 100, 2)
            stats["skip_rate"] = round(stats["skipped"] / stats["total"] * 100, 2)
        else:
            stats["pass_rate"] = 0.0
            stats["fail_rate"] = 0.0
            stats["skip_rate"] = 0.0
    
    # Build implementation x platform matrix
    # Matrix structure: {implementation_id: {platform: {passed, failed, skipped, total, pass_rate, fail_rate, skip_rate}}}
    impl_platform_matrix = {}
    for results in results_files:
        runner_info = results.get("run", {}).get("runner", {})
        platform_name = normalize_platform_name(runner_info.get("os", "Unknown"))
        
        # Count results per implementation for this platform
        for impl in results["implementations"]:
            impl_id = impl["id"]
            if impl_id not in impl_platform_matrix:
                impl_platform_matrix[impl_id] = {}
            
            if platform_name not in impl_platform_matrix[impl_id]:
                impl_platform_matrix[impl_id][platform_name] = {
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "total": 0
                }
            
            # Count results for this implementation
            for test in results["tests"]:
                for result in test["results"]:
                    if result["implementation"] == impl_id:
                        impl_platform_matrix[impl_id][platform_name]["total"] += 1
                        if result["status"] == "PASS":
                            impl_platform_matrix[impl_id][platform_name]["passed"] += 1
                        elif result["status"] == "FAIL":
                            impl_platform_matrix[impl_id][platform_name]["failed"] += 1
                        elif result["status"] == "SKIPPED":
                            impl_platform_matrix[impl_id][platform_name]["skipped"] += 1
    
    # Calculate rates for each cell in the matrix
    for impl_id, platforms in impl_platform_matrix.items():
        for platform, stats in platforms.items():
            if stats["total"] > 0:
                stats["pass_rate"] = round(stats["passed"] / stats["total"] * 100, 2)
                stats["fail_rate"] = round(stats["failed"] / stats["total"] * 100, 2)
                stats["skip_rate"] = round(stats["skipped"] / stats["total"] * 100, 2)
            else:
                stats["pass_rate"] = 0.0
                stats["fail_rate"] = 0.0
                stats["skip_rate"] = 0.0
    
    total_results = total_tests * len(implementations) if implementations else 0
    overall_fail_rate = round(total_failed / total_results * 100, 2) if total_results > 0 else 0
    overall_skip_rate = round(total_skipped / total_results * 100, 2) if total_results > 0 else 0
    
    return {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_runs": len(runs),
        "total_tests": total_tests,
        "total_results": total_results,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total_skipped": total_skipped,
        "overall_pass_rate": round(total_passed / total_results * 100, 2) if total_results > 0 else 0,
        "overall_fail_rate": overall_fail_rate,
        "overall_skip_rate": overall_skip_rate,
        "implementations": sorted(list(implementations)),
        "platform_stats": platform_stats,
        "impl_platform_matrix": impl_platform_matrix,
        "runs": runs
    }

def main():
    parser = argparse.ArgumentParser(description="Merge canonical results into dashboard layout")
    parser.add_argument("results_files", nargs="+", help="Canonical results JSON files")
    parser.add_argument("--site", default="site", help="Site directory")
    
    args = parser.parse_args()
    
    # Load all results files
    results_files = []
    for file_path in args.results_files:
        if os.path.exists(file_path):
            results_files.append(load_canonical_results(file_path))
        else:
            print(f"Warning: File not found: {file_path}")
    
    if not results_files:
        print("Error: No valid results files found")
        return 1
    
    # Create site directory structure
    site_dir = Path(args.site)
    data_dir = site_dir / "data"
    runs_dir = data_dir / "runs"
    
    data_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)
    
    # Write individual run files
    for results in results_files:
        run_id = results["run"]["id"]
        run_file = runs_dir / f"{run_id}.json"
        with open(run_file, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Wrote {run_file}")
    
    # Create and write index.json
    index_data = create_index_data(results_files)
    index_file = data_dir / "index.json"
    with open(index_file, 'w') as f:
        json.dump(index_data, f, indent=2)
    print(f"Wrote {index_file}")
    
    # Write latest.json (compatibility)
    if results_files:
        latest_file = data_dir / "latest.json"
        with open(latest_file, 'w') as f:
            json.dump(results_files[0], f, indent=2)
        print(f"Wrote {latest_file}")
    
    print(f"Successfully merged {len(results_files)} results files")
    return 0

if __name__ == "__main__":
    exit(main())
