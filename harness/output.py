"""
Output generation for the SWHID Testing Harness.

This module handles result serialization, formatting, and summary generation.
"""

import platform
from typing import List, Dict, Callable, Tuple, Optional
from datetime import datetime

from .plugins.base import SwhidImplementation, ImplementationInfo, SwhidTestResult
from .models import (
    HarnessResults, RunInfo, RunnerInfo, Implementation, TestCase,
    ExpectedRef, Result, Metrics, ErrorInfo, Aggregates,
    make_run_id, get_runner_info, ImplementationCapabilitiesModel, DiffEntry
)
from .plugins.base import ComparisonResult
import logging

logger = logging.getLogger(__name__)


class OutputGenerator:
    """Generates output formats from test results."""
    
    def __init__(
        self,
        implementations: Dict[str, SwhidImplementation],
        get_impl_git_sha_func: Callable[[str, ImplementationInfo], Optional[str]]
    ) -> None:
        """
        Initialize output generator.
        
        Args:
            implementations: Dictionary of implementations
            get_impl_git_sha_func: Function to get Git SHA for an implementation
        """
        self.implementations = implementations
        self._get_implementation_git_sha = get_impl_git_sha_func
    
    def get_canonical_results(
        self,
        results: List[ComparisonResult],
        branch: str = "main",
        commit: str = "unknown"
    ) -> HarnessResults:
        """
        Generate canonical format results.
        
        Args:
            results: List of comparison results
            branch: Git branch name
            commit: Git commit hash
            
        Returns:
            HarnessResults in canonical format
        """
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
        test_cases = self._create_test_cases(results)
        
        # Calculate aggregates
        aggregates = self._calculate_aggregates(test_cases)
        
        return HarnessResults(
            schema_version="1.0.0",
            schema_extensions=[],
            run=run_info,
            run_environment=run_info.runner,
            implementations=implementations,
            tests=test_cases,
            aggregates=aggregates
        )
    
    def _create_test_cases(self, results: List[ComparisonResult]) -> List[TestCase]:
        """Create test cases from comparison results."""
        test_cases = []
        for result in results:
            # Determine category from payload path
            category = self._determine_category(result.payload_path)
            
            # Create expected reference
            expected = ExpectedRef(
                reference_impl="python-swhid",
                swhid=result.expected_swhid,
                expected_swhid_sha256=result.expected_swhid_sha256
            )
            
            # Create results for each implementation
            test_results = []
            for impl_name, test_result in result.results.items():
                status, error, swhid = self._determine_status(test_result, result)
                
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
        
        return test_cases
    
    def _determine_category(self, payload_path: str) -> str:
        """Determine test category from payload path."""
        payload_path_normalized = payload_path.replace("\\", "/")
        if "/content/" in payload_path_normalized:
            return "content/edge_cases" if "/edge_cases/" in payload_path_normalized else "content/basic"
        elif "/directory/" in payload_path_normalized:
            return "directory/edge_cases" if "/edge_cases/" in payload_path_normalized else "directory/basic"
        elif "archive" in payload_path_normalized:
            return "archive/basic"
        elif "git" in payload_path_normalized:
            return "git/basic"
        elif "negative" in payload_path_normalized:
            return "negative"
        return "unknown"
    
    def _determine_status(
        self,
        test_result: SwhidTestResult,
        comparison_result: ComparisonResult
    ) -> Tuple[str, Optional[ErrorInfo], Optional[str]]:
        """Determine status, error, and swhid for a test result."""
        from .harness import SwhidHarness  # Import here to avoid circular dependency
        
        if not test_result.success:
            # Check if this is a SKIPPED case
            error_str = str(test_result.error)
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
                return status, error, None
            else:
                status = "FAIL"
                # Use harness's error classification (will be refactored later)
                # For now, create a temporary harness instance just for classification
                # This is a temporary workaround until error classification is extracted
                error_code, error_subtype = self._classify_error_string(error_str)
                error = ErrorInfo(
                    code=error_code,
                    subtype=error_subtype,
                    message=error_str,
                    context={}
                )
                return status, error, None
        else:
            # Determine which expected value to use based on result version
            expected_swhid_to_check = None
            if test_result.version == 2:
                expected_swhid_to_check = comparison_result.expected_swhid_sha256
            else:
                expected_swhid_to_check = comparison_result.expected_swhid
            
            # Check against appropriate expected value
            if expected_swhid_to_check and test_result.swhid != expected_swhid_to_check:
                status = "FAIL"
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
                return status, error, test_result.swhid
            else:
                status = "PASS"
                return status, None, test_result.swhid
    
    def _classify_error_string(self, error_str: str) -> Tuple[str, str]:
        """Classify error string into error code and subtype."""
        error_lower = error_str.lower()
        
        # Timeout errors
        if "timeout" in error_lower or "timed out" in error_lower:
            return ("TIMEOUT", "wall_clock")
        
        # Resource limit errors
        if "rss limit" in error_lower or "memory" in error_lower or "resource" in error_lower:
            return ("RESOURCE_LIMIT", "memory")
        if "cpu" in error_lower and "limit" in error_lower:
            return ("RESOURCE_LIMIT", "cpu")
        
        # I/O errors
        if "file not found" in error_lower or "no such file" in error_lower:
            return ("IO_ERROR", "file_not_found")
        if "permission denied" in error_lower or "permission" in error_lower:
            return ("IO_ERROR", "permission_denied")
        if "json" in error_lower and ("decode" in error_lower or "invalid" in error_lower):
            return ("IO_ERROR", "protocol_violation")
        if "process" in error_lower and ("failed" in error_lower or "crashed" in error_lower):
            return ("IO_ERROR", "process_crash")
        
        # Parse errors
        if "invalid swhid" in error_lower or "invalid format" in error_lower:
            return ("PARSE_ERROR", "format")
        if "invalid" in error_lower and ("scheme" in error_lower or "version" in error_lower):
            return ("PARSE_ERROR", "syntax")
        
        # Validation errors
        if "hash" in error_lower and "match" in error_lower:
            return ("VALIDATION_ERROR", "hash_mismatch")
        if "semantic" in error_lower or "semantically invalid" in error_lower:
            return ("VALIDATION_ERROR", "semantic")
        
        # Mismatch errors
        if "mismatch" in error_lower:
            return ("MISMATCH_ERROR", "value")
        
        # Default: COMPUTE_ERROR
        return ("COMPUTE_ERROR", "exception")
    
    def _calculate_aggregates(self, test_cases: List[TestCase]) -> Aggregates:
        """Calculate aggregate statistics."""
        aggregates_data = {}
        for impl in self.implementations.keys():
            passed = sum(
                1 for tc in test_cases for r in tc.results 
                if r.implementation == impl and r.status == "PASS"
            )
            failed = sum(
                1 for tc in test_cases for r in tc.results 
                if r.implementation == impl and r.status == "FAIL"
            )
            skipped = sum(
                1 for tc in test_cases for r in tc.results 
                if r.implementation == impl and r.status == "SKIPPED"
            )
            aggregates_data[impl] = {
                "passed": passed,
                "failed": failed,
                "skipped": skipped
            }
        
        return Aggregates(by_implementation=aggregates_data)
    
    def print_summary(self, canonical_results: HarnessResults) -> None:
        """Print summary of test results."""
        # This is a simplified version - full implementation would be in harness
        # For now, delegate to the existing method in harness
        total_tests = len(canonical_results.tests)
        total_passed = sum(
            1 for tc in canonical_results.tests for r in tc.results if r.status == "PASS"
        )
        total_failed = sum(
            1 for tc in canonical_results.tests for r in tc.results if r.status == "FAIL"
        )
        total_skipped = sum(
            1 for tc in canonical_results.tests for r in tc.results if r.status == "SKIPPED"
        )
        
        print("\n" + "=" * 50)
        print("SWHID Testing Harness Summary")
        print("=" * 50)
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {total_passed}")
        print(f"Failed: {total_failed}")
        print(f"Skipped: {total_skipped}")
        if total_tests > 0:
            print(f"Success Rate: {total_passed/total_tests*100:.1f}%")
        print("=" * 50)

