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
import tarfile
import shutil
import platform
import atexit
from pathlib import Path
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import logging

from .plugins import SwhidImplementation, ImplementationInfo, SwhidTestResult, ComparisonResult, ImplementationDiscovery, ErrorCode, TestMetrics
from .models import (
    HarnessResults, RunInfo, RunnerInfo, Implementation, TestCase, 
    ExpectedRef, Result, Metrics, ErrorInfo, Aggregates, make_run_id, get_runner_info, format_rfc3339,
    ImplementationCapabilitiesModel, DiffEntry
)
from .config import HarnessConfig
from .exceptions import (
    SwhidHarnessError, ConfigurationError, ImplementationError,
    TestExecutionError, ResultError, TimeoutError, ResourceLimitError, IOError as HarnessIOError
)
from .resource_manager import ResourceManager
from .git_manager import GitManager
from .comparator import ResultComparator
from .output import OutputGenerator
from .runner import TestRunner

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SwhidHarness:
    """Main testing harness for SWHID implementations."""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        try:
            self.config = HarnessConfig.load_from_file(config_path)
        except FileNotFoundError as e:
            raise ConfigurationError(
                f"Configuration file not found: {config_path}",
                config_path=config_path,
                subtype="file_not_found"
            ) from e
        except ValueError as e:
            raise ConfigurationError(
                f"Invalid configuration: {e}",
                config_path=config_path
            ) from e
        
        self.results_dir = Path(self.config.output.results_dir)
        self.results_dir.mkdir(exist_ok=True)
        
        # Initialize implementation discovery
        self.discovery = ImplementationDiscovery()
        self.implementations = {}
        
        # Initialize resource manager
        self.resource_manager = ResourceManager()
        atexit.register(self.resource_manager.cleanup_temp_dirs)
        
        # Initialize Git manager
        self.git_manager = GitManager()
        
        # Initialize comparator
        self.comparator = ResultComparator()
        
        # Initialize output generator (will be set when implementations are loaded)
        self.output_generator = None
        
        # Initialize test runner (will be set when implementations are loaded)
        self.test_runner = None
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file (deprecated - use self.config directly)."""
        # Return dict representation for backward compatibility
        return self.config.model_dump(mode='python')
    
    def _load_implementations(self, impl_names: Optional[List[str]] = None) -> Dict[str, SwhidImplementation]:
        """Load implementations using the discovery system."""
        all_implementations = self.discovery.discover_implementations()
        
        if impl_names is None:
            # Use all available implementations
            return all_implementations
        
        # Filter to requested implementations
        filtered = {}
        for name in impl_names:
            if name in all_implementations:
                filtered[name] = all_implementations[name]
            else:
                logger.warning(f"Implementation '{name}' not found")
        
        return filtered
    
    def _cleanup_temp_dirs(self):
        """Clean up temporary directories created from tarballs (delegates to ResourceManager)."""
        self.resource_manager.cleanup_temp_dirs()
    
    def _obj_type_to_swhid_code(self, obj_type: str) -> str:
        """Map object type to SWHID type code."""
        from .utils.constants import obj_type_to_swhid_code
        return obj_type_to_swhid_code(obj_type)
    
    def _extract_tarball_if_needed(self, payload_path: str) -> str:
        """Extract tarball to temporary directory if payload is a .tar.gz file (delegates to ResourceManager)."""
        config_dir = os.path.dirname(os.path.abspath(self.config_path))
        return self.resource_manager.extract_tarball_if_needed(payload_path, config_dir)
    
    def _resolve_commit_reference(self, repo_path: str, commit: Optional[str] = None) -> Optional[str]:
        """Resolve a commit reference (branch name, tag, short SHA) to a full SHA (delegates to GitManager)."""
        return self.git_manager.resolve_commit(repo_path, commit)
    
    def _run_single_test(self, implementation: SwhidImplementation, payload_path: str, 
                         payload_name: str, category: Optional[str] = None, 
                         commit: Optional[str] = None, tag: Optional[str] = None,
                         version: Optional[int] = None, hash_algo: Optional[str] = None) -> SwhidTestResult:
        """Run a single test (delegates to TestRunner)."""
        if self.test_runner is None:
            # Initialize test runner if not already done
            self.test_runner = TestRunner(
                self.config, self.config_path, self.implementations,
                self.resource_manager, self.git_manager
            )
        return self.test_runner.run_single_test(
            implementation, payload_path, payload_name, category,
            commit, tag, version, hash_algo
        )
    
    def _discover_git_tests(self, repo_path: str, base_name: str, 
                            discover_branches: bool, discover_tags: bool,
                            expected_config: Optional[Dict[str, Any]] = None) -> List[ComparisonResult]:
        """Discover and test all branches and/or annotated tags in a Git repository."""
        all_results = []
        expected_config = expected_config or {}
        expected_branches = expected_config.get("branches", {}) or {}
        expected_tags = expected_config.get("tags", {}) or {}
        
        # Extract tarball if needed
        config_dir = os.path.dirname(os.path.abspath(self.config_path))
        actual_repo_path = self.resource_manager.extract_tarball_if_needed(repo_path, config_dir)
        
        if not os.path.exists(actual_repo_path):
            logger.warning(f"Repository not found: {actual_repo_path}")
            return all_results
        
                # Discover branches
        if discover_branches:
            try:
                branches = self.git_manager.get_branches(actual_repo_path)
                logger.info(f"Discovered {len(branches)} branches in {base_name}: {', '.join(branches)}")
                
                # Test each branch as a revision
                for branch in branches:
                    test_name = f"{base_name}_branch_{branch.replace('/', '_')}"
                    logger.info(f"Testing branch '{branch}' as revision: {test_name}")
                    
                    results = {}
                    with ThreadPoolExecutor(max_workers=self.config.settings.parallel_tests) as executor:
                        future_to_impl = {
                            executor.submit(self._run_single_test, impl, actual_repo_path, test_name, 
                                          category="revision", commit=branch): impl
                            for impl in self.implementations.values()
                        }
                        for future in as_completed(future_to_impl):
                            impl = future_to_impl[future]
                            try:
                                result = future.result()
                                results[impl.get_info().name] = result
                            except Exception as e:
                                logger.error(f"Error running test for {impl.get_info().name}: {e}")
                    
                    # Compare results (no expected SWHID for discovered tests)
                    expected_swhid = expected_branches.get(branch)
                    comparison = self._compare_results(test_name, actual_repo_path, results, expected_swhid=expected_swhid, expected_swhid_sha256=None)
                    all_results.append(comparison)
                    
                    # Log results similar to regular tests
                    skipped_impls = [impl_name for impl_name, result in results.items() 
                                       if not result.success and any(phrase in str(result.error).lower() 
                                           for phrase in ["not supported", "doesn't support", "does not support", "unsupported"])]
                    
                    if comparison.all_match:
                        # Get the SWHID from any successful result
                        swhid = next((r.swhid for r in results.values() if r.success), None)
                        if swhid:
                            logger.info(f"[PASS] {test_name}: All implementations match - {swhid}")
                        else:
                            logger.info(f"[PASS] {test_name}: All implementations match")
                    else:
                        # Check if all implementations skipped
                        if skipped_impls and len(skipped_impls) == len(results):
                            logger.info(f"[SKIP] {test_name}: All implementations skipped (unsupported type)")
                        else:
                            logger.error(f"[FAIL] {test_name}: Implementations differ")
                            
                            # Show skipped implementations
                            if skipped_impls:
                                logger.info(f"  Skipped by: {', '.join(skipped_impls)}")
                            
                            # Group results by SWHID to show which implementations match
                            swhid_groups = {}
                            failed_implementations = []
                            
                            for impl_name, result in results.items():
                                if result.success:
                                    swhid = result.swhid
                                    if swhid not in swhid_groups:
                                        swhid_groups[swhid] = []
                                    swhid_groups[swhid].append(impl_name)
                                elif impl_name not in skipped_impls:
                                    failed_implementations.append((impl_name, result.error))
                            
                            # Show SWHID groups
                            if len(swhid_groups) > 1:
                                logger.error(f"  Found {len(swhid_groups)} different SWHID groups:")
                                for i, (swhid, impls) in enumerate(swhid_groups.items(), 1):
                                    logger.error(f"    Group {i}: {swhid}")
                                    logger.error(f"      Implementations: {', '.join(impls)}")
                            elif len(swhid_groups) == 1:
                                swhid = list(swhid_groups.keys())[0]
                                impls = list(swhid_groups.values())[0]
                                logger.error(f"    Group 1: {swhid}")
                                logger.error(f"      Implementations: {', '.join(impls)}")
                            
                            # Show failed implementations
                            if failed_implementations:
                                logger.error(f"    Failed implementations:")
                                for impl_name, error in failed_implementations:
                                    logger.error(f"      {impl_name}: {error}")
                    
            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed to discover branches in {actual_repo_path}: {e}")
            except Exception as e:
                logger.warning(f"Error discovering branches: {e}")
        
        # Discover annotated tags
        if discover_tags:
            try:
                annotated_tags = self.git_manager.get_annotated_tags(actual_repo_path)
                logger.info(f"Discovered {len(annotated_tags)} annotated tags in {base_name}: {', '.join(annotated_tags)}")
                
                # Test each annotated tag as a release
                for tag in annotated_tags:
                    test_name = f"{base_name}_tag_{tag.replace('/', '_')}"
                    logger.info(f"Testing annotated tag '{tag}' as release: {test_name}")
                    
                    results = {}
                    with ThreadPoolExecutor(max_workers=self.config.settings.parallel_tests) as executor:
                        future_to_impl = {
                            executor.submit(self._run_single_test, impl, actual_repo_path, test_name, 
                                          category="release", tag=tag): impl
                            for impl in self.implementations.values()
                        }
                        for future in as_completed(future_to_impl):
                            impl = future_to_impl[future]
                            try:
                                result = future.result()
                                results[impl.get_info().name] = result
                            except Exception as e:
                                logger.error(f"Error running test for {impl.get_info().name}: {e}")
                    
                    # Compare results (no expected SWHID for discovered tests)
                    expected_swhid = expected_tags.get(tag)
                    comparison = self._compare_results(test_name, actual_repo_path, results, expected_swhid=expected_swhid, expected_swhid_sha256=None)
                    all_results.append(comparison)
                    
                    # Log results similar to regular tests
                    skipped_impls = [impl_name for impl_name, result in results.items() 
                                   if not result.success and any(phrase in str(result.error).lower() 
                                       for phrase in ["not supported", "doesn't support", "does not support", "unsupported"])]
                    
                    if comparison.all_match:
                        # Get the SWHID from any successful result
                        swhid = next((r.swhid for r in results.values() if r.success), None)
                        if swhid:
                            logger.info(f"[PASS] {test_name}: All implementations match - {swhid}")
                        else:
                            logger.info(f"[PASS] {test_name}: All implementations match")
                    else:
                        # Check if all implementations skipped
                        if skipped_impls and len(skipped_impls) == len(results):
                            logger.info(f"[SKIP] {test_name}: All implementations skipped (unsupported type)")
                        else:
                            logger.error(f"[FAIL] {test_name}: Implementations differ")
                            
                            # Show skipped implementations
                            if skipped_impls:
                                logger.info(f"  Skipped by: {', '.join(skipped_impls)}")
                            
                            # Group results by SWHID to show which implementations match
                            swhid_groups = {}
                            failed_implementations = []
                            
                            for impl_name, result in results.items():
                                if result.success:
                                    swhid = result.swhid
                                    if swhid not in swhid_groups:
                                        swhid_groups[swhid] = []
                                    swhid_groups[swhid].append(impl_name)
                                elif impl_name not in skipped_impls:
                                    failed_implementations.append((impl_name, result.error))
                            
                            # Show SWHID groups
                            if len(swhid_groups) > 1:
                                logger.error(f"  Found {len(swhid_groups)} different SWHID groups:")
                                for i, (swhid, impls) in enumerate(swhid_groups.items(), 1):
                                    logger.error(f"    Group {i}: {swhid}")
                                    logger.error(f"      Implementations: {', '.join(impls)}")
                            elif len(swhid_groups) == 1:
                                swhid = list(swhid_groups.keys())[0]
                                impls = list(swhid_groups.values())[0]
                                logger.error(f"    Group 1: {swhid}")
                                logger.error(f"      Implementations: {', '.join(impls)}")
                            
                            # Show failed implementations
                            if failed_implementations:
                                logger.error(f"    Failed implementations:")
                                for impl_name, error in failed_implementations:
                                    logger.error(f"      {impl_name}: {error}")
                    
            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed to discover tags in {actual_repo_path}: {e}")
            except Exception as e:
                logger.warning(f"Error discovering tags: {e}")
        
        return all_results
    
    def _is_unsupported_result(self, result: SwhidTestResult) -> bool:
        """Return True if the result represents an unsupported object type (delegates to ResultComparator)."""
        return self.comparator.is_unsupported_result(result)
    
    def _compare_results(self, payload_name: str, payload_path: str,
                        results: Dict[str, SwhidTestResult], 
                        expected_swhid: Optional[str] = None,
                        expected_swhid_sha256: Optional[str] = None,
                        expected_error: Optional[str] = None) -> ComparisonResult:
        """Compare results across implementations (delegates to ResultComparator)."""
        return self.comparator.compare_results(
            payload_name, payload_path, results,
            expected_swhid, expected_swhid_sha256, expected_error
        )
    
    def run_tests(self, implementations: Optional[List[str]] = None,
                  categories: Optional[List[str]] = None,
                  payloads: Optional[List[str]] = None,
                  version: Optional[int] = None,
                  hash_algo: Optional[str] = None,
                  test_both_versions: bool = False) -> List[ComparisonResult]:
        """Run tests for specified implementations and categories."""
        # Load implementations
        self.implementations = self._load_implementations(implementations)
        
        if not self.implementations:
            logger.error("No implementations available")
            return []
        
        # Initialize test runner and output generator with loaded implementations
        self.test_runner = TestRunner(
            self.config, self.config_path, self.implementations,
            self.resource_manager, self.git_manager
        )
        self.output_generator = OutputGenerator(
            self.implementations, self._get_implementation_git_sha
        )
        
        if categories is None:
            categories = list(self.config.payloads.keys())
        
        all_results = []
        
        for category in sorted(categories):  # Deterministic ordering
            if category not in self.config.payloads:
                logger.warning(f"Category '{category}' not found in config")
                continue
            
            logger.info(f"Testing category: {category}")
            
            # Sort payloads deterministically by name
            category_payloads = sorted(self.config.payloads[category], key=lambda p: p.name or p.path)
            
            # Filter by payload names if specified
            if payloads:
                category_payloads = [p for p in category_payloads if p.name in payloads]
                if not category_payloads:
                    logger.info(f"No matching payloads found in category '{category}' for filter: {payloads}")
                    continue
            
            for payload in category_payloads:
                payload_path = payload.path
                # Resolve to absolute path relative to config file directory
                if not os.path.isabs(payload_path):
                    config_dir = os.path.dirname(os.path.abspath(self.config_path))
                    payload_path = os.path.join(config_dir, payload_path)
                payload_name = payload.name
                expected_swhid = payload.expected_swhid
                expected_swhid_sha256 = payload.expected_swhid_sha256
                
                # Determine which version(s) to test
                # Priority: CLI flags > payload rust_config > expected values presence
                rust_config = payload.rust_config
                payload_version = rust_config.version if rust_config else None
                payload_hash = rust_config.hash if rust_config else None
                
                # CLI flags override config
                if version is not None:
                    # CLI version specified - use it
                    test_versions = [version]
                    test_hash = hash_algo or (payload_hash if version == 2 else None)
                elif test_both_versions and expected_swhid and expected_swhid_sha256:
                    # Test both versions if both expected values present and flag set
                    test_versions = [1, 2]
                    test_hash = hash_algo or payload_hash or "sha256"
                else:
                    # Determine from config/expected values
                    # Default behavior: test v1 only (backward compatible)
                    # Only test v2 if explicitly configured or both expected values present
                    test_versions = []
                    if expected_swhid:
                        test_versions.append(1)  # Always test v1 if expected_swhid present
                    if expected_swhid_sha256 and (payload_version == 2 or test_both_versions):
                        test_versions.append(2)  # Test v2 only if explicitly configured
                    
                    # If no explicit version config and no expected values, default to v1 only
                    if not test_versions:
                        test_versions = [1]
                    
                    test_hash = hash_algo or payload_hash
                
                # Ensure git payloads exist by creating synthetic repos on-the-fly
                # For synthetic repos, always recreate to ensure consistency
                if category == "git" and payload_name == "synthetic_repo":
                    try:
                        # Remove existing repo if it exists to ensure clean recreation
                        if os.path.exists(payload_path):
                            import shutil
                            if os.path.exists(os.path.join(payload_path, ".git")):
                                shutil.rmtree(payload_path)
                                os.makedirs(payload_path, exist_ok=True)
                        self.git_manager.create_minimal_git_repo(payload_path)
                        logger.info(f"Created/recreated synthetic git payload at: {payload_path}")
                    except Exception as e:
                        logger.warning(f"Failed to create synthetic git payload at: {payload_path}")
                        logger.debug(f"Error: {e}")
                        continue
                elif category == "git":
                    # For other git payloads, check if it's a valid Git repository
                    is_git_repo = False
                    if os.path.exists(payload_path):
                        # Check if it's actually a Git repository
                        git_dir = os.path.join(payload_path, ".git")
                        is_git_repo = self.git_manager.check_is_repository(payload_path)
                    
                    if not is_git_repo:
                        try:
                            self.git_manager.create_minimal_git_repo(payload_path)
                            logger.info(f"Created synthetic git payload at: {payload_path}")
                        except Exception as e:
                            logger.warning(f"Failed to create synthetic git payload at: {payload_path}")
                            logger.debug(f"Error: {e}")
                            continue
                elif not os.path.exists(payload_path):
                    logger.warning(f"Payload not found: {payload_path} - will emit SKIPPED status")
                    # Emit SKIPPED status for missing payloads
                    skipped_results = {}
                    for impl_name, impl in self.implementations.items():
                        skipped_results[impl_name] = SwhidTestResult(
                            payload_name=payload_name,
                            payload_path=payload_path,
                            implementation=impl_name,
                            success=False,
                            swhid=None,
                            error="Payload file not found",
                            duration=0.0,
                            metrics=TestMetrics(
                                wall_ms_median=0.0,
                                wall_ms_mad=0.0,
                                cpu_ms_median=0.0,
                                max_rss_kb=0
                            )
                        )
                    # Create comparison result with SKIPPED status
                    expected_error = payload.expected_error
                    expected_swhid_sha256 = payload.expected_swhid_sha256
                    comparison = ComparisonResult(
                        payload_name=payload_name,
                        payload_path=payload_path,
                        results=skipped_results,
                        all_match=False,  # SKIPPED is not a match
                        expected_swhid=expected_swhid,
                        expected_swhid_sha256=expected_swhid_sha256
                    )
                    all_results.append(comparison)
                    continue
                
                logger.info(f"Testing payload: {payload_name}")
                
                # Check if we should discover branches/tags
                discover_branches = payload.discover_branches
                discover_tags = payload.discover_tags
                
                if discover_branches or discover_tags:
                    # Generate test cases for discovered branches/tags
                    expected_config = payload.expected
                    if expected_config:
                        expected_config_dict = {
                            "branches": expected_config.branches,
                            "tags": expected_config.tags
                        }
                    else:
                        expected_config_dict = {}
                    discovered_tests = self._discover_git_tests(payload_path, payload_name, 
                                                                 discover_branches, discover_tags, expected_config_dict)
                    all_results.extend(discovered_tests)
                    continue
                
                # Get commit/tag metadata for revision/release tests
                commit = payload.commit
                tag = payload.tag
                
                # Run tests for all implementations and all versions
                results = {}
                with ThreadPoolExecutor(max_workers=self.config.settings.parallel_tests) as executor:
                    futures = []
                    for impl in self.implementations.values():
                        for test_version in test_versions:
                            # Determine hash algorithm for this version
                            version_hash = None
                            if test_version == 2:
                                version_hash = test_hash or "sha256"
                            
                            future = executor.submit(
                                self.test_runner.run_single_test,
                                impl,
                                payload_path,
                                payload_name,
                                category,
                                commit=commit,
                                tag=tag,
                                version=test_version,
                                hash_algo=version_hash
                            )
                            futures.append((future, impl, test_version))
                    
                    for future, impl, test_version in futures:
                        try:
                            result = future.result()
                            # Use a key that includes version to distinguish v1 and v2 results
                            result_key = f"{impl.get_info().name}"
                            if len(test_versions) > 1:
                                result_key = f"{impl.get_info().name}_v{test_version}"
                            results[result_key] = result
                        except Exception as e:
                            logger.error(f"Error running test for {impl.get_info().name} (v{test_version}): {e}")
                
                # Compare results
                expected_error = payload.expected_error
                comparison = self._compare_results(
                    payload_name,
                    payload_path,
                    results,
                    expected_swhid,
                    expected_swhid_sha256,
                    expected_error
                )
                all_results.append(comparison)
                
                # Log results
                # Check for skipped implementations
                skipped_impls = [impl_name for impl_name, result in results.items() 
                               if not result.success and any(phrase in str(result.error).lower() 
                                   for phrase in ["not supported", "doesn't support", "does not support", "unsupported"])]
                
                if comparison.all_match:
                    logger.info(f"[PASS] {payload_name}: All implementations match")
                    if expected_swhid:
                        logger.info(f"  Expected: {expected_swhid}")
                else:
                    # Check if all implementations skipped
                    if skipped_impls and len(skipped_impls) == len(results):
                        logger.info(f"[SKIP] {payload_name}: All implementations skipped (unsupported type)")
                    else:
                        logger.error(f"[FAIL] {payload_name}: Implementations differ")
                    
                    # Show expected result if available
                    if expected_swhid:
                        logger.info(f"  Expected: {expected_swhid}")
                    
                    # Show skipped implementations
                    if skipped_impls:
                        logger.info(f"  Skipped by: {', '.join(skipped_impls)}")
                    
                    # Group results by SWHID to show which implementations match
                    swhid_groups = {}
                    failed_implementations = []
                    
                    for impl_name, result in results.items():
                        if result.success:
                            swhid = result.swhid
                            if swhid not in swhid_groups:
                                swhid_groups[swhid] = []
                            swhid_groups[swhid].append(impl_name)
                        elif impl_name not in skipped_impls:
                            failed_implementations.append((impl_name, result.error))
                    
                    # Show SWHID groups
                    if len(swhid_groups) > 1:
                        logger.error(f"  Found {len(swhid_groups)} different SWHID groups:")
                        for i, (swhid, impls) in enumerate(swhid_groups.items(), 1):
                            logger.error(f"    Group {i}: {swhid}")
                            logger.error(f"      Implementations: {', '.join(impls)}")
                    elif len(swhid_groups) == 1:
                        # All successful implementations agree, but expected differs
                        swhid = list(swhid_groups.keys())[0]
                        impls = list(swhid_groups.values())[0]
                        logger.error(f"  All implementations agree: {swhid}")
                        logger.error(f"    Implementations: {', '.join(impls)}")
                        if expected_swhid and swhid != expected_swhid:
                            logger.error(f"    But expected: {expected_swhid}")
                    
                    # Show failed implementations
                    if failed_implementations:
                        logger.error(f"  Failed implementations:")
                        for impl_name, error in failed_implementations:
                            logger.error(f"    {impl_name}: {error}")
        
        return all_results

    def _create_minimal_git_repo(self, repo_path: str):
        """Create a small git repository (delegates to GitManager)."""
        self.git_manager.create_minimal_git_repo(repo_path)
    
    def generate_expected_results(self, implementation: str = "python"):
        """Generate expected results using a reference implementation."""
        logger.info(f"Generating expected results using {implementation}")
        
        # Load the reference implementation
        impl = self.discovery.get_implementation(implementation)
        if not impl:
            logger.error(f"Reference implementation '{implementation}' not found")
            return
        
        # Note: generate_expected_results modifies the config file directly
        # We need to work with the dict representation for YAML serialization
        config_dict = self.config.model_dump(mode='python')
        
        for category, payloads in config_dict["payloads"].items():
            for payload in payloads:
                payload_path = payload["path"]
                # Resolve to absolute path relative to config file directory
                if not os.path.isabs(payload_path):
                    config_dir = os.path.dirname(os.path.abspath(self.config_path))
                    payload_path = os.path.join(config_dir, payload_path)
                payload_name = payload["name"]
                
                if not os.path.exists(payload_path):
                    continue
                
                try:
                    # Determine object type from category
                    # Category names map to object types: content -> content, directory -> directory, git -> snapshot
                    if category == "git":
                        obj_type = "snapshot"
                    elif category == "content" or category.startswith("content/"):
                        obj_type = "content"
                    elif category == "directory" or category.startswith("directory/"):
                        obj_type = "directory"
                    elif category == "revision":
                        obj_type = "revision"
                    elif category == "release":
                        obj_type = "release"
                    else:
                        # Fallback to auto-detection for unknown categories
                        obj_type = impl.detect_object_type(payload_path)
                    
                    # For revision/release, note that most implementations don't support these yet
                    # They will be skipped if not supported
                    
                    swhid = impl.compute_swhid(payload_path, obj_type)
                    
                    # Update the config with expected SWHID
                    payload["expected_swhid"] = swhid
                    logger.info(f"Generated expected SWHID for {payload_name}: {swhid}")
                    
                except Exception as e:
                    logger.error(f"Error generating expected result for {payload_name}: {e}")
        
        # Save updated config
        with open(self.config_path, 'w') as f:
            yaml.dump(config_dict, f, default_flow_style=False)
        
        # Reload config to reflect changes
        self.config = HarnessConfig.load_from_file(self.config_path)
    
    def get_canonical_results(self, results: List[ComparisonResult], branch: str = "main", commit: str = "unknown") -> HarnessResults:
        """Generate canonical format results (delegates to OutputGenerator)."""
        if self.output_generator is None:
            # Initialize if not already done
            self.output_generator = OutputGenerator(
                self.implementations, self._get_implementation_git_sha
            )
        return self.output_generator.get_canonical_results(results, branch, commit)
    
    def _print_summary(self, canonical_results: HarnessResults):
        """Print enhanced summary with per-implementation and global statistics."""
        total_tests = len(canonical_results.tests)
        
        # Track per-implementation statistics
        impl_stats = {}
        impl_failed_tests = {}  # Failed tests per implementation (when expected is available)
        impl_skipped_tests = {}  # Skipped tests per implementation
        
        # Initialize stats for each implementation
        for impl in canonical_results.implementations:
            impl_id = impl.id
            impl_stats[impl_id] = {"passed": 0, "failed": 0, "skipped": 0}
            impl_failed_tests[impl_id] = []
            impl_skipped_tests[impl_id] = []
        
        # Track global statistics
        all_agree = 0  # All implementations agree (same SWHID or all PASS)
        disagreements = 0  # Implementations disagree (different SWHIDs or mixed statuses)
        fully_skipped = 0  # All implementations skipped
        
        # Process each test case
        for test_case in canonical_results.tests:
            has_expected = test_case.expected.swhid is not None
            expected_swhid = test_case.expected.swhid
            
            # Get all results for this test
            results = test_case.results
            statuses = {r.status for r in results}
            non_skipped_results = [r for r in results if r.status != "SKIPPED"]
            swhids = {r.swhid for r in non_skipped_results if r.swhid is not None}
            
            # Check if all implementations skipped
            if statuses == {"SKIPPED"}:
                fully_skipped += 1
                for result in results:
                    # Normalize implementation name (strip version suffix)
                    impl_name_base = result.implementation
                    if impl_name_base.endswith('_v1') or impl_name_base.endswith('_v2'):
                        impl_name_base = impl_name_base.rsplit('_', 1)[0]
                    if impl_name_base not in impl_stats:
                        impl_stats[impl_name_base] = {"passed": 0, "failed": 0, "skipped": 0}
                    impl_stats[impl_name_base]["skipped"] += 1
                    impl_skipped_tests[impl_name_base].append(test_case.id)
            else:
                # Process each implementation's result
                all_agree_on_this_test = True
                non_skipped_statuses = {r.status for r in non_skipped_results}
                
                # Check if all non-skipped implementations agree (same SWHID)
                # Must have at least one non-skipped result and all must agree
                if (len(non_skipped_results) > 0 and 
                    len(non_skipped_statuses) == 1 and 
                    "PASS" in non_skipped_statuses and 
                    len(swhids) == 1):
                    # All non-skipped implementations agree on SWHID
                    pass  # all_agree_on_this_test remains True
                else:
                    # There's a disagreement
                    all_agree_on_this_test = False
                
                # Count statistics per implementation
                for result in results:
                    # Normalize implementation name (strip version suffix for dual-version tests)
                    impl_name_base = result.implementation
                    if impl_name_base.endswith('_v1') or impl_name_base.endswith('_v2'):
                        impl_name_base = impl_name_base.rsplit('_', 1)[0]
                    
                    # Ensure normalized name exists in stats
                    if impl_name_base not in impl_stats:
                        impl_stats[impl_name_base] = {"passed": 0, "failed": 0, "skipped": 0}
                    
                    # Determine which expected value to check based on implementation name
                    # If implementation name has _v2 suffix, check against v2 expected
                    check_v2 = result.implementation.endswith('_v2')
                    expected_to_check = test_case.expected.expected_swhid_sha256 if check_v2 else test_case.expected.swhid
                    has_expected_for_version = expected_to_check is not None
                    
                    if result.status == "SKIPPED":
                        impl_stats[impl_name_base]["skipped"] += 1
                        impl_skipped_tests[impl_name_base].append(test_case.id)
                    elif result.status == "FAIL":
                        impl_stats[impl_name_base]["failed"] += 1
                        # Always add to failed tests list, regardless of whether expected exists
                        impl_failed_tests[impl_name_base].append(test_case.id)
                        all_agree_on_this_test = False
                    elif result.status == "PASS":
                        # Check if it matches expected (if available for this version)
                        if has_expected_for_version and result.swhid != expected_to_check:
                            # PASS but wrong SWHID - count as failure
                            impl_stats[impl_name_base]["failed"] += 1
                            impl_failed_tests[impl_name_base].append(test_case.id)
                            all_agree_on_this_test = False
                        else:
                            # PASS and matches expected (or no expected) - count as pass
                            impl_stats[impl_name_base]["passed"] += 1
                
                # Update global counters
                if all_agree_on_this_test:
                    all_agree += 1
                else:
                    disagreements += 1
        
        # Print global summary
        print(f"\nSummary: {all_agree}/{total_tests} all implementations agree, {disagreements}/{total_tests} disagreements, {fully_skipped} fully skipped")
        
        # Print per-implementation summaries
        print("\nPer-implementation summary:")
        for impl in sorted(canonical_results.implementations, key=lambda x: x.id):
            impl_id = impl.id
            stats = impl_stats[impl_id]
            total = stats["passed"] + stats["failed"] + stats["skipped"]
            print(f"  {impl_id}: {stats['passed']}/{total} passed, {stats['failed']} failed, {stats['skipped']} fully skipped")
        
        # Print failed tests per implementation (when expected is available)
        print("\nFailed tests per implementation:")
        for impl in sorted(canonical_results.implementations, key=lambda x: x.id):
            impl_id = impl.id
            failed = impl_failed_tests[impl_id]
            if failed:
                unique_failed = sorted(set(failed))
                print(f"  {impl_id}: {len(unique_failed)} test(s)")
                for test_id in unique_failed:
                    print(f"    [FAIL] {test_id}")
            else:
                print(f"  {impl_id}: 0 failed")
        
        # Print skipped tests per implementation
        if any(impl_skipped_tests.values()):
            print("\nSkipped tests per implementation:")
            for impl in sorted(canonical_results.implementations, key=lambda x: x.id):
                impl_id = impl.id
                skipped = impl_skipped_tests[impl_id]
                if skipped:
                    unique_skipped = sorted(set(skipped))
                    print(f"  {impl_id}: {len(unique_skipped)} test(s)")
                    for test_id in unique_skipped:
                        print(f"    - {test_id}")
        
        # Print detailed disagreement summary
        disagreement_tests = []
        for test_case in canonical_results.tests:
            has_expected_v1 = test_case.expected.swhid is not None
            has_expected_v2 = test_case.expected.expected_swhid_sha256 is not None
            expected_swhid_v1 = test_case.expected.swhid
            expected_swhid_v2 = test_case.expected.expected_swhid_sha256
            
            # Get all results for this test
            results = test_case.results
            non_skipped_results = [r for r in results if r.status != "SKIPPED"]
            
            # Skip if all implementations agree or all skipped
            if len(non_skipped_results) == 0:
                continue
            
            # Group by SWHID and status
            swhid_groups = {}  # swhid -> list of (impl_id, status)
            failed_impls = []  # list of (impl_id, error_message)
            
            # Map implementation to expected value
            expected_by_impl = {}  # impl_name -> expected_swhid
            for result in non_skipped_results:
                if result.implementation.endswith('_v2'):
                    expected_by_impl[result.implementation] = expected_swhid_v2
                else:
                    expected_by_impl[result.implementation] = expected_swhid_v1
            
            for result in non_skipped_results:
                if result.status == "FAIL":
                    error_msg = result.error.message if result.error else "Unknown error"
                    failed_impls.append((result.implementation, error_msg))
                elif result.status == "PASS" and result.swhid:
                    swhid = result.swhid
                    if swhid not in swhid_groups:
                        swhid_groups[swhid] = []
                    swhid_groups[swhid].append(result.implementation)
            
            # Check if there's a disagreement
            # Disagreement exists if:
            # - Multiple different SWHIDs
            # - Or one SWHID but doesn't match expected (when expected exists for that version)
            # - Or there are failures
            has_disagreement = False
            if len(swhid_groups) > 1:
                has_disagreement = True
            elif len(swhid_groups) == 1:
                computed_swhid = list(swhid_groups.keys())[0]
                impls_in_group = swhid_groups[computed_swhid]
                # Check if any implementation's result doesn't match its expected
                for impl_id in impls_in_group:
                    expected_for_impl = expected_by_impl.get(impl_id)
                    if expected_for_impl and computed_swhid != expected_for_impl:
                        has_disagreement = True
                        break
            elif failed_impls:
                has_disagreement = True
            
            if has_disagreement:
                disagreement_tests.append({
                    'test_id': test_case.id,
                    'category': test_case.category,
                    'has_expected_v1': has_expected_v1,
                    'has_expected_v2': has_expected_v2,
                    'expected_swhid_v1': expected_swhid_v1,
                    'expected_swhid_v2': expected_swhid_v2,
                    'expected_by_impl': expected_by_impl,
                    'swhid_groups': swhid_groups,
                    'failed_impls': failed_impls
                })
        
        # Print disagreement details
        if disagreement_tests:
            print(f"\nDisagreements summary ({len(disagreement_tests)} test(s) with disagreements):")
            for disc in disagreement_tests:
                print(f"\n  [FAIL] {disc['test_id']} ({disc['category']})")
                
                # Show expected result status (show both v1 and v2 if available)
                expected_lines = []
                if disc.get('has_expected_v1'):
                    expected_lines.append(f"Expected (v1): {disc['expected_swhid_v1']}")
                if disc.get('has_expected_v2'):
                    expected_lines.append(f"Expected (v2): {disc['expected_swhid_v2']}")
                if expected_lines:
                    for line in expected_lines:
                        print(f"    {line}")
                else:
                    print(f"    Expected: (none)")
                
                # Show SWHID groups
                if disc['swhid_groups']:
                    if len(disc['swhid_groups']) > 1:
                        print(f"    Found {len(disc['swhid_groups'])} different SWHID groups:")
                        for i, (swhid, impls) in enumerate(sorted(disc['swhid_groups'].items()), 1):
                            # Check if this SWHID matches expected for any implementation in group
                            matches_any = False
                            for impl_id in impls:
                                expected_for_impl = disc.get('expected_by_impl', {}).get(impl_id)
                                if expected_for_impl and swhid == expected_for_impl:
                                    matches_any = True
                                    break
                            
                            match_indicator = " [PASS] (matches expected)" if matches_any else " [FAIL] (differs from expected)"
                            print(f"      Group {i}: {swhid}{match_indicator}")
                            print(f"        Implementations: {', '.join(sorted(impls))}")
                    else:
                        # Single group
                        swhid = list(disc['swhid_groups'].keys())[0]
                        impls = list(disc['swhid_groups'].values())[0]
                        # Check if this SWHID matches expected for any implementation
                        # Also detect version from SWHID format (swh:2: vs swh:1:)
                        is_v2_swhid = swhid.startswith('swh:2:')
                        matches_any = False
                        for impl_id in impls:
                            expected_for_impl = disc.get('expected_by_impl', {}).get(impl_id)
                            # If no expected_by_impl entry, try to infer from SWHID version
                            if not expected_for_impl:
                                if is_v2_swhid and disc.get('has_expected_v2'):
                                    expected_for_impl = disc.get('expected_swhid_v2')
                                elif not is_v2_swhid and disc.get('has_expected_v1'):
                                    expected_for_impl = disc.get('expected_swhid_v1')
                            
                            if expected_for_impl and swhid == expected_for_impl:
                                matches_any = True
                                break
                        
                        match_indicator = " [PASS] (matches expected)" if matches_any else " [FAIL] (differs from expected)"
                        print(f"    Computed SWHID: {swhid}{match_indicator}")
                        print(f"      Implementations: {', '.join(sorted(impls))}")
                
                # Show failed implementations
                if disc['failed_impls']:
                    print(f"    Failed implementations ({len(disc['failed_impls'])}):")
                    for impl_id, error_msg in disc['failed_impls']:
                        # Truncate long error messages
                        if len(error_msg) > 80:
                            error_msg = error_msg[:77] + "..."
                        print(f"      {impl_id}: {error_msg}")
        else:
            print("\nNo disagreements found - all implementations agree on all tests.")
    
    def _get_implementation_git_sha(self, impl_name: str, impl_info: ImplementationInfo) -> Optional[str]:
        """Try to get git SHA for an implementation."""
        import subprocess
        from pathlib import Path
        
        # Check if implementation directory exists
        impl_dir = Path("implementations") / impl_name
        if not impl_dir.exists():
            return None
        
        try:
            # Try to get git SHA from the implementation directory
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=impl_dir,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=2
            )
            if result.returncode == 0:
                return result.stdout.strip()[:12]  # Short SHA
        except Exception:
            pass
        
        # Fallback: try to get from repo root if implementation is in this repo
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=2
            )
            if result.returncode == 0:
                return result.stdout.strip()[:12]
        except Exception:
            pass
        
        return None
    
    def _classify_error(self, error: Any) -> tuple[str, str]:
        """
        Classify error into ErrorCode and subtype.
        
        If error is a SwhidHarnessError, extract error code and subtype.
        Otherwise, classify based on error message string.
        
        Args:
            error: Exception instance or error string
            
        Returns:
            Tuple of (error_code, subtype)
        """
        # If it's already a SwhidHarnessError, extract the error code
        if isinstance(error, SwhidHarnessError):
            if error.error_code:
                return (error.error_code.value, error.subtype or "generic")
            # Fall through to string classification
        
        error_str = str(error).lower()
        
        # Timeout errors
        if "timeout" in error_str or "timed out" in error_str:
            return ("TIMEOUT", "wall_clock")
        
        # Resource limit errors
        if "rss limit" in error_str or "memory" in error_str or "resource" in error_str:
            return ("RESOURCE_LIMIT", "memory")
        if "cpu" in error_str and "limit" in error_str:
            return ("RESOURCE_LIMIT", "cpu")
        
        # I/O errors
        if "file not found" in error_str or "no such file" in error_str:
            return ("IO_ERROR", "file_not_found")
        if "permission denied" in error_str or "permission" in error_str:
            return ("IO_ERROR", "permission_denied")
        if "json" in error_str and ("decode" in error_str or "invalid" in error_str):
            return ("IO_ERROR", "protocol_violation")
        if "process" in error_str and ("failed" in error_str or "crashed" in error_str):
            return ("IO_ERROR", "process_crash")
        
        # Parse errors (invalid SWHID format)
        if "invalid swhid" in error_str or "invalid format" in error_str:
            return ("PARSE_ERROR", "format")
        if "invalid" in error_str and ("scheme" in error_str or "version" in error_str):
            return ("PARSE_ERROR", "syntax")
        
        # Validation errors
        if "hash" in error_str and "match" in error_str:
            return ("VALIDATION_ERROR", "hash_mismatch")
        if "semantic" in error_str or "semantically invalid" in error_str:
            return ("VALIDATION_ERROR", "semantic")
        
        # Mismatch errors (handled separately, but included for completeness)
        if "mismatch" in error_str:
            return ("MISMATCH_ERROR", "value")
        
        # Default: COMPUTE_ERROR (most common)
        return ("COMPUTE_ERROR", "exception")

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
                    print(f"\n  [FAIL] {result.payload_name}")
                    
                    # Show expected result if available
                    if result.expected_swhid:
                        print(f"    Expected: {result.expected_swhid}")
                    
                    # Group results by SWHID
                    swhid_groups = {}
                    failed_implementations = []
                    
                    for impl_name, test_result in result.results.items():
                        if test_result.success:
                            swhid = test_result.swhid
                            if swhid not in swhid_groups:
                                swhid_groups[swhid] = []
                            swhid_groups[swhid].append(impl_name)
                        else:
                            failed_implementations.append((impl_name, test_result.error))
                    
                    # Show SWHID groups
                    if len(swhid_groups) > 1:
                        print(f"    Found {len(swhid_groups)} different SWHID groups:")
                        for i, (swhid, impls) in enumerate(swhid_groups.items(), 1):
                            print(f"      Group {i}: {swhid}")
                            print(f"        Implementations: {', '.join(impls)}")
                    elif len(swhid_groups) == 1:
                        swhid = list(swhid_groups.keys())[0]
                        impls = list(swhid_groups.values())[0]
                        print(f"    All implementations agree: {swhid}")
                        print(f"      Implementations: {', '.join(impls)}")
                        if result.expected_swhid and swhid != result.expected_swhid:
                            print(f"      But expected: {result.expected_swhid}")
                    
                    # Show failed implementations
                    if failed_implementations:
                        print(f"    Failed implementations:")
                        for impl_name, error in failed_implementations:
                            print(f"      {impl_name}: {error}")
        
        print("=" * 50)

def main():
    parser = argparse.ArgumentParser(description="SWHID Testing Harness")
    parser.add_argument("--impl", nargs="*", help="Specific implementations to test (comma-separated or space-separated)")
    parser.add_argument("--category", nargs="*", help="Specific categories to test (comma-separated or space-separated)")
    parser.add_argument("--payload", nargs="*", help="Specific payload names to test (comma-separated or space-separated)")
    parser.add_argument("--config", default="config.yaml", help="Configuration file")
    parser.add_argument("--generate-expected", action="store_true", 
                       help="Generate expected results using reference implementation")
    parser.add_argument("--output-format", choices=["canonical", "ndjson"], default="canonical",
                       help="Output format for results (canonical JSON or NDJSON)")
    parser.add_argument("--reference-impl", default="python",
                       help="Reference implementation for generating expected results")
    parser.add_argument("--dashboard-output", help="Save dashboard results to file")
    parser.add_argument("--branch", default="main", help="Git branch name")
    parser.add_argument("--commit", default="unknown", help="Git commit hash")
    
    # New CLI options (P1)
    parser.add_argument("--list-impls", action="store_true",
                       help="List all available implementations and exit")
    parser.add_argument("--list-payloads", action="store_true",
                       help="List all test payloads and exit")
    parser.add_argument("--fail-fast", action="store_true",
                       help="Stop on first failure")
    parser.add_argument("--summary-only", action="store_true",
                       help="Show only summary, not detailed results")
    parser.add_argument("--seed", type=int, help="Random seed for deterministic ordering")
    parser.add_argument("--deep", action="store_true",
                       help="Run deep test suite including property-based tests")
    
    # SWHID v2/SHA256 support
    parser.add_argument("--version", type=int, choices=[1, 2],
                       help="SWHID version to use (1 for v1/SHA1, 2 for v2/SHA256). Overrides config.")
    parser.add_argument("--hash", choices=["sha1", "sha256"],
                       help="Hash algorithm to use (sha1 for v1, sha256 for v2). Overrides config.")
    parser.add_argument("--test-both-versions", action="store_true",
                       help="Run both v1 and v2 tests when both expected values are present")
    
    args = parser.parse_args()
    
    harness = SwhidHarness(args.config)
    
    # Handle list commands
    if args.list_impls:
        impls = harness.discovery.list_available_implementations()
        print("Available implementations:")
        for impl_name in sorted(impls):
            impl = harness.discovery.get_implementation(impl_name)
            if impl:
                info = impl.get_info()
                available = "[OK]" if impl.is_available() else "[FAIL]"
                print(f"  {available} {impl_name}: {info.description} (v{info.version})")
        return
    
    if args.list_payloads:
        print("Available test payloads:")
        for category, payloads in sorted(harness.config.payloads.items()):
            print(f"\n  {category}:")
            for payload in sorted(payloads, key=lambda p: p.name or ""):
                name = payload.name or "unnamed"
                path = payload.path or ""
                expected = payload.expected_swhid
                status = "[PASS]" if expected else "[SKIP]"
                print(f"    {status} {name}: {path}")
        return
    
    if args.generate_expected:
        harness.generate_expected_results(args.reference_impl)
    else:
        # Set random seed if provided
        if args.seed is not None:
            import random
            random.seed(args.seed)
        
        # Parse comma-separated or space-separated arguments
        impl_list = None
        if args.impl:
            # args.impl is a list (from nargs="*")
            # If it's a single element with commas, split it; otherwise use as-is
            if len(args.impl) == 1 and ',' in args.impl[0]:
                impl_list = [i.strip() for i in args.impl[0].split(',')]
            else:
                impl_list = args.impl
        
        category_list = None
        if args.category:
            # args.category is a list (from nargs="*")
            # If it's a single element with commas, split it; otherwise use as-is
            if len(args.category) == 1 and ',' in args.category[0]:
                category_list = [c.strip() for c in args.category[0].split(',')]
            else:
                category_list = args.category
        
        payload_list = None
        if args.payload:
            # args.payload is a list (from nargs="*")
            # If it's a single element with commas, split it; otherwise use as-is
            if len(args.payload) == 1 and ',' in args.payload[0]:
                payload_list = [p.strip() for p in args.payload[0].split(',')]
            else:
                payload_list = args.payload
        
        results = harness.run_tests(
            implementations=impl_list,
            categories=category_list,
            payloads=payload_list,
            version=args.version,
            hash_algo=args.hash,
            test_both_versions=args.test_both_versions
        )
        
        # Check for failures if fail-fast
        if args.fail_fast:
            failed = [r for r in results if not r.all_match]
            if failed:
                logger.error(f"Fail-fast: Stopping after first failure")
                # Exit with code 1 for mismatch
                sys.exit(1)
        
        # Generate canonical results
        canonical_results = harness.get_canonical_results(results, args.branch, args.commit)
        
        # Default behavior: write to results directory if no output specified
        # This maintains compatibility with original swhid-harness behavior
        # Always write output file first (before summary) to ensure it's created even if there are errors
        if args.summary_only:
            harness._print_summary(canonical_results)
        elif args.dashboard_output:
            # Write to specified file
            try:
                if args.output_format == "ndjson":
                    # Write NDJSON format (one JSON object per line)
                    with open(args.dashboard_output, 'w') as f:
                        # Write run info
                        f.write(json.dumps({"type": "run_info", **canonical_results.run.model_dump(mode="json")}) + "\n")
                        # Write implementations
                        for impl in canonical_results.implementations:
                            f.write(json.dumps({"type": "implementation", **impl.model_dump(mode="json")}) + "\n")
                        # Write test cases
                        for test in canonical_results.tests:
                            f.write(json.dumps({"type": "test_case", **test.model_dump(mode="json")}) + "\n")
                        # Write aggregates
                        f.write(json.dumps({"type": "aggregates", **canonical_results.aggregates.model_dump(mode="json")}) + "\n")
                    print(f"NDJSON results saved to {args.dashboard_output}")
                else:
                    # Write canonical JSON format
                    with open(args.dashboard_output, 'w') as f:
                        json.dump(canonical_results.model_dump(mode="json"), f, indent=2)
                    print(f"Canonical results saved to {args.dashboard_output}")
            except Exception as e:
                logger.error(f"Failed to write results to {args.dashboard_output}: {e}")
                raise
            
            # Always show summary when saving to file
            harness._print_summary(canonical_results)
        else:
            # Default: write to results directory (original behavior)
            # Generate filename with timestamp
            run_id = canonical_results.run.id
            if args.output_format == "ndjson":
                output_path = harness.results_dir / f"results_{run_id}.ndjson"
                with open(output_path, 'w') as f:
                    f.write(json.dumps({"type": "run_info", **canonical_results.run.model_dump(mode="json")}) + "\n")
                    for impl in canonical_results.implementations:
                        f.write(json.dumps({"type": "implementation", **impl.model_dump(mode="json")}) + "\n")
                    for test in canonical_results.tests:
                        f.write(json.dumps({"type": "test_case", **test.model_dump(mode="json")}) + "\n")
                    f.write(json.dumps({"type": "aggregates", **canonical_results.aggregates.model_dump(mode="json")}) + "\n")
                print(f"NDJSON results saved to {output_path}")
            else:
                output_path = harness.results_dir / f"results_{run_id}.json"
                with open(output_path, 'w') as f:
                    json.dump(canonical_results.model_dump(mode="json"), f, indent=2)
                print(f"Canonical results saved to {output_path}")
            
            # Always show summary
            harness._print_summary(canonical_results)
        
        # Exit code: 0=all pass, 1=mismatch, 2=error
        failed = sum(1 for r in results if not r.all_match)
        if failed > 0:
            sys.exit(1)  # Mismatch
        sys.exit(0)  # All pass

if __name__ == "__main__":
    main()
