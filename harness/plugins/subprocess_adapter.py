"""
Subprocess adapter for safe plugin execution.

This module provides a subprocess-based execution adapter that runs plugins
out-of-process with resource limits and timeouts for security and stability.
"""

import json
import subprocess
import tempfile
import os
import signal
import psutil
import time
import resource
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
import logging

from .base import SwhidImplementation, ImplementationInfo, ImplementationCapabilities, SwhidTestResult, TestMetrics
from ..utils.subprocess_utils import prepare_subprocess_environment, set_resource_limits, run_with_timeout

logger = logging.getLogger(__name__)

# Path to the wrapper script
_WRAPPER_SCRIPT = Path(__file__).parent / "run_impl.py"


class SubprocessAdapter(SwhidImplementation):
    """
    Adapter that runs implementations in subprocess with safety limits.
    
    This provides isolation, resource limits, and timeout protection.
    Uses JSON protocol over stdin/stdout to communicate with subprocess.
    """
    
    def __init__(
        self,
        wrapped_impl: SwhidImplementation,
        timeout: int = 30,
        max_rss_mb: int = 500,
        max_cpu_time: int = 60,
        clean_env: bool = True,
        use_subprocess: bool = True
    ):
        """
        Initialize subprocess adapter.
        
        Args:
            wrapped_impl: The implementation to wrap
            timeout: Maximum wall-clock time in seconds
            max_rss_mb: Maximum resident set size in MB
            max_cpu_time: Maximum CPU time in seconds
            clean_env: Use clean environment (whitelist PATH only)
            use_subprocess: If True, run in subprocess; if False, monitor in-process
        """
        self.wrapped_impl = wrapped_impl
        self.timeout = timeout
        self.max_rss_mb = max_rss_mb
        self.max_cpu_time = max_cpu_time
        self.clean_env = clean_env
        self.use_subprocess = use_subprocess
        
        # Get implementation module path for subprocess execution
        impl_module = wrapped_impl.__class__.__module__
        impl_class = wrapped_impl.__class__.__name__
        self.impl_module_path = impl_module
        self.impl_class_name = impl_class
    
    def get_info(self) -> ImplementationInfo:
        """Return implementation metadata."""
        return self.wrapped_impl.get_info()
    
    def is_available(self) -> bool:
        """Check if implementation is available."""
        return self.wrapped_impl.is_available()
    
    def get_capabilities(self) -> ImplementationCapabilities:
        """Return implementation capabilities."""
        return self.wrapped_impl.get_capabilities()
    
    def compute_swhid(self, payload_path: str, obj_type: Optional[str] = None) -> str:
        """
        Compute SWHID via subprocess with safety limits.
        
        This runs the implementation in a subprocess with:
        - Timeout protection
        - RSS limit monitoring
        - CPU time tracking
        - Clean environment
        """
        if self.use_subprocess:
            return self._compute_via_subprocess(payload_path, obj_type)
        else:
            return self._compute_with_monitoring(payload_path, obj_type)
    
    def _compute_via_subprocess(self, payload_path: str, obj_type: Optional[str] = None) -> str:
        """Compute SWHID by running implementation in subprocess with JSON protocol."""
        # Prepare request
        request = {
            "op": "compute",
            "payload_path": os.path.abspath(payload_path),
            "obj_type": obj_type,
            "impl_module": self.impl_module_path,
            "impl_class": self.impl_class_name
        }
        
        # Prepare environment
        env = self._prepare_environment()
        
        # Create isolated working directory
        work_dir = tempfile.mkdtemp(prefix="swhid_impl_")
        
        try:
            # Build command
            python = shutil.which("python3") or shutil.which("python")
            if not python:
                raise RuntimeError("Python interpreter not found")
            
            cmd = [python, str(_WRAPPER_SCRIPT)]
            
            # Start process with resource limits
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',  # Replace invalid UTF-8 sequences instead of raising UnicodeDecodeError
                env=env,
                cwd=work_dir,
                preexec_fn=self._set_resource_limits if os.name != 'nt' else None
            )
            
            # Monitor process for RSS
            proc_monitor = psutil.Process(process.pid)
            max_rss_kb = 0
            
            # Send request
            request_json = json.dumps(request)
            start_time = time.time()
            
            try:
                stdout, stderr = process.communicate(
                    input=request_json,
                    timeout=self.timeout
                )
                
                # Get final RSS
                try:
                    max_rss_kb = int(proc_monitor.memory_info().rss / 1024)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                
            except subprocess.TimeoutExpired:
                # Kill process and all children
                try:
                    proc_monitor.terminate()
                    proc_monitor.wait(timeout=5)
                except psutil.TimeoutExpired:
                    proc_monitor.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                
                raise RuntimeError(f"Implementation timed out after {self.timeout}s")
            
            # Check RSS limit
            if max_rss_kb > self.max_rss_mb * 1024:
                raise RuntimeError(
                    f"RSS limit exceeded: {max_rss_kb}KB > {self.max_rss_mb * 1024}KB"
                )
            
            # Check exit code
            if process.returncode != 0:
                error_msg = stderr.strip() or stdout.strip() or "Unknown error"
                raise RuntimeError(f"Implementation failed (exit {process.returncode}): {error_msg}")
            
            # Parse response
            try:
                response = json.loads(stdout)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON response: {e}\nOutput: {stdout[:200]}")
            
            if not response.get("ok"):
                error = response.get("error", {})
                error_msg = error.get("message", "Unknown error")
                error_code = error.get("code", "UNKNOWN")
                raise RuntimeError(f"Implementation error [{error_code}]: {error_msg}")
            
            swhid = response.get("swhid")
            if not swhid:
                raise RuntimeError("No SWHID in response")
            
            return swhid
            
        finally:
            # Cleanup
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass
    
    def _compute_with_monitoring(self, payload_path: str, obj_type: Optional[str] = None) -> str:
        """Compute SWHID with in-process monitoring (fallback)."""
        # Set resource limits
        try:
            max_rss_bytes = self.max_rss_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (max_rss_bytes, max_rss_bytes))
        except (ValueError, OSError) as e:
            logger.warning(f"Could not set RSS limit: {e}")
        
        # Monitor process
        process = psutil.Process()
        start_rss = process.memory_info().rss / 1024  # KB
        start_cpu = process.cpu_times().user + process.cpu_times().system
        
        start_time = time.time()
        
        try:
            # Run with timeout
            result = self._run_with_timeout(
                lambda: self.wrapped_impl.compute_swhid(payload_path, obj_type),
                self.timeout
            )
            
            # Get final metrics
            end_time = time.time()
            end_rss = process.memory_info().rss / 1024  # KB
            end_cpu = process.cpu_times().user + process.cpu_times().system
            
            wall_ms = (end_time - start_time) * 1000
            cpu_ms = (end_cpu - start_cpu) * 1000
            max_rss_kb = int(max(start_rss, end_rss))
            
            # Check limits
            if max_rss_kb > self.max_rss_mb * 1024:
                raise RuntimeError(f"RSS limit exceeded: {max_rss_kb}KB > {self.max_rss_mb * 1024}KB")
            
            if cpu_ms > self.max_cpu_time * 1000:
                raise RuntimeError(f"CPU time limit exceeded: {cpu_ms}ms > {self.max_cpu_time * 1000}ms")
            
            return result
            
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Implementation timed out after {self.timeout}s")
        except Exception as e:
            raise RuntimeError(f"Subprocess execution failed: {e}")
    
    def _prepare_environment(self) -> Dict[str, str]:
        """Prepare clean environment for subprocess."""
        return prepare_subprocess_environment(
            clean_env=self.clean_env,
            project_root=str(Path(__file__).parent.parent.parent.absolute())
        )
    
    def _set_resource_limits(self):
        """Set resource limits for subprocess (Unix only)."""
        set_resource_limits(self.max_rss_mb, self.max_cpu_time)
    
    def _run_with_timeout(self, func, timeout: float):
        """Run a function with timeout using signal (Unix only)."""
        return run_with_timeout(func, timeout)
    
    def detect_object_type(self, payload_path: str) -> str:
        """Delegate to wrapped implementation."""
        return self.wrapped_impl.detect_object_type(payload_path)


