#!/usr/bin/env python3
"""
SWHID Testing Harness

A technology-neutral testing harness for comparing different SWHID implementations
on standardized test payloads.
"""

import argparse
import json
import os
import sys
import time
import yaml
import subprocess
import tempfile
import shutil
import importlib.util
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class TestResult:
    """Represents the result of a single test."""
    payload_name: str
    payload_path: str
    implementation: str
    swhid: Optional[str]
    error: Optional[str]
    duration: float
    success: bool

@dataclass
class ComparisonResult:
    """Represents the comparison of results across implementations."""
    payload_name: str
    payload_path: str
    results: Dict[str, TestResult]
    all_match: bool
    expected_swhid: Optional[str]

class SwhidHarness:
    """Main testing harness for SWHID implementations."""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config()
        self.results_dir = Path(self.config["output"]["results_dir"])
        self.results_dir.mkdir(exist_ok=True)
        
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def _get_runner(self, implementation: str) -> str:
        """Get the runner script for an implementation."""
        impl_config = self.config["implementations"][implementation]
        return impl_config["runner"]
    
    def _run_single_test(self, implementation: str, payload_path: str, 
                         payload_name: str) -> TestResult:
        """Run a single test for one implementation."""
        start_time = time.time()
        
        try:
            # Import the runner module
            runner_path = self._get_runner(implementation)
            spec = importlib.util.spec_from_file_location("runner", runner_path)
            runner_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(runner_module)
            
            # Run the test
            swhid = runner_module.compute_swhid(payload_path)
            duration = time.time() - start_time
            
            return TestResult(
                payload_name=payload_name,
                payload_path=payload_path,
                implementation=implementation,
                swhid=swhid,
                error=None,
                duration=duration,
                success=True
            )
            
        except Exception as e:
            duration = time.time() - start_time
            return TestResult(
                payload_name=payload_name,
                payload_path=payload_path,
                implementation=implementation,
                swhid=None,
                error=str(e),
                duration=duration,
                success=False
            )
    
    def _compare_results(self, payload_name: str, payload_path: str,
                        results: Dict[str, TestResult], 
                        expected_swhid: Optional[str] = None) -> ComparisonResult:
        """Compare results across implementations."""
        # Check if all implementations succeeded
        all_success = all(r.success for r in results.values())
        
        if not all_success:
            return ComparisonResult(
                payload_name=payload_name,
                payload_path=payload_path,
                results=results,
                all_match=False,
                expected_swhid=expected_swhid
            )
        
        # Get all SWHIDs
        swhids = [r.swhid for r in results.values() if r.swhid]
        
        # Check if all SWHIDs match
        all_match = len(set(swhids)) == 1 if swhids else False
        
        # Check against expected SWHID if provided
        if expected_swhid and all_match:
            all_match = swhids[0] == expected_swhid
        
        return ComparisonResult(
            payload_name=payload_name,
            payload_path=payload_path,
            results=results,
            all_match=all_match,
            expected_swhid=expected_swhid
        )
    
    def run_tests(self, implementations: Optional[List[str]] = None,
                  categories: Optional[List[str]] = None) -> List[ComparisonResult]:
        """Run tests for specified implementations and categories."""
        if implementations is None:
            implementations = [k for k, v in self.config["implementations"].items() 
                            if v.get("enabled", True)]
        
        if categories is None:
            categories = list(self.config["payloads"].keys())
        
        all_results = []
        
        for category in categories:
            if category not in self.config["payloads"]:
                logger.warning(f"Category '{category}' not found in config")
                continue
                
            logger.info(f"Testing category: {category}")
            
            for payload in self.config["payloads"][category]:
                payload_path = payload["path"]
                payload_name = payload["name"]
                expected_swhid = payload.get("expected_swhid")
                
                # Check if payload exists
                if not os.path.exists(payload_path):
                    logger.warning(f"Payload not found: {payload_path}")
                    continue
                
                logger.info(f"Testing payload: {payload_name}")
                
                # Run tests for all implementations
                results = {}
                with ThreadPoolExecutor(max_workers=self.config["settings"]["parallel_tests"]) as executor:
                    future_to_impl = {
                        executor.submit(self._run_single_test, impl, payload_path, payload_name): impl
                        for impl in implementations
                    }
                    
                    for future in as_completed(future_to_impl):
                        impl = future_to_impl[future]
                        try:
                            result = future.result()
                            results[impl] = result
                        except Exception as e:
                            logger.error(f"Error running test for {impl}: {e}")
                
                # Compare results
                comparison = self._compare_results(payload_name, payload_path, results, expected_swhid)
                all_results.append(comparison)
                
                # Log results
                if comparison.all_match:
                    logger.info(f"✓ {payload_name}: All implementations match")
                else:
                    logger.error(f"✗ {payload_name}: Implementations differ")
                    for impl, result in results.items():
                        if result.success:
                            logger.info(f"  {impl}: {result.swhid}")
                        else:
                            logger.error(f"  {impl}: Error - {result.error}")
        
        return all_results
    
    def generate_expected_results(self, implementation: str = "python"):
        """Generate expected results using a reference implementation."""
        logger.info(f"Generating expected results using {implementation}")
        
        for category, payloads in self.config["payloads"].items():
            for payload in payloads:
                payload_path = payload["path"]
                payload_name = payload["name"]
                
                if not os.path.exists(payload_path):
                    continue
                
                try:
                    # Run the reference implementation
                    runner_path = self._get_runner(implementation)
                    spec = importlib.util.spec_from_file_location("runner", runner_path)
                    runner_module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(runner_module)
                    
                    swhid = runner_module.compute_swhid(payload_path)
                    
                    # Update the config with expected SWHID
                    payload["expected_swhid"] = swhid
                    logger.info(f"Generated expected SWHID for {payload_name}: {swhid}")
                    
                except Exception as e:
                    logger.error(f"Error generating expected result for {payload_name}: {e}")
        
        # Save updated config
        with open(self.config_path, 'w') as f:
            yaml.dump(self.config, f, default_flow_style=False)
    
    def save_results(self, results: List[ComparisonResult], output_format: str = "json"):
        """Save test results to file."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        
        if output_format == "json":
            output_file = self.results_dir / f"results_{timestamp}.json"
            
            # Convert results to JSON-serializable format
            json_results = []
            for comparison in results:
                json_comparison = {
                    "payload_name": comparison.payload_name,
                    "payload_path": comparison.payload_path,
                    "all_match": comparison.all_match,
                    "expected_swhid": comparison.expected_swhid,
                    "results": {}
                }
                
                for impl, result in comparison.results.items():
                    json_comparison["results"][impl] = {
                        "swhid": result.swhid,
                        "error": result.error,
                        "duration": result.duration,
                        "success": result.success
                    }
                
                json_results.append(json_comparison)
            
            with open(output_file, 'w') as f:
                json.dump(json_results, f, indent=2)
            
            logger.info(f"Results saved to {output_file}")
        
        elif output_format == "text":
            output_file = self.results_dir / f"results_{timestamp}.txt"
            
            with open(output_file, 'w') as f:
                f.write("SWHID Testing Harness Results\n")
                f.write("=" * 40 + "\n\n")
                
                for comparison in results:
                    f.write(f"Payload: {comparison.payload_name}\n")
                    f.write(f"Path: {comparison.payload_path}\n")
                    f.write(f"All Match: {comparison.all_match}\n")
                    
                    if comparison.expected_swhid:
                        f.write(f"Expected: {comparison.expected_swhid}\n")
                    
                    f.write("Results:\n")
                    for impl, result in comparison.results.items():
                        f.write(f"  {impl}: ")
                        if result.success:
                            f.write(f"{result.swhid} ({result.duration:.3f}s)\n")
                        else:
                            f.write(f"ERROR - {result.error}\n")
                    
                    f.write("\n")
            
            logger.info(f"Results saved to {output_file}")
    
    def print_summary(self, results: List[ComparisonResult]):
        """Print a summary of test results."""
        total_tests = len(results)
        successful_tests = sum(1 for r in results if r.all_match)
        failed_tests = total_tests - successful_tests
        
        print("\n" + "=" * 50)
        print("SWHID Testing Harness Summary")
        print("=" * 50)
        print(f"Total Tests: {total_tests}")
        print(f"Successful: {successful_tests}")
        print(f"Failed: {failed_tests}")
        print(f"Success Rate: {successful_tests/total_tests*100:.1f}%")
        
        if failed_tests > 0:
            print("\nFailed Tests:")
            for result in results:
                if not result.all_match:
                    print(f"  - {result.payload_name}")
        
        print("=" * 50)

def main():
    parser = argparse.ArgumentParser(description="SWHID Testing Harness")
    parser.add_argument("--impl", nargs="+", help="Specific implementations to test")
    parser.add_argument("--category", nargs="+", help="Specific categories to test")
    parser.add_argument("--config", default="config.yaml", help="Configuration file")
    parser.add_argument("--generate-expected", action="store_true", 
                       help="Generate expected results using reference implementation")
    parser.add_argument("--output-format", choices=["json", "text"], default="json",
                       help="Output format for results")
    parser.add_argument("--reference-impl", default="python",
                       help="Reference implementation for generating expected results")
    
    args = parser.parse_args()
    
    harness = SwhidHarness(args.config)
    
    if args.generate_expected:
        harness.generate_expected_results(args.reference_impl)
    else:
        results = harness.run_tests(args.impl, args.category)
        harness.save_results(results, args.output_format)
        harness.print_summary(results)

if __name__ == "__main__":
    main() 