"""
Pydantic models for canonical SWHID Testing Harness results schema.

This module provides type-safe models for generating and validating
the canonical JSON format used by the dashboard and other tools.
"""

from __future__ import annotations
from typing import Optional, List, Dict, Literal, Any
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime

SchemaVersion = Literal["1.0.0"]
Status = Literal["PASS", "FAIL", "SKIPPED"]


class Metrics(BaseModel):
    """Normalized performance metrics, always in milliseconds."""
    samples: int = 1
    wall_ms_median: float
    wall_ms_mad: float
    cpu_ms_median: float
    max_rss_kb: Optional[int] = None


class DiffEntry(BaseModel):
    """Single diff entry with JSON Pointer path."""
    path: str  # JSON Pointer path (e.g., "/qualifiers/path")
    expected: Optional[Any] = None
    actual: Optional[Any] = None
    category: Literal["value_mismatch", "missing_field", "ordering", "normalization"] = "value_mismatch"


class ErrorInfo(BaseModel):
    """Structured error metadata for failed tests."""
    code: Literal[
        "PARSE_ERROR",
        "NORMALIZE_ERROR", 
        "VALIDATION_ERROR",
        "COMPUTE_ERROR",
        "MISMATCH_ERROR",
        "TIMEOUT",
        "RESOURCE_LIMIT",
        "IO_ERROR",
    ]
    subtype: Optional[str] = None
    message: str
    context: Dict[str, Any] = Field(default_factory=dict)
    diff: Optional[List[DiffEntry]] = None  # Structured diff for mismatches


class Result(BaseModel):
    """Outcome of a single test for a given implementation."""
    implementation: str
    status: Status
    error: Optional[ErrorInfo] = None
    metrics: Metrics
    swhid: Optional[str] = None


class ExpectedRef(BaseModel):
    """Reference SWHID used for validation."""
    reference_impl: Optional[str] = None
    swhid: Optional[str] = None


class TestCase(BaseModel):
    """Single test case and its results across all implementations."""
    id: str
    category: str
    payload_ref: Optional[str] = None
    expected: ExpectedRef
    results: List[Result]


class ImplementationCapabilitiesModel(BaseModel):
    """Capabilities declared by an implementation (structured)."""
    supported_types: List[str]
    supported_qualifiers: List[str]
    api_version: str
    max_payload_size_mb: int
    supports_unicode: bool
    supports_percent_encoding: bool


class Implementation(BaseModel):
    """Metadata for each implementation tested."""
    id: str
    version: str
    git_sha: Optional[str] = None  # Git commit SHA
    git: Optional[str] = None  # Legacy field, use git_sha
    language: Optional[str] = None
    api_version: str
    capabilities: ImplementationCapabilitiesModel
    toolchain: Dict[str, str] = Field(default_factory=dict)
    
    model_config = ConfigDict(extra="allow")  # Allow extra fields for forward compatibility


class RunnerInfo(BaseModel):
    """Machine and environment info for reproducibility."""
    os: str
    kernel: Optional[str] = None
    cpu: str
    python: str
    container_image: Optional[str] = None
    
    model_config = ConfigDict(extra="allow")  # Allow extra fields for forward compatibility


class RunInfo(BaseModel):
    """Information about this particular harness execution."""
    id: str
    created_at: datetime
    branch: str
    commit: str
    runner: RunnerInfo


class Aggregates(BaseModel):
    """Aggregated pass/fail counts per implementation."""
    by_implementation: Dict[str, Dict[str, int]]


class HarnessResults(BaseModel):
    """Canonical schema for the SWHID Testing Harness results."""
    schema_version: SchemaVersion = "1.0.0"
    schema_extensions: List[str] = Field(default_factory=list)  # Experimental fields
    run: RunInfo
    run_environment: Optional[RunnerInfo] = None  # Alias for run.runner, kept for compatibility
    implementations: List[Implementation]
    tests: List[TestCase]
    aggregates: Aggregates
    
    model_config = ConfigDict(extra="allow")  # Allow extra fields for forward compatibility

    def pass_rate(self) -> float:
        """Calculate overall pass rate percentage."""
        total = sum(len(t.results) for t in self.tests) or 1
        passed = sum(
            1 for t in self.tests for r in t.results if r.status == "PASS"
        )
        return round(passed / total * 100.0, 2)

    def get_implementation_stats(self) -> Dict[str, Dict[str, int]]:
        """Get statistics for each implementation."""
        stats = {}
        for impl in self.implementations:
            impl_id = impl.id
            passed = sum(
                1 for t in self.tests for r in t.results 
                if r.implementation == impl_id and r.status == "PASS"
            )
            failed = sum(
                1 for t in self.tests for r in t.results 
                if r.implementation == impl_id and r.status == "FAIL"
            )
            skipped = sum(
                1 for t in self.tests for r in t.results 
                if r.implementation == impl_id and r.status == "SKIPPED"
            )
            stats[impl_id] = {
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "total": passed + failed + skipped
            }
        return stats


def make_run_id() -> str:
    """Generate a unique run ID with timestamp and short hash."""
    import hashlib
    now = datetime.utcnow()
    timestamp = now.strftime("%Y-%m-%dT%H-%M-%SZ")
    hash_suffix = hashlib.sha1(timestamp.encode()).hexdigest()[:6]
    return f"{timestamp}_{hash_suffix}"

def format_rfc3339(dt: datetime) -> str:
    """Format datetime as RFC3339 without fractional seconds."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_runner_info() -> RunnerInfo:
    """Get current runner information."""
    import platform
    import os
    
    # Get kernel version if available
    kernel = None
    try:
        if platform.system() == "Linux":
            import subprocess
            result = subprocess.run(
                ["uname", "-r"], capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                kernel = result.stdout.strip()
    except Exception:
        pass
    
    # Check for container
    container_image = None
    if os.path.exists("/.dockerenv"):
        container_image = "docker"
    elif os.path.exists("/run/.containerenv"):
        container_image = "podman"
    
    return RunnerInfo(
        os=platform.platform(),
        kernel=kernel,
        cpu=platform.processor() or "Unknown",
        python=platform.python_version(),
        container_image=container_image
    )


if __name__ == "__main__":
    """CLI validation tool."""
    import sys
    import json
    
    if len(sys.argv) != 2:
        print("Usage: python3 -m harness.models <results.json>")
        sys.exit(1)
    
    try:
        with open(sys.argv[1], 'r') as f:
            data = json.load(f)
        results = HarnessResults.model_validate(data)
        print(f"✅ Schema validated successfully. Pass rate: {results.pass_rate()}%")
    except Exception as e:
        print(f"❌ Validation failed: {e}")
        sys.exit(1)
