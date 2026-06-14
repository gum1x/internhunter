# Development Guide

## Project Structure

```
internhunter/
├── cli.py              # Command-line interface
├── core/               # Core functionality
│   ├── fetch.py       # HTTP client with caching
│   ├── db.py          # Database models and sessions
│   ├── browser.py     # Browser automation
│   └── normalize.py   # Data normalization
├── sources/           # ATS integrations (tier_a, tier_b, tier_c)
├── discovery/         # Board discovery mechanisms
├── match/            # Matching and scoring algorithms
├── llm/              # LLM integration
├── contacts/         # Contact discovery
├── web/              # Web dashboard (FastAPI + HTMX)
├── notify/           # Notification system
└── config/           # Configuration management
```

## Adding a New ATS Integration

1. Determine the ATS tier based on authentication requirements:
   - **Tier A**: Keyless JSON APIs (Greenhouse, Lever, Ashby)
   - **Tier B**: Public HTML/JSON (BreezyHR, BambooHR)
   - **Tier C**: JavaScript-heavy or authenticated (Workday, iCIMS)

2. Create a new file in the appropriate `sources/tier_*/` directory:

```python
from typing import List
from ..base import Source, Internship

class NewATSSource(Source):
    name = "new_ats"
    base_urls = ["https://api.newats.com"]
    
    async def fetch_internships(self) -> List[Internship]:
        # Implementation here
        return []
    
    @classmethod
    def detect(cls, url: str) -> bool:
        return "newats.com" in url
```

3. Register the source in `sources/__init__.py`:
```python
from .tier_a.new_ats import NewATSSource
register_source(NewATSSource)
```

4. Add tests in `tests/test_new_ats.py` with fixtures.

## Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_greenhouse.py

# Run with coverage
pytest --cov=internhunter --cov-report=html
```

## Code Quality

```bash
# Format code
ruff format internhunter tests

# Lint code
ruff check internhunter tests --fix

# Type checking
mypy internhunter --strict
```

## Database Migrations

When modifying database models:
1. Update models in `internhunter/core/models.py`
2. Create migration in `migrations/` directory
3. Test migration with existing data

## Release Process

1. Update version in `pyproject.toml`
2. Update CHANGELOG.md
3. Run full test suite
4. Build and publish package:
   ```bash
   hatch build
   hatch publish
   ```