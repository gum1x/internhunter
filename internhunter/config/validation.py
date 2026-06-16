"""Environment and configuration validation."""

import os
from typing import Any

from pydantic import ValidationError

from .settings import Settings


def validate_environment() -> list[str]:
    """Validate environment configuration and return warnings."""
    warnings = []
    
    try:
        settings: Any = Settings()
        
        # Check for required but missing settings
        if not settings.database_url:
            warnings.append("DATABASE_URL not set, using default SQLite database")
        
        if not settings.llm_base_url and settings.llm_enabled:
            warnings.append("LLM_BASE_URL not set but LLM enabled, LLM features will fail")
        
        # Check API keys if features are enabled
        if settings.github_enabled and not os.getenv("GITHUB_TOKEN"):
            warnings.append("GITHUB_TOKEN not set but GitHub features enabled")
        
        if settings.anthropic_enabled and not os.getenv("ANTHROPIC_API_KEY"):
            warnings.append("ANTHROPIC_API_KEY not set but Anthropic features enabled")
        
        # Validate paths
        if settings.data_dir:
            data_path = settings.data_dir
            if not data_path.exists():
                warnings.append(f"Data directory {data_path} does not exist")
            elif not os.access(data_path, os.W_OK):
                warnings.append(f"Data directory {data_path} is not writable")
        
    except ValidationError as e:
        warnings.append(f"Configuration validation error: {e}")
    
    return warnings


def check_prerequisites() -> bool:
    """Check if system prerequisites are met."""
    # Check Python version
    import sys
    if sys.version_info < (3, 12):  # noqa: UP036
        print(f"Warning: Python 3.12+ required, found {sys.version}")
        return False
    
    # Check for required system tools
    import shutil
    required_tools = ["git", "curl"]
    missing_tools = []
    
    for tool in required_tools:
        if not shutil.which(tool):
            missing_tools.append(tool)
    
    if missing_tools:
        print(f"Missing required tools: {', '.join(missing_tools)}")
        return False
    
    return True