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

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SwhidHarness:
    """Main testing harness for SWHID implementations."""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config()
        self.results_dir = Path(self.config["output"]["results_dir"])
        self.results_dir.mkdir(exist_ok=True)
        
        # Initialize implementation discovery
        self.discovery = ImplementationDiscovery()
        self.implementations = {}
        
        # Track temporary directories created from tarballs
        self._temp_dirs = []
        
        # Register cleanup function
        atexit.register(self._cleanup_temp_dirs)
        
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)
    
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
        """Clean up temporary directories created from tarballs."""
        for temp_dir in self._temp_dirs:
            if os.path.exists(temp_dir):
                try:
                    if platform.system() == 'Windows':
                        # On Windows, use a more robust cleanup that handles locked files
                        self._rmtree_windows(temp_dir)
                    else:
                        shutil.rmtree(temp_dir)
                    logger.debug(f"Cleaned up temporary directory: {temp_dir}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temporary directory {temp_dir}: {e}")
        self._temp_dirs.clear()
    
    def _rmtree_windows(self, path):
        """Windows-specific recursive delete that handles locked files gracefully.
        
        On Windows, Git object files may be locked by the file system, preventing
        normal deletion. This method attempts to handle such cases gracefully.
        """
        import stat
        import time
        
        def handle_remove_readonly(func, path, exc):
            """Handle readonly files on Windows."""
            if os.path.exists(path):
                try:
                    os.chmod(path, stat.S_IWRITE)
                    func(path)
                except (OSError, PermissionError):
                    pass  # Skip files that can't be modified
        
        # Retry with exponential backoff for locked files
        max_retries = 3
        for attempt in range(max_retries):
            try:
                shutil.rmtree(path, onerror=handle_remove_readonly)
                return
            except (OSError, PermissionError) as e:
                if attempt < max_retries - 1:
                    time.sleep(0.1 * (2 ** attempt))
                else:
                    # Last attempt failed - try best-effort cleanup
                    logger.debug(f"Could not fully remove {path} after {max_retries} attempts, attempting best-effort cleanup")
                    try:
                        # Try to remove individual files that aren't locked
                        for root, dirs, files in os.walk(path, topdown=False):
                            for name in files:
                                file_path = os.path.join(root, name)
                                try:
                                    os.chmod(file_path, stat.S_IWRITE)
                                    os.remove(file_path)
                                except (OSError, PermissionError):
                                    pass  # Skip locked files
                            for name in dirs:
                                dir_path = os.path.join(root, name)
                                try:
                                    os.rmdir(dir_path)
                                except (OSError, PermissionError):
                                    pass  # Skip locked directories
                    except Exception:
                        pass  # Best effort cleanup - don't fail if this also fails
    
    def _obj_type_to_swhid_code(self, obj_type: str) -> str:
        """Map object type to SWHID type code."""
        mapping = {
            "content": "cnt",
            "directory": "dir",
            "revision": "rev",
            "release": "rel",
            "snapshot": "snp"
        }
        return mapping.get(obj_type, obj_type)
    
    def _extract_tarball_if_needed(self, payload_path: str) -> str:
        """Extract tarball to temporary directory if payload is a .tar.gz file.
        
        Returns:
            Path to the extracted directory (or original path if not a tarball)
        """
        if not payload_path.endswith('.tar.gz'):
            return payload_path
        
        # Resolve absolute path
        if not os.path.isabs(payload_path):
            config_dir = os.path.dirname(os.path.abspath(self.config_path))
            payload_path = os.path.join(config_dir, payload_path)
        
        if not os.path.exists(payload_path):
            raise FileNotFoundError(f"Tarball not found: {payload_path}")
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp(prefix="swhid_test_")
        self._temp_dirs.append(temp_dir)
        
        # Extract tarball
        logger.debug(f"Extracting {payload_path} to {temp_dir}")
        with tarfile.open(payload_path, "r:gz") as tar:
            tar.extractall(temp_dir)
        
        # Find the extracted directory (should be the first directory in the tarball)
        extracted_items = os.listdir(temp_dir)
        if len(extracted_items) == 1 and os.path.isdir(os.path.join(temp_dir, extracted_items[0])):
            extracted_path = os.path.join(temp_dir, extracted_items[0])
        else:
            # Multiple items or unexpected structure - use temp_dir itself
            extracted_path = temp_dir
        
        logger.debug(f"Extracted to: {extracted_path}")
        return extracted_path
    
    def _resolve_commit_reference(self, repo_path: str, commit: Optional[str] = None) -> Optional[str]:
        """Resolve a commit reference (branch name, tag, short SHA) to a full SHA.
        
        Returns the full SHA if successful, or the original commit string if resolution fails.
        """
        if not commit or commit == "HEAD" or len(commit) == 40:
            # HEAD, None, or already a full SHA - return as-is
            return commit
        
        # Try to resolve using git rev-parse (handles branch names, tags, short SHAs)
        try:
            result = subprocess.run(
                ["git", "rev-parse", commit],
                cwd=repo_path,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                check=True,
                timeout=5
            )
            return result.stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            # Resolution failed - return original (let implementation handle it)
            return commit
    
    def _run_single_test(self, implementation: SwhidImplementation, payload_path: str, 
                         payload_name: str, category: Optional[str] = None, 
                         commit: Optional[str] = None, tag: Optional[str] = None,
                         version: Optional[int] = None, hash_algo: Optional[str] = None) -> SwhidTestResult:
        """Run a single test for one implementation."""
        start_time = time.time()
        
        try:
            # Extract tarball if needed
            actual_payload_path = self._extract_tarball_if_needed(payload_path)
            
            # Determine object type from category if available, otherwise auto-detect
            if category:
                # Map category to object type
                if category == "content" or category.startswith("content/"):
                    obj_type = "content"
                elif category == "directory" or category.startswith("directory/"):
                    obj_type = "directory"  # Don't auto-detect as snapshot for directory tests
                elif category == "git":
                    obj_type = "snapshot"  # Git category means snapshot
                elif category == "git-repository":
                    # git-repository category: auto-detect based on payload (can be snapshot, revision, or release)
                    obj_type = implementation.detect_object_type(actual_payload_path)
                elif category == "revision":
                    obj_type = "revision"  # Revision category means revision (Git commit)
                elif category == "release":
                    obj_type = "release"  # Release category means release (Git tag)
                else:
                    # Fallback to auto-detection for unknown categories
                    obj_type = implementation.detect_object_type(actual_payload_path)
            else:
                # Auto-detect object type if category not provided
                obj_type = implementation.detect_object_type(actual_payload_path)
            
            # Check if implementation supports this object type
            capabilities = implementation.get_capabilities()
            swhid_code = self._obj_type_to_swhid_code(obj_type)
            
            if swhid_code not in capabilities.supported_types:
                # Skip test - implementation doesn't support this type
                logger.info(f"Skipping {payload_name} for {implementation.get_info().name}: unsupported type '{obj_type}' (SWHID code '{swhid_code}')")
                return SwhidTestResult(
                    payload_name=payload_name,
                    payload_path=payload_path,
                    implementation=implementation.get_info().name,
                    swhid=None,
                    error=f"Object type '{obj_type}' (SWHID code '{swhid_code}') not supported by implementation",
                    duration=0.0,
                    success=False,
                    version=version if version is not None else 1
                )
            
            # Resolve commit reference to full SHA if needed (for branch names, tags, short SHAs)
            # This ensures all implementations receive a full SHA, not branch names
            resolved_commit = commit
            if commit and obj_type == "revision":
                resolved_commit = self._resolve_commit_reference(actual_payload_path, commit)
            
            # For revision/release, pass commit/tag information to implementations
            # Use resolved commit (full SHA) instead of original commit reference
            # Pass version/hash config if provided
            compute_kwargs = {"commit": resolved_commit, "tag": tag}
            if version is not None:
                compute_kwargs["version"] = version
            if hash_algo is not None:
                compute_kwargs["hash_algo"] = hash_algo
            
            swhid = implementation.compute_swhid(actual_payload_path, obj_type, **compute_kwargs)
            duration = time.time() - start_time
            
            # Determine SWHID version from result
            # Priority: explicit version parameter > SWHID string detection > default to 1
            if version is not None:
                result_version = version
            elif swhid and swhid.startswith("swh:2:"):
                result_version = 2
            elif swhid and swhid.startswith("swh:1:"):
                result_version = 1
            else:
                result_version = 1  # Default fallback
            
            return SwhidTestResult(
                payload_name=payload_name,
                payload_path=payload_path,
                implementation=implementation.get_info().name,
                swhid=swhid,
                error=None,
                duration=duration,
                success=True,
                version=result_version
            )
            
        except Exception as e:
            duration = time.time() - start_time
            error_str = str(e)
            # Check if this is an "unsupported type" error that should be skipped
            if any(phrase in error_str.lower() for phrase in [
                "doesn't support", "does not support", "not support", 
                "unsupported", "not supported"
            ]):
                logger.info(f"Skipping {payload_name} for {implementation.get_info().name}: {error_str}")
                return SwhidTestResult(
                    payload_name=payload_name,
                    payload_path=payload_path,
                    implementation=implementation.get_info().name,
                    swhid=None,
                    error=f"Object type not supported: {error_str}",
                    duration=0.0,
                    success=False,
                    version=version if version is not None else 1
                )
            return SwhidTestResult(
                payload_name=payload_name,
                payload_path=payload_path,
                implementation=implementation.get_info().name,
                swhid=None,
                error=error_str,
                duration=duration,
                success=False,
                version=version if version is not None else 1
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
        actual_repo_path = self._extract_tarball_if_needed(repo_path)
        
        if not os.path.exists(actual_repo_path):
            logger.warning(f"Repository not found: {actual_repo_path}")
            return all_results
        
        # Discover branches
        if discover_branches:
            try:
                result = subprocess.run(
                    ["git", "branch", "-a"],
                    cwd=actual_repo_path,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    check=True,
                    timeout=10
                )
                branches = []
                for line in result.stdout.strip().split('\n'):
                    branch = line.strip().lstrip('*').strip()
                    # Remove remote prefix and filter out HEAD
                    if branch.startswith('remotes/'):
                        branch = branch.replace('remotes/origin/', '').replace('remotes/', '')
                    if branch and branch != 'HEAD' and not branch.startswith('remotes/'):
                        branches.append(branch)
                
                # Remove duplicates and sort
                branches = sorted(set(branches))
                logger.info(f"Discovered {len(branches)} branches in {base_name}: {', '.join(branches)}")
                
                # Test each branch as a revision
                for branch in branches:
                    test_name = f"{base_name}_branch_{branch.replace('/', '_')}"
                    logger.info(f"Testing branch '{branch}' as revision: {test_name}")
                    
                    results = {}
                    with ThreadPoolExecutor(max_workers=self.config["settings"]["parallel_tests"]) as executor:
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
                result = subprocess.run(
                    ["git", "tag", "-l"],
                    cwd=actual_repo_path,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    check=True,
                    timeout=10
                )
                all_tags = [tag.strip() for tag in result.stdout.strip().split('\n') if tag.strip()]
                
                # Filter to only annotated tags
                annotated_tags = []
                for tag in all_tags:
                    try:
                        tag_type_result = subprocess.run(
                            ["git", "cat-file", "-t", tag],
                            cwd=actual_repo_path,
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='replace',
                            check=True,
                            timeout=5
                        )
                        if tag_type_result.stdout.strip() == "tag":
                            annotated_tags.append(tag)
                    except subprocess.CalledProcessError:
                        # Skip if we can't determine type
                        continue
                
                annotated_tags = sorted(annotated_tags)
                logger.info(f"Discovered {len(annotated_tags)} annotated tags in {base_name}: {', '.join(annotated_tags)}")
                
                # Test each annotated tag as a release
                for tag in annotated_tags:
                    test_name = f"{base_name}_tag_{tag.replace('/', '_')}"
                    logger.info(f"Testing annotated tag '{tag}' as release: {test_name}")
                    
                    results = {}
                    with ThreadPoolExecutor(max_workers=self.config["settings"]["parallel_tests"]) as executor:
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
        """Return True if the result represents an unsupported object type."""
        if result.success:
            return False
        if not result.error:
            return False
        err = str(result.error).lower()
        return "object type" in err and "not support" in err
    
    def _compare_results(self, payload_name: str, payload_path: str,
                        results: Dict[str, SwhidTestResult], 
                        expected_swhid: Optional[str] = None,
                        expected_swhid_sha256: Optional[str] = None,
                        expected_error: Optional[str] = None) -> ComparisonResult:
        """Compare results across implementations."""
        supported_results = {
            name: result for name, result in results.items()
            if not self._is_unsupported_result(result)
        }
        
        if not supported_results:
            all_unsupported = results and all(self._is_unsupported_result(r) for r in results.values())
            if all_unsupported:
                return ComparisonResult(
                    payload_name=payload_name,
                    payload_path=payload_path,
                    results=results,
                    all_match=True,
                    expected_swhid=expected_swhid
                )
            # Fall through to regular comparison (e.g., missing payloads)
            supported_results = results
        
        # Handle negative tests: if expected_error is set, all supporting implementations should fail
        if expected_error and supported_results:
            all_failed = all(not r.success for r in supported_results.values())
            if all_failed:
                # All supporting implementations correctly rejected the invalid input
                return ComparisonResult(
                    payload_name=payload_name,
                    payload_path=payload_path,
                    results=results,
                    all_match=True,
                    expected_swhid=expected_swhid,
                    expected_swhid_sha256=expected_swhid_sha256
                )
        
        # Check if all implementations succeeded
        all_success = all(r.success for r in supported_results.values())
        
        if not all_success:
            return ComparisonResult(
                payload_name=payload_name,
                payload_path=payload_path,
                results=results,
                all_match=False,
                expected_swhid=expected_swhid,
                expected_swhid_sha256=expected_swhid_sha256
            )
        
        # Get all SWHIDs, grouped by version
        v1_swhids = [r.swhid for r in supported_results.values() 
                     if r.swhid and r.version == 1]
        v2_swhids = [r.swhid for r in supported_results.values() 
                     if r.swhid and r.version == 2]
        
        # Check if all SWHIDs match within each version group
        v1_match = len(set(v1_swhids)) == 1 if v1_swhids else True  # True if no v1 results
        v2_match = len(set(v2_swhids)) == 1 if v2_swhids else True  # True if no v2 results
        
        all_match = v1_match and v2_match
        
        # Check against expected SWHIDs if provided
        if all_match:
            if v1_swhids and expected_swhid:
                all_match = v1_swhids[0] == expected_swhid
            if v2_swhids and expected_swhid_sha256:
                all_match = all_match and (v2_swhids[0] == expected_swhid_sha256)
        
        return ComparisonResult(
            payload_name=payload_name,
            payload_path=payload_path,
            results=results,
            all_match=all_match,
            expected_swhid=expected_swhid,
            expected_swhid_sha256=expected_swhid_sha256
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
        
        if categories is None:
            categories = list(self.config["payloads"].keys())
        
        all_results = []
        
        for category in sorted(categories):  # Deterministic ordering
            if category not in self.config["payloads"]:
                logger.warning(f"Category '{category}' not found in config")
                continue
                
            logger.info(f"Testing category: {category}")
            
            # Sort payloads deterministically by name
            category_payloads = sorted(self.config["payloads"][category], key=lambda p: p.get("name", p.get("path", "")))
            
            # Filter by payload names if specified
            if payloads:
                category_payloads = [p for p in category_payloads if p.get("name") in payloads]
                if not category_payloads:
                    logger.info(f"No matching payloads found in category '{category}' for filter: {payloads}")
                    continue
            
            for payload in category_payloads:
                payload_path = payload["path"]
                # Resolve to absolute path relative to config file directory
                if not os.path.isabs(payload_path):
                    config_dir = os.path.dirname(os.path.abspath(self.config_path))
                    payload_path = os.path.join(config_dir, payload_path)
                payload_name = payload["name"]
                expected_swhid = payload.get("expected_swhid")
                expected_swhid_sha256 = payload.get("expected_swhid_sha256")
                
                # Determine which version(s) to test
                # Priority: CLI flags > payload rust_config > expected values presence
                rust_config = payload.get("rust_config", {})
                payload_version = rust_config.get("version")
                payload_hash = rust_config.get("hash")
                
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
                        self._create_minimal_git_repo(payload_path)
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
                        is_git_repo = os.path.exists(git_dir) or (
                            os.path.exists(os.path.join(payload_path, "HEAD")) and
                            os.path.exists(os.path.join(payload_path, "refs")) and
                            os.path.exists(os.path.join(payload_path, "objects"))
                        )
                    
                    if not is_git_repo:
                        try:
                            self._create_minimal_git_repo(payload_path)
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
                    expected_error = payload.get("expected_error")
                    expected_swhid_sha256 = payload.get("expected_swhid_sha256")
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
                discover_branches = payload.get("discover_branches", False)
                discover_tags = payload.get("discover_tags", False)
                
                if discover_branches or discover_tags:
                    # Generate test cases for discovered branches/tags
                    expected_config = payload.get("expected", {})
                    discovered_tests = self._discover_git_tests(payload_path, payload_name, 
                                                                 discover_branches, discover_tags, expected_config)
                    all_results.extend(discovered_tests)
                    continue
                
                # Get commit/tag metadata for revision/release tests
                commit = payload.get("commit")
                tag = payload.get("tag")
                
                # Run tests for all implementations and all versions
                results = {}
                with ThreadPoolExecutor(max_workers=self.config["settings"]["parallel_tests"]) as executor:
                    futures = []
                    for impl in self.implementations.values():
                        for test_version in test_versions:
                            # Determine hash algorithm for this version
                            version_hash = None
                            if test_version == 2:
                                version_hash = test_hash or "sha256"
                            
                            future = executor.submit(
                                self._run_single_test,
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
                expected_error = payload.get("expected_error")
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
        """Create a small git repository with one commit, one tag, and default HEAD.
        This is used to test snapshot identifiers.
        
        Uses fixed timestamps to ensure deterministic commit hashes across runs.
        All operations use fixed dates and explicit configurations for reproducibility.
        """
        import subprocess
        import pathlib
        import os
        path = pathlib.Path(repo_path)
        path.mkdir(parents=True, exist_ok=True)

        # Fixed timestamp for deterministic commits and tags
        # Use Unix timestamp format like Git's test suite (1112911993 = 2005-04-07)
        test_tick = 1112911993
        env = os.environ.copy()
        env["TZ"] = "UTC"

        # Initialize repo with explicit default branch name for consistency
        subprocess.run(["git", "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True)
        # Configure user (required for commits)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)
        # Disable GPG signing for commits and tags to ensure deterministic objects
        subprocess.run(["git", "config", "commit.gpgSign", "false"], cwd=repo_path, check=True)
        subprocess.run(["git", "config", "tag.gpgSign", "false"], cwd=repo_path, check=True)
        
        # Configure Git for cross-platform consistency (critical for Windows)
        # This ensures line endings, Unicode, and file modes are handled consistently
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "core.filemode", "true"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "config", "core.precomposeunicode", "false"], cwd=repo_path, check=True, capture_output=True)

        # Create a file and commit (first timestamp)
        # Write files in binary mode with explicit LF line endings and UTF-8 encoding
        # to ensure cross-platform consistency (pathlib.write_text() may use CRLF on Windows)
        env["GIT_AUTHOR_DATE"] = f"{test_tick} +0000"
        env["GIT_COMMITTER_DATE"] = f"{test_tick} +0000"
        with open(path / "README.md", "wb") as f:
            f.write("# Sample Repo\n".encode("utf-8"))
        subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=True,
                      capture_output=True, env=env)

        # Create a branch 'feature' and second commit (increment timestamp)
        test_tick += 60
        env["GIT_AUTHOR_DATE"] = f"{test_tick} +0000"
        env["GIT_COMMITTER_DATE"] = f"{test_tick} +0000"
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo_path, check=True, capture_output=True)
        with open(path / "FEATURE.txt", "wb") as f:
            f.write("feature\n".encode("utf-8"))
        subprocess.run(["git", "add", "FEATURE.txt"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add feature"], cwd=repo_path, check=True,
                      capture_output=True, env=env)

        # Switch back to main
        subprocess.run(["git", "checkout", "-B", "main"], cwd=repo_path, check=True, capture_output=True)

        # Create an annotated tag (increment timestamp)
        test_tick += 60
        env["GIT_AUTHOR_DATE"] = f"{test_tick} +0000"
        env["GIT_COMMITTER_DATE"] = f"{test_tick} +0000"
        subprocess.run(["git", "tag", "-a", "v1.0", "-m", "Release v1.0"], cwd=repo_path, check=True,
                      capture_output=True, env=env)
    
    def generate_expected_results(self, implementation: str = "python"):
        """Generate expected results using a reference implementation."""
        logger.info(f"Generating expected results using {implementation}")
        
        # Load the reference implementation
        impl = self.discovery.get_implementation(implementation)
        if not impl:
            logger.error(f"Reference implementation '{implementation}' not found")
            return
        
        for category, payloads in self.config["payloads"].items():
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
            yaml.dump(self.config, f, default_flow_style=False)
    
    def get_canonical_results(self, results: List[ComparisonResult], branch: str = "main", commit: str = "unknown") -> HarnessResults:
        """Generate canonical format results."""
        # Create run info
        now = datetime.utcnow()
        run_info = RunInfo(
            id=make_run_id(),
            created_at=now,
            branch=branch,
            commit=commit,
            runner=get_runner_info()
        )
        
        # Create implementation metadata
        implementations = []
        for impl_name, impl in self.implementations.items():
            impl_info = impl.get_info()
            capabilities = impl.get_capabilities()
            
            # Convert capabilities dataclass to Pydantic model
            capabilities_model = ImplementationCapabilitiesModel(
                supported_types=capabilities.supported_types,
                supported_qualifiers=capabilities.supported_qualifiers,
                api_version=capabilities.api_version,
                max_payload_size_mb=capabilities.max_payload_size_mb,
                supports_unicode=capabilities.supports_unicode,
                supports_percent_encoding=capabilities.supports_percent_encoding
            )
            
            # Try to get git SHA for implementation
            git_sha = self._get_implementation_git_sha(impl_name, impl_info)
            
            # Build toolchain info
            toolchain = {"python": platform.python_version()}
            if impl_info.language:
                toolchain["language"] = impl_info.language
            
            implementations.append(Implementation(
                id=impl_name,
                version=impl_info.version,
                git_sha=git_sha,
                git=git_sha,  # Legacy field
                language=impl_info.language,
                api_version=capabilities.api_version,
                capabilities=capabilities_model,
                toolchain=toolchain
            ))
        
        # Create test cases
        test_cases = []
        for result in results:
            # Determine category from payload path (distinguish basic vs edge_cases)
            category = "unknown"
            payload_path_normalized = result.payload_path.replace("\\", "/")
            if "/content/" in payload_path_normalized:
                category = "content/edge_cases" if "/edge_cases/" in payload_path_normalized else "content/basic"
            elif "/directory/" in payload_path_normalized:
                category = "directory/edge_cases" if "/edge_cases/" in payload_path_normalized else "directory/basic"
            elif "archive" in payload_path_normalized:
                category = "archive/basic"
            elif "git" in payload_path_normalized:
                category = "git/basic"
            elif "negative" in payload_path_normalized:
                category = "negative"
            
            # Create expected reference (include both v1 and v2 expected values)
            expected = ExpectedRef(
                reference_impl="python-swhid",  # Default reference
                swhid=result.expected_swhid,
                expected_swhid_sha256=result.expected_swhid_sha256
            )
            
            # Create results for each implementation
            test_results = []
            for impl_name, test_result in result.results.items():
                # Determine status
                if not test_result.success:
                    # Check if this is a SKIPPED case (missing payload or unsupported type)
                    error_str = str(test_result.error)
                    # Check for various "unsupported" error patterns
                    is_skipped = (
                        "Payload file not found" in error_str or 
                        "not supported by implementation" in error_str or
                        "Object type not supported" in error_str or
                        any(phrase in error_str.lower() for phrase in [
                            "doesn't support", "does not support", 
                            "not support", "unsupported"
                        ])
                    )
                    if is_skipped:
                        status = "SKIPPED"
                        if "file not found" in error_str.lower() or "Payload file not found" in error_str:
                            error = ErrorInfo(
                                code="IO_ERROR",
                                subtype="file_not_found",
                                message=error_str,
                                context={}
                            )
                        else:
                            error = ErrorInfo(
                                code="VALIDATION_ERROR",
                                subtype="unsupported_type",
                                message=error_str,
                                context={}
                            )
                        swhid = None
                    else:
                        status = "FAIL"
                        # Map exception to appropriate ErrorCode
                        error_code, error_subtype = self._classify_error(test_result.error)
                        error = ErrorInfo(
                            code=error_code,
                            subtype=error_subtype,
                            message=str(test_result.error),
                            context={}
                        )
                        swhid = None
                else:
                    # Determine which expected value to use based on result version
                    expected_swhid_to_check = None
                    if test_result.version == 2:
                        expected_swhid_to_check = result.expected_swhid_sha256
                    else:
                        expected_swhid_to_check = result.expected_swhid
                    
                    # Check against appropriate expected value
                    if expected_swhid_to_check and test_result.swhid != expected_swhid_to_check:
                        status = "FAIL"
                        # Create structured diff
                        diff = [
                            DiffEntry(
                                path="/swhid",
                                expected=expected_swhid_to_check,
                                actual=test_result.swhid,
                                category="value_mismatch"
                            )
                        ]
                        error = ErrorInfo(
                            code="MISMATCH_ERROR",
                            subtype="swhid",
                            message="SWHID mismatch",
                            context={
                                "got": test_result.swhid,
                                "expected": expected_swhid_to_check
                            },
                            diff=diff
                        )
                        swhid = test_result.swhid
                    else:
                        status = "PASS"
                        error = None
                        swhid = test_result.swhid
                
                # Create metrics
                metrics = Metrics(
                    samples=1,
                    wall_ms_median=round(test_result.duration * 1000, 3),
                    wall_ms_mad=0.0,
                    cpu_ms_median=round(test_result.duration * 1000, 3),
                    max_rss_kb=test_result.metrics.max_rss_kb if test_result.metrics else None
                )
                
                test_results.append(Result(
                    implementation=impl_name,
                    status=status,
                    error=error,
                    metrics=metrics,
                    swhid=swhid
                ))
            
            test_cases.append(TestCase(
                id=result.payload_name,
                category=category,
                payload_ref=result.payload_path,
                expected=expected,
                results=test_results
            ))
        
        # Calculate aggregates
        aggregates_data = {}
        for impl_name in self.implementations.keys():
            passed = sum(
                1 for tc in test_cases for r in tc.results 
                if r.implementation == impl_name and r.status == "PASS"
            )
            failed = sum(
                1 for tc in test_cases for r in tc.results 
                if r.implementation == impl_name and r.status == "FAIL"
            )
            skipped = sum(
                1 for tc in test_cases for r in tc.results 
                if r.implementation == impl_name and r.status == "SKIPPED"
            )
            aggregates_data[impl_name] = {
                "passed": passed,
                "failed": failed,
                "skipped": skipped
            }
        
        aggregates = Aggregates(by_implementation=aggregates_data)
        
        return HarnessResults(
            schema_version="1.0.0",
            schema_extensions=[],  # No experimental fields yet
            run=run_info,
            run_environment=run_info.runner,  # Also include at top level for compatibility
            implementations=implementations,
            tests=test_cases,
            aggregates=aggregates
        )
    
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
    
    def _classify_error(self, error: str) -> tuple[str, str]:
        """
        Classify error string into ErrorCode and subtype.
        
        Returns:
            Tuple of (error_code, subtype)
        """
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
        for category, payloads in sorted(harness.config["payloads"].items()):
            print(f"\n  {category}:")
            for payload in sorted(payloads, key=lambda p: p.get("name", "")):
                name = payload.get("name", "unnamed")
                path = payload.get("path", "")
                expected = payload.get("expected_swhid")
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
        
        if args.summary_only:
            harness._print_summary(canonical_results)
        elif args.dashboard_output:
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
            
            # Always show summary when saving to file
            harness._print_summary(canonical_results)
        else:
            if args.output_format == "ndjson":
                # Print NDJSON to stdout
                print(json.dumps({"type": "run_info", **canonical_results.run.model_dump(mode="json")}))
                for impl in canonical_results.implementations:
                    print(json.dumps({"type": "implementation", **impl.model_dump(mode="json")}))
                for test in canonical_results.tests:
                    print(json.dumps({"type": "test_case", **test.model_dump(mode="json")}))
                print(json.dumps({"type": "aggregates", **canonical_results.aggregates.model_dump(mode="json")}))
            else:
                print(json.dumps(canonical_results.model_dump(mode="json"), indent=2))
        
        # Exit code: 0=all pass, 1=mismatch, 2=error
        failed = sum(1 for r in results if not r.all_match)
        if failed > 0:
            sys.exit(1)  # Mismatch
        sys.exit(0)  # All pass

if __name__ == "__main__":
    main()
