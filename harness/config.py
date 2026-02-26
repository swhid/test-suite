"""
Pydantic models for configuration validation.

This module provides type-safe configuration models with validation
for the SWHID Testing Harness configuration file.
"""

from typing import Optional, Dict, List, Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from pathlib import Path


class OutputConfig(BaseModel):
    """Output configuration settings."""
    detailed_logs: bool = True
    format: Literal["json", "ndjson"] = "json"
    performance_metrics: bool = True
    results_dir: str = "results"
    
    @field_validator("results_dir")
    @classmethod
    def validate_results_dir(cls, v: str) -> str:
        """Validate results directory path."""
        if not v:
            raise ValueError("results_dir cannot be empty")
        return v


class ExpectedRefs(BaseModel):
    """Expected SWHID references for discovered branches/tags (v1)."""
    branches: Dict[str, str] = Field(default_factory=dict)
    tags: Dict[str, str] = Field(default_factory=dict)
    
    @field_validator("branches", "tags")
    @classmethod
    def validate_swhid_format(cls, v: Dict[str, str], info) -> Dict[str, str]:
        """Validate that values are valid SWHID format."""
        for key, swhid in v.items():
            if not swhid.startswith("swh:"):
                raise ValueError(f"Invalid SWHID format for {info.field_name}[{key}]: {swhid}")
        return v


class ExpectedRefsSha256(BaseModel):
    """Expected SHA256 SWHID references for discovered branches/tags (v2)."""
    branches: Dict[str, str] = Field(default_factory=dict)
    tags: Dict[str, str] = Field(default_factory=dict)
    
    @field_validator("branches", "tags")
    @classmethod
    def validate_swh2_format(cls, v: Dict[str, str], info) -> Dict[str, str]:
        """Validate that values are SWHID v2 (swh:2:)."""
        for key, swhid in v.items():
            if not swhid.startswith("swh:2:"):
                raise ValueError(f"Invalid SWHID v2 format for {info.field_name}[{key}]: {swhid}")
        return v


class RustConfig(BaseModel):
    """Rust-specific configuration for a payload."""
    version: Optional[int] = Field(None, ge=1, le=2)
    hash: Optional[Literal["sha1", "sha256"]] = None


class PayloadConfig(BaseModel):
    """Configuration for a single test payload."""
    name: str
    path: str
    description: Optional[str] = None
    expected_swhid: Optional[str] = None
    expected_swhid_sha256: Optional[str] = None
    commit: Optional[str] = None
    tag: Optional[str] = None
    discover_branches: bool = False
    discover_tags: bool = False
    expected: Optional[ExpectedRefs] = None
    expected_sha256: Optional[ExpectedRefsSha256] = None
    rust_config: Optional[RustConfig] = None
    expected_error: Optional[str] = None  # For negative tests
    
    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate payload name."""
        if not v:
            raise ValueError("Payload name cannot be empty")
        return v
    
    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Validate payload path."""
        if not v:
            raise ValueError("Payload path cannot be empty")
        return v
    
    @field_validator("expected_swhid", "expected_swhid_sha256")
    @classmethod
    def validate_swhid(cls, v: Optional[str]) -> Optional[str]:
        """Validate SWHID format."""
        if v is not None and not v.startswith("swh:"):
            raise ValueError(f"Invalid SWHID format: {v}")
        return v
    
    @model_validator(mode="after")
    def validate_payload_consistency(self) -> "PayloadConfig":
        """Validate payload configuration consistency."""
        # For release payloads, tag should be provided
        if self.tag is not None and not self.path:
            raise ValueError("Payload path is required when tag is specified")
        
        # For revision payloads, commit may be provided
        if self.commit is not None and not self.path:
            raise ValueError("Payload path is required when commit is specified")
        
        # Discovery flags should only be used with git-repository category
        if (self.discover_branches or self.discover_tags) and not self.path.endswith(".tar.gz"):
            # This is a soft validation - we'll allow it but it may not work as expected
            pass
        
        return self


class SettingsConfig(BaseModel):
    """Runtime settings configuration."""
    cleanup_temp: bool = True
    max_file_size: str = "100MB"
    parallel_tests: int = Field(4, ge=1, le=32)
    timeout: int = Field(30, ge=1, le=3600)
    
    @field_validator("max_file_size")
    @classmethod
    def validate_max_file_size(cls, v: str) -> str:
        """Validate max_file_size format."""
        if not v:
            raise ValueError("max_file_size cannot be empty")
        # Should be in format like "100MB", "1GB", etc.
        if not any(v.upper().endswith(unit) for unit in ["B", "KB", "MB", "GB", "TB"]):
            raise ValueError(f"Invalid max_file_size format: {v}. Expected format like '100MB'")
        return v


class HarnessConfig(BaseModel):
    """Complete harness configuration model."""
    output: OutputConfig
    payloads: Dict[str, List[PayloadConfig]]
    settings: SettingsConfig
    
    @field_validator("payloads")
    @classmethod
    def validate_payloads(cls, v: Dict[str, List[PayloadConfig]]) -> Dict[str, List[PayloadConfig]]:
        """Validate payloads structure."""
        if not v:
            raise ValueError("payloads section cannot be empty")
        
        # Check for duplicate payload names within categories
        for category, payloads in v.items():
            names = [p.name for p in payloads]
            duplicates = [name for name in names if names.count(name) > 1]
            if duplicates:
                raise ValueError(f"Duplicate payload names in category '{category}': {set(duplicates)}")
        
        return v
    
    @classmethod
    def load_from_file(cls, config_path: str) -> "HarnessConfig":
        """
        Load configuration from YAML file.
        
        Args:
            config_path: Path to configuration YAML file
            
        Returns:
            Validated HarnessConfig instance
            
        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config is invalid
        """
        import yaml
        from pathlib import Path
        
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        with open(config_file, 'r') as f:
            try:
                raw_config = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise ValueError(f"Invalid YAML in configuration file: {e}")
        
        if raw_config is None:
            raise ValueError("Configuration file is empty")
        
        try:
            return cls.model_validate(raw_config)
        except Exception as e:
            raise ValueError(f"Invalid configuration: {e}")
    
    def get_payload_by_name(self, category: str, name: str) -> Optional[PayloadConfig]:
        """
        Get a payload by category and name.
        
        Args:
            category: Payload category
            name: Payload name
            
        Returns:
            PayloadConfig if found, None otherwise
        """
        if category not in self.payloads:
            return None
        
        for payload in self.payloads[category]:
            if payload.name == name:
                return payload
        
        return None
    
    def get_all_payloads(self) -> List[tuple[str, PayloadConfig]]:
        """
        Get all payloads as (category, payload) tuples.
        
        Returns:
            List of (category, payload) tuples
        """
        result = []
        for category, payloads in self.payloads.items():
            for payload in payloads:
                result.append((category, payload))
        return result

