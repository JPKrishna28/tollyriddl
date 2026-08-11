"""Central configuration for the Telugu movie dataset scraper.

Every tunable lives here so the parser can be tightened without touching
scraping logic. Values chosen during the Wikipedia structure recon are
documented inline with the observation that motivated them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Frozen: treat as read-only config."""

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------
    project_root: Path = PROJECT_ROOT
    cache_dir: Path = PROJECT_ROOT / "cache"
    logs_dir: Path = PROJECT_ROOT / "logs"
    output_dir: Path = PROJECT_ROOT / "output"
    log_file: Path = PROJECT_ROOT / "logs" / "scraper.log"
    state_db: Path = PROJECT_ROOT / "output" / "scraper_state.db"

    # ------------------------------------------------------------------
    # Year range
    # ------------------------------------------------------------------
    default_start_year: int = 2000
    default_end_year: int = 2023
    min_valid_year: int = 2000
    max_valid_year: int = 2023

    # ------------------------------------------------------------------
    # Network / politeness
    # ------------------------------------------------------------------
    # Contact info in the UA is what Wikipedia's robot policy asks for.
    user_agent: str = (
        "TeluguMovieDatasetScraper/1.0 "
        "(https://github.com/example/telugu-movie-scraper; "
        "contact: jaswanth@pcsdatai.com) python-requests"
    )
    api_endpoint: str = "https://en.wikipedia.org/w/api.php"
    wiki_base: str = "https://en.wikipedia.org/wiki/"
    wikidata_api: str = "https://www.wikidata.org/w/api.php"

    # Rate limit: minimum seconds between two live requests. The spec asks
    # for 1-2s; we jitter between these bounds so we never look like a
    # fixed-interval bot.
    min_delay: float = 1.0
    max_delay: float = 2.0

    request_timeout: int = 30
    max_retries: int = 5
    backoff_factor: float = 2.0
    backoff_max: float = 120.0
    # On HTTP 429 we add this to the floor delay for the rest of the run.
    throttle_penalty: float = 2.0
    throttle_penalty_max: float = 30.0

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------
    cache_enabled: bool = True
    # Cached HTML never expires by default: Wikipedia film pages for
    # 2000-2023 are effectively static and re-runs are for parser work.
    cache_ttl_days: int | None = None

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    csv_name: str = "telugu_movies_2000_2023.csv"
    json_name: str = "telugu_movies_2000_2023.json"
    failed_csv_name: str = "failed_urls.csv"
    report_name: str = "scraping_report.json"
    missing_csv_name: str = "missing_fields.csv"
    discrepancies_csv_name: str = "year_discrepancies.csv"
    rejected_csv_name: str = "rejected_movies.csv"
    multi_value_separator: str = "|"
    null_value: str = ""

    # ------------------------------------------------------------------
    # Language validation
    # ------------------------------------------------------------------
    target_language: str = "Telugu"
    # Only 'high' and 'medium' land in the primary dataset; 'low' is kept
    # in rejected_movies.csv so nothing is silently discarded.
    accepted_confidences: tuple[str, ...] = ("high", "medium")

    # ------------------------------------------------------------------
    # Enrichment toggles
    # ------------------------------------------------------------------
    wikidata_enabled: bool = True
    tmdb_enabled: bool = False
    tmdb_api_key: str | None = field(
        default_factory=lambda: os.environ.get("TMDB_API_KEY")
    )

    def ensure_dirs(self) -> None:
        """Create the runtime directories if they are missing."""
        for directory in (self.cache_dir, self.logs_dir, self.output_dir):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()


# ----------------------------------------------------------------------
# Infobox label aliases
# ----------------------------------------------------------------------
# Derived from a live label-frequency count over 15 films spanning
# 2000-2023. Labels are normalised (lowercased, NBSP -> space, trailing
# punctuation stripped) before lookup, so only lowercase keys appear here.

DIRECTOR_LABELS: tuple[str, ...] = (
    "directed by",
    "director",
    "directors",
    "direction",
)

WRITER_LABELS: tuple[str, ...] = (
    "written by",
    "writer",
    "writers",
    "screenplay by",
    "screenplay",
    "story by",
    "story",
    "based on",
)

# Recon showed 'Dialogues by' is a *separate* infobox row on 6/15 films.
# The spec explicitly forbids treating dialogue/lyrics/camera credits as
# the writer, so these are hard-excluded rather than merely deprioritised.
WRITER_EXCLUDED_LABELS: frozenset[str] = frozenset(
    {
        "dialogues by",
        "dialogue by",
        "dialogues",
        "dialogue",
        "lyrics by",
        "lyrics",
        "cinematography",
        "edited by",
        "editor",
        "narrated by",
    }
)

# Preference order when several writer-ish rows exist: an explicit
# "written by" beats a screenplay credit, which beats a story credit.
WRITER_LABEL_PRIORITY: tuple[str, ...] = (
    "written by",
    "writer",
    "writers",
    "screenplay by",
    "screenplay",
    "story by",
    "story",
    "based on",
)

MUSIC_LABELS: tuple[str, ...] = (
    "music by",
    "music",
    "music director",
    "composer",
    "composed by",
    "score by",
    "original score",
)

PRODUCTION_HOUSE_LABELS: tuple[str, ...] = (
    "production company",
    "production companies",
    "production house",
    "production houses",
    "produced by",  # last-resort fallback; see extractor notes
    "studio",
    "studios",
    "banner",
)

# 'Produced by' names *people*, not companies, on most Indian film
# infoboxes. It is only consulted when no company row exists at all.
PRODUCTION_FALLBACK_LABELS: frozenset[str] = frozenset({"produced by"})

