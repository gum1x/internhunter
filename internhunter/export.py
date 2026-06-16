"""Data export functionality for InternHunter."""

import csv
import json
from pathlib import Path

from .core.models import Internship


def export_internships_csv(filepath: Path, internships: list[Internship]) -> None:
    """Export internships to CSV file."""
    fieldnames = [
        "id", "company", "title", "location", "url", 
        "posted_date", "deadline", "remote", "source"
    ]
    
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for internship in internships:
            writer.writerow({
                "id": internship.id,
                "company": internship.company,
                "title": internship.title,
                "location": internship.location,
                "url": internship.url,
                "posted_date": internship.posted_date.isoformat() if internship.posted_date else "",
                "deadline": internship.deadline.isoformat() if internship.deadline else "",
                "remote": internship.remote,
                "source": internship.source
            })


def export_internships_json(filepath: Path, internships: list[Internship]) -> None:
    """Export internships to JSON file."""
    data = [
        {
            "id": i.id,
            "company": i.company,
            "title": i.title,
            "location": i.location,
            "url": i.url,
            "posted_date": i.posted_date.isoformat() if i.posted_date else None,
            "deadline": i.deadline.isoformat() if i.deadline else None,
            "remote": i.remote,
            "source": i.source,
            "description": i.description[:500] if i.description else None
        }
        for i in internships
    ]
    
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)