class JSONProtocolAdapter(SwhidImplementation):
    """
    Adapter for implementations using JSON stdin/stdout protocol.
    
    Protocol:
    - Request: {"op": "compute", "category": "content", "payload_path": "..."}
    - Response: {"ok": true, "swhid": "...", "metrics": {...}} or {"ok": false, "error": {...}}
    """
    
    def __init__(
        self,
        command: List[str],
        timeout: int = 30,
        max_rss_mb: int = 500,
        max_cpu_time: int = 60,
        clean_env: bool = True
    ):
        """
        Initialize JSON protocol adapter.
        
        Args:
            command: Command to run (e.g., ["python", "my_impl.py"])
            timeout: Maximum execution time
            max_rss_mb: Maximum RSS limit
            max_cpu_time: Maximum CPU time in seconds
            clean_env: Use clean environment
        """
        self.command = command
        self.timeout = timeout
        self.max_rss_mb = max_rss_mb
        self.max_cpu_time = max_cpu_time
        self.clean_env = clean_env
    
    def get_info(self) -> ImplementationInfo:
        """Return implementation metadata."""
        # Would need to query implementation via protocol
        return ImplementationInfo(
            name="json-protocol",
            version="1.0.0",
            language="unknown",
            description="JSON protocol implementation",
            dependencies=[]
        )
    
    def is_available(self) -> bool:
        """Check if command is available."""
        try:
            result = subprocess.run(
                self.command[:1] + ["--version"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def get_capabilities(self) -> ImplementationCapabilities:
        """Return default capabilities."""
        return ImplementationCapabilities(
            supported_types=["cnt", "dir", "rev", "rel", "snp"],
            supported_qualifiers=["origin", "visit", "anchor", "path", "lines"],
            api_version="1.0"
        )
    
    def compute_swhid(self, payload_path: str, obj_type: Optional[str] = None) -> str:
        """Compute SWHID via JSON protocol."""
        request = {
            "op": "compute",
            "payload_path": os.path.abspath(payload_path),
            "obj_type": obj_type
        }
        
        # Prepare environment
        env = self._prepare_environment()
        
        # Create isolated working directory
        work_dir = tempfile.mkdtemp(prefix="swhid_impl_")
        
        try:
            # Start process with resource limits
            process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                env=env,
                cwd=work_dir,
                preexec_fn=self._set_resource_limits if os.name != 'nt' else None
            )
            
            # Monitor process for RSS
            proc_monitor = psutil.Process(process.pid)
            max_rss_kb = 0
            
            # Send request
            request_json = json.dumps(request)
            
            try:
                stdout, stderr = process.communicate(
                    input=request_json,
                    timeout=self.timeout
                )
                
                # Get final RSS
                try:
                    max_rss_kb = int(proc_monitor.memory_info().rss / 1024)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                
            except subprocess.TimeoutExpired:
                # Kill process and all children
                try:
                    proc_monitor.terminate()
                    proc_monitor.wait(timeout=5)
                except psutil.TimeoutExpired:
                    proc_monitor.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                
                raise RuntimeError(f"Implementation timed out after {self.timeout}s")
            
            # Check RSS limit
            if max_rss_kb > self.max_rss_mb * 1024:
                raise RuntimeError(
                    f"RSS limit exceeded: {max_rss_kb}KB > {self.max_rss_mb * 1024}KB"
                )
            
            if process.returncode != 0:
                error_msg = stderr.strip() or stdout.strip() or "Unknown error"
                raise RuntimeError(f"Process failed (exit {process.returncode}): {error_msg}")
            
            # Parse response
            try:
                response = json.loads(stdout)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON response: {e}\nOutput: {stdout[:200]}")
            
            if not response.get("ok"):
                error = response.get("error", {})
                error_msg = error.get("message", "Unknown error")
                error_code = error.get("code", "UNKNOWN")
                raise RuntimeError(f"Implementation error [{error_code}]: {error_msg}")
            
            swhid = response.get("swhid")
            if not swhid:
                raise RuntimeError("No SWHID in response")
            
            return swhid
            
        finally:
            # Cleanup
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass
    
    def _prepare_environment(self) -> Dict[str, str]:
        """Prepare clean environment for subprocess."""
        return prepare_subprocess_environment(
            clean_env=self.clean_env,
            project_root=str(Path(__file__).parent.parent.parent.absolute())
        )
    
    def _set_resource_limits(self):
        """Set resource limits for subprocess (Unix only)."""
        max_cpu_time = self.max_cpu_time if hasattr(self, 'max_cpu_time') else 60
        set_resource_limits(self.max_rss_mb, max_cpu_time)
    
    def detect_object_type(self, payload_path: str) -> str:
        """Detect object type (default implementation)."""
        from pathlib import Path
        path = Path(payload_path)
        if path.is_file():
            return "content"
        elif path.is_dir():
            return "directory"
        else:
            raise ValueError(f"Payload is neither file nor directory: {payload_path}")

