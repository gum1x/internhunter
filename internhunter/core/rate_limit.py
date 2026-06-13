"""Rate limiting for external API calls."""

import asyncio
import time
from typing import Dict, Optional


class RateLimiter:
    """Simple rate limiter for external API calls."""
    
    def __init__(self, requests_per_second: float = 2.0):
        self.requests_per_second = requests_per_second
        self.min_interval = 1.0 / requests_per_second
        self.last_call_time: Dict[str, float] = {}
        self.lock = asyncio.Lock()
    
    async def wait_for_domain(self, domain: str) -> None:
        """Wait if necessary to respect rate limits for a domain."""
        async with self.lock:
            current_time = time.time()
            last_time = self.last_call_time.get(domain, 0)
            
            time_since_last = current_time - last_time
            if time_since_last < self.min_interval:
                wait_time = self.min_interval - time_since_last
                await asyncio.sleep(wait_time)
            
            self.last_call_time[domain] = time.time()


# Global rate limiter instance
rate_limiter = RateLimiter()