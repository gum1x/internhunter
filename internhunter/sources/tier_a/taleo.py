"""Oracle Taleo ATS integration (placeholder)."""


from ..base import Internship, Source


class TaleoSource(Source):
    """Oracle Taleo ATS source."""
    
    name = "taleo"
    base_urls = ["https://{tenant}.taleo.net"]
    
    async def fetch_internships(self) -> list[Internship]:
        """Fetch internships from Taleo."""
        # This is a placeholder - Taleo integration would require
        # reverse engineering their JavaScript-heavy interface
        return []
    
    @classmethod
    def detect(cls, url: str) -> bool:
        """Detect if URL is a Taleo careers page."""
        return "taleo.net" in url.lower() or "taleocdn.net" in url.lower()