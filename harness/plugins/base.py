"""
Base classes and interfaces for SWHID implementations.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class ErrorCode(Enum):
    """Error codes for SWHID implementation failures."""
    PARSE_ERROR = "PARSE_ERROR"                    # Bad syntax (scheme, version, type, hash, qualifiers)
    NORMALIZE_ERROR = "NORMALIZE_ERROR"            # Valid parse but canonicalization fails
    VALIDATION_ERROR = "VALIDATION_ERROR"          # Semantically invalid but well-formed
    COMPUTE_ERROR = "COMPUTE_ERROR"                # Failure computing SWHID from payload
    MISMATCH_ERROR = "MISMATCH_ERROR"              # Value differs from reference implementation
    TIMEOUT = "TIMEOUT"                            # Exceeded wall clock budget
    RESOURCE_LIMIT = "RESOURCE_LIMIT"              # Memory/CPU cap exceeded
    IO_ERROR = "IO_ERROR"                          # Plugin crashed / bad exit / protocol violation

@dataclass
class ErrorContext:
    """Structured error context for debugging."""
    code: ErrorCode
    subtype: str  # e.g., "hash_length", "unknown_qualifier", "qualifier_order"
    message: str
    context: Optional[Dict[str, Any]] = None  # Additional structured data
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "code": self.code.value,
            "subtype": self.subtype,
            "message": self.message,
            "context": self.context or {}
        }

@dataclass
class ImplementationInfo:
    """Metadata about a SWHID implementation."""
    name: str
    version: str
    language: str
    description: str = ""
    git_repo: Optional[str] = None
    git_commit: Optional[str] = None
    git_branch: Optional[str] = None
    build_command: Optional[str] = None
    test_command: Optional[str] = None
    dependencies: List[str] = None
    
    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []

@dataclass
class TestMetrics:
    """Performance metrics for a test run."""
    samples: int = 1
    wall_ms_median: float = 0.0
    wall_ms_mad: float = 0.0  # Median Absolute Deviation
    cpu_ms_median: float = 0.0
    cpu_ms_mad: float = 0.0
    max_rss_kb: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "samples": self.samples,
            "wall_ms_median": self.wall_ms_median,
            "wall_ms_mad": self.wall_ms_mad,
            "cpu_ms_median": self.cpu_ms_median,
            "cpu_ms_mad": self.cpu_ms_mad,
            "max_rss_kb": self.max_rss_kb,
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out
        }

@dataclass
class SwhidTestResult:
    """Represents the result of a single test."""
    payload_name: str
    payload_path: str
    implementation: str
    swhid: Optional[str]
    error: Optional[Union[str, ErrorContext]]
    duration: float
    success: bool
    metrics: Optional[TestMetrics] = None
    timestamp: datetime = None
    version: int = 1  # SWHID version (1 for v1, 2 for v2)
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
    
    def get_error_dict(self) -> Optional[Dict[str, Any]]:
        """Get error as dictionary for JSON serialization."""
        if self.error is None:
            return None
        if isinstance(self.error, ErrorContext):
            return self.error.to_dict()
        return {"code": "UNKNOWN_ERROR", "subtype": "generic", "message": str(self.error)}

@dataclass
class ComparisonResult:
    """Represents the comparison of results across implementations."""
    payload_name: str
    payload_path: str
    results: Dict[str, SwhidTestResult]
    all_match: bool
    expected_swhid: Optional[str]
    expected_swhid_sha256: Optional[str] = None  # Expected SWHID for v2 SHA256
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
    

@dataclass
class BenchmarkResult:
    """Represents benchmark results for an implementation."""
    implementation: str
    payload_name: str
    mean_duration_ms: float
    median_duration_ms: float
    std_duration_ms: float
    min_duration_ms: float
    max_duration_ms: float
    iterations: int
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

@dataclass
class ImplementationCapabilities:
    """Capabilities declared by an implementation."""
    supported_types: List[str]  # e.g., ["cnt", "dir", "rev", "rel", "snp"]
    supported_qualifiers: List[str]  # e.g., ["origin", "visit", "anchor", "path", "lines"]
    api_version: str = "1.0"
    max_payload_size_mb: int = 100
    supports_unicode: bool = True
    supports_percent_encoding: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "supported_types": self.supported_types,
            "supported_qualifiers": self.supported_qualifiers,
            "api_version": self.api_version,
            "max_payload_size_mb": self.max_payload_size_mb,
            "supports_unicode": self.supports_unicode,
            "supports_percent_encoding": self.supports_percent_encoding
        }

class SwhidImplementation(ABC):
    """Base class for SWHID implementations."""
    
    @abstractmethod
    def get_info(self) -> ImplementationInfo:
        """Return implementation metadata."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if implementation is available."""
        pass
    
    @abstractmethod
    def get_capabilities(self) -> ImplementationCapabilities:
        """Return implementation capabilities."""
        pass
    
    def compute_swhid(self, payload_path: str, obj_type: Optional[str] = None,
                     commit: Optional[str] = None, tag: Optional[str] = None,
                     version: Optional[int] = None, hash_algo: Optional[str] = None) -> str:
        """Compute SWHID for given payload.
        
        Args:
            payload_path: Path to the payload (file, directory, or Git repository)
            obj_type: Object type (content, directory, revision, release, snapshot)
            commit: Optional commit SHA for revision SWHIDs (defaults to HEAD)
            tag: Optional tag name for release SWHIDs (required for releases)
        """
        # Default implementation - subclasses should override
        raise NotImplementedError("Subclasses must implement compute_swhid")
    
    def benchmark(self, payload_path: str, iterations: int = 100) -> BenchmarkResult:
        """Run performance benchmarks (default implementation)."""
        import time
        import statistics
        
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            try:
                self.compute_swhid(payload_path)
                times.append(time.perf_counter() - start)
            except Exception as e:
                logger.warning(f"Benchmark iteration failed: {e}")
                continue
        
        if not times:
            raise RuntimeError("All benchmark iterations failed")
        
        # Convert to milliseconds
        times_ms = [t * 1000 for t in times]
        
        return BenchmarkResult(
            implementation=self.get_info().name,
            payload_name=payload_path,
            mean_duration_ms=statistics.mean(times_ms),
            median_duration_ms=statistics.median(times_ms),
            std_duration_ms=statistics.stdev(times_ms) if len(times_ms) > 1 else 0,
            min_duration_ms=min(times_ms),
            max_duration_ms=max(times_ms),
            iterations=len(times_ms)
        )
    
    def detect_object_type(self, payload_path: str) -> str:
        """Detect object type from payload path (default implementation)."""
        import os
        from pathlib import Path
        
        path = Path(payload_path)
        
        if not path.exists():
            raise ValueError(f"Payload does not exist: {payload_path}")
        
        if path.is_file():
            return "content"
        elif path.is_dir():
            # Check if it's a Git repository
            # Case 1: Regular Git repo (has .git subdirectory)
            git_dir = path / ".git"
            if git_dir.exists():
                # .git can be a directory or a file (for worktrees/submodules)
                if git_dir.is_dir() or git_dir.is_file():
                    return "snapshot"
            
            # Case 2: Bare Git repository (directory itself is the git repo)
            # Check for common git repository indicators
            if (path / "HEAD").exists() and \
               (path / "refs").exists() and \
               (path / "objects").exists():
                return "snapshot"
            
            return "directory"
        else:
            raise ValueError(f"Payload is neither file nor directory: {payload_path}")
    
    def __str__(self) -> str:
        info = self.get_info()
        return f"{info.name} v{info.version} ({info.language})"
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self}>"
