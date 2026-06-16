"""User feedback and error reporting."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class Feedback(BaseModel):
    """User feedback model."""
    
    type: str  # "bug", "feature", "question"
    title: str
    description: str
    contact_email: str | None = None
    created_at: datetime = datetime.now()
    
    def to_dict(self) -> dict[str, Any]:
        """Convert feedback to dictionary."""
        data = self.dict()
        data["created_at"] = self.created_at.isoformat()
        return data


class FeedbackCollector:
    """Collect and store user feedback."""
    
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def save_feedback(self, feedback: Feedback) -> str:
        """Save feedback to disk and return feedback ID."""
        feedback_id = f"feedback_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        filepath = self.storage_path / f"{feedback_id}.json"
        
        with open(filepath, "w") as f:
            json.dump(feedback.to_dict(), f, indent=2)
        
        return feedback_id
    
    def get_feedback_count(self) -> int:
        """Get count of stored feedback items."""
        if not self.storage_path.exists():
            return 0
        return len(list(self.storage_path.glob("feedback_*.json")))