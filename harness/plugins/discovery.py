"""
Implementation discovery system for finding and loading SWHID implementations.
"""

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Dict, List, Type, Optional
import logging

from .base import SwhidImplementation

logger = logging.getLogger(__name__)

class ImplementationDiscovery:
    """Discovers and loads SWHID implementations from the filesystem."""
    
    def __init__(self, implementations_dir: str = "implementations"):
        self.implementations_dir = Path(implementations_dir)
        self._implementations_cache: Dict[str, SwhidImplementation] = {}
    
    def discover_implementations(
        self,
        force_reload: bool = False,
        only_impls: Optional[List[str]] = None
    ) -> Dict[str, SwhidImplementation]:
        """
        Auto-discover implementations.
        
        Args:
            force_reload: If True, reload implementations even if cached
            only_impls: If set, only load these implementation names (e.g. ['rust']).
                        Avoids loading others, so their is_available() is never
                        called and no "not available" warnings are logged.
            
        Returns:
            Dictionary mapping implementation names to instances
        """
        cache_key = (tuple(sorted(only_impls or [])) if only_impls else None)
        if not force_reload and self._implementations_cache and getattr(self, "_cache_key", None) == cache_key:
            return self._implementations_cache
        
        implementations = {}
        
        if not self.implementations_dir.exists():
            logger.warning(f"Implementations directory not found: {self.implementations_dir}")
            return implementations
        
        only_set = set(only_impls) if only_impls else None
        
        for impl_dir in self.implementations_dir.iterdir():
            if not impl_dir.is_dir():
                continue
            if impl_dir.name.startswith('.'):
                continue
            if only_set is not None and impl_dir.name not in only_set:
                continue
            
            try:
                impl = self._load_implementation(impl_dir)
                if impl and impl.is_available():
                    info = impl.get_info()
                    implementations[info.name] = impl
                    logger.info(f"Loaded implementation: {info.name} v{info.version}")
                else:
                    logger.debug(f"Implementation {impl_dir.name} not available")
            except Exception as e:
                logger.warning(f"Failed to load implementation {impl_dir.name}: {e}")
        
        self._implementations_cache = implementations
        self._cache_key = cache_key
        return implementations
    
    def _load_implementation(self, impl_dir: Path) -> Optional[SwhidImplementation]:
        """Load a single implementation from a directory."""
        impl_file = impl_dir / "implementation.py"
        
        if not impl_file.exists():
            logger.debug(f"No implementation.py found in {impl_dir}")
            return None
        
        # Create a unique module name
        module_name = f"implementations.{impl_dir.name}.implementation"
        
        # Load the module
        spec = importlib.util.spec_from_file_location(module_name, impl_file)
        if spec is None:
            logger.warning(f"Could not create spec for {impl_file}")
            return None
        
        module = importlib.util.module_from_spec(spec)
        
        # Add to sys.modules to avoid reload issues
        if module_name in sys.modules:
            del sys.modules[module_name]
        
        sys.modules[module_name] = module
        
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            logger.warning(f"Failed to execute module {module_name}: {e}")
            return None
        
        # Look for Implementation class
        impl_class = getattr(module, "Implementation", None)
        
        if impl_class is None:
            logger.warning(f"No Implementation class found in {impl_file}")
            return None
        
        if not issubclass(impl_class, SwhidImplementation):
            logger.warning(f"Implementation class in {impl_file} does not inherit from SwhidImplementation")
            return None
        
        try:
            return impl_class()
        except Exception as e:
            logger.warning(f"Failed to instantiate implementation {impl_dir.name}: {e}")
            return None
    
    def get_implementation(self, name: str) -> Optional[SwhidImplementation]:
        """Get a specific implementation by name."""
        implementations = self.discover_implementations()
        return implementations.get(name)
    
    def list_available_implementations(self) -> List[str]:
        """List names of all available implementations."""
        implementations = self.discover_implementations()
        return list(implementations.keys())
    
    def reload_implementation(self, name: str) -> Optional[SwhidImplementation]:
        """Reload a specific implementation."""
        if name in self._implementations_cache:
            del self._implementations_cache[name]
        
        # Find the implementation directory
        impl_dir = self.implementations_dir / name
        if not impl_dir.exists():
            logger.warning(f"Implementation directory not found: {impl_dir}")
            return None
        
        return self._load_implementation(impl_dir)
    
    def clear_cache(self):
        """Clear the implementations cache."""
        self._implementations_cache.clear()
