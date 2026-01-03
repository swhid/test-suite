"""
Resource management for the SWHID Testing Harness.

This module handles temporary directory management, tarball extraction,
and cleanup operations.
"""

import os
import shutil
import tempfile
import tarfile
import platform
import stat
import time
from pathlib import Path
from typing import List
import logging

logger = logging.getLogger(__name__)


class ResourceManager:
    """Manages temporary resources and cleanup operations."""
    
    def __init__(self):
        """Initialize resource manager."""
        self._temp_dirs: List[str] = []
    
    def extract_tarball_if_needed(self, payload_path: str, config_dir: str) -> str:
        """
        Extract tarball to temporary directory if payload is a .tar.gz file.
        
        Args:
            payload_path: Path to payload (may be .tar.gz file)
            config_dir: Directory containing config file (for resolving relative paths)
            
        Returns:
            Path to the extracted directory (or original path if not a tarball)
        """
        if not payload_path.endswith('.tar.gz'):
            return payload_path
        
        # Resolve absolute path
        if not os.path.isabs(payload_path):
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
    
    def cleanup_temp_dirs(self) -> None:
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
    
    def _rmtree_windows(self, path: str) -> None:
        """
        Windows-specific recursive delete that handles locked files gracefully.
        
        On Windows, Git object files may be locked by the file system, preventing
        normal deletion. This method attempts to handle such cases gracefully.
        
        Args:
            path: Path to directory to remove
        """
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