CAST_LABELS: tuple[str, ...] = (
    "starring",
    "cast",
    "stars",
    "starring cast",
)

LANGUAGE_LABELS: tuple[str, ...] = (
    "language",
    "languages",
)

RELEASE_DATE_LABELS: tuple[str, ...] = (
    "release date",
    "release dates",
    "released",
)

COUNTRY_LABELS: tuple[str, ...] = ("country", "countries")

GENRE_LABELS: tuple[str, ...] = ("genre", "genres")


# ----------------------------------------------------------------------
# Yearly-list table headers
# ----------------------------------------------------------------------

LIST_TITLE_HEADERS: tuple[str, ...] = ("title", "film", "movie", "name")
LIST_DIRECTOR_HEADERS: tuple[str, ...] = ("director", "directed by", "direction")
LIST_CAST_HEADERS: tuple[str, ...] = ("cast", "starring", "stars")
LIST_PRODUCTION_HEADERS: tuple[str, ...] = (
    "production house",
    "production company",
    "production companies",
    "banner",
    "studio",
    "production",
)
LIST_DATE_HEADERS: tuple[str, ...] = ("opening", "date", "release date", "release")

# A table must look like a release table. Box-office tables ('Rank',
# 'Worldwide gross') and award tables ('Event', 'Host') also carry a
# 'Title' column, so they are rejected by these markers.
LIST_REJECT_HEADERS: frozenset[str] = frozenset(
    {
        "rank",
        "worldwide gross",
        "gross",
        "distributor's share",
        "distributors' share",
        "event",
        "host",
        "location",
        "award",
        "category",
        "recipient",
        "nominee",
        "winner",
    }
)


# ----------------------------------------------------------------------
# Genre vocabulary
# ----------------------------------------------------------------------
# Wikipedia film infoboxes carry no 'Genre' row (confirmed: 0 hits across
# 15 films). Genre is therefore mined from categories such as
# '2021 action drama films' / '2000 romantic drama films'. This controlled
# vocabulary keeps the output clean and prevents category noise
# ('Films about funerals') from leaking in as a genre.

GENRE_VOCABULARY: tuple[str, ...] = (
    "Action",
    "Adventure",
    "Animation",
    "Anthology",
    "Biographical",
    "Comedy",
    "Crime",
    "Dance",
    "Devotional",
    "Disaster",
    "Documentary",
    "Drama",
    "Family",
    "Fantasy",
    "Heist",
    "Historical",
    "Horror",
    "Independent",
    "Legal",
    "Martial arts",
    "Masala",
    "Musical",
    "Mystery",
    "Political",
    "Psychological",
    "Road",
    "Romance",
    "Satire",
    "Science fiction",
    "Slasher",
    "Spy",
    "Sports",
    "Supernatural",
    "Superhero",
    "Survival",
    "Teen",
    "Thriller",
    "War",
    "Western",
    "Zombie",
)

# Category-fragment -> canonical genre. Longer keys are matched first so
# 'science fiction' wins over a bare 'fiction'-style partial.
GENRE_SYNONYMS: dict[str, str] = {
    "action": "Action",
    "adventure": "Adventure",
    "animated": "Animation",
    "animation": "Animation",
    "anthology": "Anthology",
    "biographical": "Biographical",
    "biopic": "Biographical",
    "comedy": "Comedy",
    "comedy-drama": "Comedy",
    "crime": "Crime",
    "dance": "Dance",
    "devotional": "Devotional",
    "hindu devotional": "Devotional",
    "mythological": "Devotional",
    "disaster": "Disaster",
    "documentary": "Documentary",
    "drama": "Drama",
    "family": "Family",
    "fantasy": "Fantasy",
    "heist": "Heist",
    "historical": "Historical",
    "history": "Historical",
    "horror": "Horror",
    "independent": "Independent",
    "legal": "Legal",
    "martial arts": "Martial arts",
    "masala": "Masala",
    "musical": "Musical",
    "mystery": "Mystery",
    "political": "Political",
    "psychological": "Psychological",
    "road": "Road",
    "romance": "Romance",
    "romantic": "Romance",
    "satire": "Satire",
    "satirical": "Satire",
    "science fiction": "Science fiction",
    "sci-fi": "Science fiction",
    "slasher": "Slasher",
    "spy": "Spy",
    "sports": "Sports",
    "sport": "Sports",
    "supernatural": "Supernatural",
    "superhero": "Superhero",
    "survival": "Survival",
    "teen": "Teen",
    "thriller": "Thriller",
    "war": "War",
    "western": "Western",
    "zombie": "Zombie",
}


# ----------------------------------------------------------------------
# Noise filters
# ----------------------------------------------------------------------
# Values that mean "no data" and must become NULL rather than be stored.
PLACEHOLDER_VALUES: frozenset[str] = frozenset(
    {
        "",
        "-",
        "--",
        "—",
        "–",
        "n/a",
        "na",
        "tba",
        "tbd",
        "unknown",
        "none",
        "unreleased",
        "not known",
        "see below",
        "see distribution",
        "various",
        "citation needed",
    }
)

# Infobox values that point elsewhere instead of naming anyone.
CROSS_REFERENCE_VALUES: frozenset[str] = frozenset(
    {
        "see below",
        "see distribution",
        "see credits",
        "various",
        "multiple",
    }
)

NON_MOVIE_TITLE_MARKERS: tuple[str, ...] = (
    "list of",
    "category:",
    "template:",
    "wikipedia:",
    "portal:",
    "help:",
    "file:",
    "draft:",
    "cinema of",
    "film industry",
)
