"""Telugu movie dataset scraper.

Pipeline:
    wikipedia.py  -- polite HTTP client (rate limit, retries, cache)
    parser.py     -- yearly list pages -> candidate movie rows
    extractor.py  -- individual movie page -> structured metadata
    cleaner.py    -- text normalisation shared by both parsers
    validator.py  -- Telugu-language + data-quality gating
    storage.py    -- SQLite resume state + CSV/JSON output
    tmdb.py       -- optional post-hoc enrichment (disabled by default)
"""

__version__ = "1.0.0"

__all__ = [
    "cleaner",
    "extractor",
    "parser",
    "storage",
    "validator",
    "wikipedia",
]
