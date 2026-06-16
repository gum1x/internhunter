"""Cache configuration for InternHunter."""


from pydantic import Field
from pydantic_settings import BaseSettings


class CacheSettings(BaseSettings):
    """Cache configuration settings."""
    
    ttl_hours: int = Field(
        default=24,
        description="Time-to-live for cache entries in hours"
    )
    max_size_mb: int = Field(
        default=100,
        description="Maximum cache size in megabytes"
    )
    redis_url: str | None = Field(
        default=None,
        description="Redis URL for distributed caching (optional)"
    )
    
    class Config:
        env_prefix = "INTERNHUNTER_CACHE_"