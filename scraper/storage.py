"""Persistence: SQLite resume state and dataset output files.

The SQLite database is the resume backbone. Every discovered film is
recorded with a status (``pending`` / ``success`` / ``failed``) before any
page is fetched, so a crash after N movies resumes at N+1 instead of zero.
Scraped payloads are stored as JSON alongside the status, which means the
CSV/JSON exports can be regenerated without re-fetching anything.
"""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from config.settings import settings
from scraper.extractor import MovieRecord

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS movies (
    url            TEXT PRIMARY KEY,
    movie_name     TEXT NOT NULL,
    year           INTEGER,
    wikipedia_title TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',
    attempts       INTEGER NOT NULL DEFAULT 0,
    last_attempt   TEXT,
    error          TEXT,
    payload        TEXT,
    language_confidence TEXT,
    is_valid       INTEGER,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_movies_status ON movies(status);
CREATE INDEX IF NOT EXISTS idx_movies_year   ON movies(year);

CREATE TABLE IF NOT EXISTS years (
    year        INTEGER PRIMARY KEY,
    page_title  TEXT,
    page_url    TEXT,
    discovered  INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    args        TEXT,
    summary     TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ScraperState:
    """SQLite-backed progress tracker enabling resume and retry."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or settings.state_db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        # WAL keeps the DB readable while a long scrape is writing.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------------
    # Discovery bookkeeping
    # ------------------------------------------------------------------
    def add_movie(
        self, url: str, movie_name: str, year: int, wikipedia_title: str | None = None
    ) -> bool:
        """Register a discovered film. Returns True when newly inserted."""
        now = _now()
        cursor = self.conn.execute(
            """
            INSERT INTO movies (url, movie_name, year, wikipedia_title,
                                status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO NOTHING
            """,
            (url, movie_name, year, wikipedia_title, STATUS_PENDING, now, now),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def add_movies(self, rows: Iterable[tuple[str, str, int, str | None]]) -> int:
        """Bulk-register discovered films; returns the number of new rows."""
        inserted = 0
        for url, name, year, title in rows:
            if self.add_movie(url, name, year, title):
                inserted += 1
        return inserted

    def record_year(
        self,
        year: int,
        *,
        page_title: str = "",
        page_url: str = "",
        discovered: int = 0,
        status: str = STATUS_SUCCESS,
        error: str | None = None,
    ) -> None:
        """Record the outcome of processing a yearly list page."""
        self.conn.execute(
            """
            INSERT INTO years (year, page_title, page_url, discovered, status, error, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(year) DO UPDATE SET
                page_title=excluded.page_title,
                page_url=excluded.page_url,
                discovered=excluded.discovered,
                status=excluded.status,
                error=excluded.error,
                updated_at=excluded.updated_at
            """,
            (year, page_title, page_url, discovered, status, error, _now()),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Work queue
    # ------------------------------------------------------------------
    def pending_movies(
        self, *, years: Iterable[int] | None = None, limit: int | None = None
    ) -> list[sqlite3.Row]:
        """Films still awaiting a successful scrape."""
        query = "SELECT * FROM movies WHERE status = ?"
        params: list[Any] = [STATUS_PENDING]
        query, params = self._apply_year_filter(query, params, years)
        query += " ORDER BY year, movie_name"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        return self.conn.execute(query, params).fetchall()

    def failed_movies(
        self, *, years: Iterable[int] | None = None, limit: int | None = None
    ) -> list[sqlite3.Row]:
        """Films whose last attempt failed, for ``--retry-failed``."""
        query = "SELECT * FROM movies WHERE status = ?"
        params: list[Any] = [STATUS_FAILED]
        query, params = self._apply_year_filter(query, params, years)
        query += " ORDER BY attempts, year"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        return self.conn.execute(query, params).fetchall()

    def successful_movies(
        self, *, years: Iterable[int] | None = None
    ) -> list[sqlite3.Row]:
        """All successfully scraped films."""
        query = "SELECT * FROM movies WHERE status = ? AND payload IS NOT NULL"
        params: list[Any] = [STATUS_SUCCESS]
        query, params = self._apply_year_filter(query, params, years)
        query += " ORDER BY year, movie_name"
        return self.conn.execute(query, params).fetchall()

    @staticmethod
    def _apply_year_filter(
        query: str, params: list[Any], years: Iterable[int] | None
    ) -> tuple[str, list[Any]]:
        year_list = list(years) if years is not None else []
        if year_list:
            placeholders = ",".join("?" for _ in year_list)
            query += f" AND year IN ({placeholders})"
            params.extend(year_list)
        return query, params

    # ------------------------------------------------------------------
    # Status updates
    # ------------------------------------------------------------------
    def mark_success(
        self,
        url: str,
        record: MovieRecord,
        *,
        language_confidence: str,
        is_valid: bool,
    ) -> None:
        """Store a scraped record and mark the URL done."""
        self.conn.execute(
            """
            UPDATE movies
               SET status = ?, payload = ?, error = NULL,
                   attempts = attempts + 1, last_attempt = ?,
                   language_confidence = ?, is_valid = ?, updated_at = ?
             WHERE url = ?
            """,
            (
                STATUS_SUCCESS,
                json.dumps(asdict(record), ensure_ascii=False),
                _now(),
                language_confidence,
                1 if is_valid else 0,
                _now(),
                url,
            ),
        )
        self.conn.commit()

    def mark_failed(self, url: str, error: str) -> None:
        """Record a failure; the row stays retryable."""
        self.conn.execute(
            """
            UPDATE movies
               SET status = ?, error = ?, attempts = attempts + 1,
                   last_attempt = ?, updated_at = ?
             WHERE url = ?
            """,
            (STATUS_FAILED, error[:1000], _now(), _now(), url),
        )
        self.conn.commit()

    def reset_failed(self) -> int:
        """Move failed rows back to pending so they are retried."""
        cursor = self.conn.execute(
            "UPDATE movies SET status = ?, updated_at = ? WHERE status = ?",
            (STATUS_PENDING, _now(), STATUS_FAILED),
        )
        self.conn.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        """Aggregate counts for ``--stats`` and the final report."""
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM movies GROUP BY status"
        ).fetchall()
        by_status = {row["status"]: row["n"] for row in rows}

        per_year = self.conn.execute(
            """
            SELECT year,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS ok,
                   SUM(CASE WHEN status='failed'  THEN 1 ELSE 0 END) AS failed
              FROM movies GROUP BY year ORDER BY year
            """
        ).fetchall()

        return {
            "total": sum(by_status.values()),
            "by_status": by_status,
            "pending": by_status.get(STATUS_PENDING, 0),
            "success": by_status.get(STATUS_SUCCESS, 0),
            "failed": by_status.get(STATUS_FAILED, 0),
            "per_year": [dict(row) for row in per_year],
        }

    def load_records(self, *, only_valid: bool = True) -> list[MovieRecord]:
        """Rehydrate stored payloads into :class:`MovieRecord` objects."""
        query = "SELECT payload, is_valid FROM movies WHERE payload IS NOT NULL"
        if only_valid:
            query += " AND is_valid = 1"
        records: list[MovieRecord] = []
        for row in self.conn.execute(query):
            try:
                records.append(MovieRecord(**json.loads(row["payload"])))
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Skipping corrupt payload: %s", exc)
        return records

    def start_run(self, args: str) -> int:
        cursor = self.conn.execute(
            "INSERT INTO runs (started_at, args) VALUES (?, ?)", (_now(), args)
        )
        self.conn.commit()
        return int(cursor.lastrowid or 0)

    def finish_run(self, run_id: int, summary: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, summary = ? WHERE id = ?",
            (_now(), json.dumps(summary, ensure_ascii=False), run_id),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ScraperState":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


# ----------------------------------------------------------------------
# Output writers
# ----------------------------------------------------------------------

CSV_COLUMNS = [
    "movie_id",
    "movie_name",
    "year",
    "language",
    "genre",
    "cast",
    "director",
    "production_house",
    "music_director",
    "writer",
    "wikipedia_url",
]

SEPARATOR = settings.multi_value_separator


def _join(values: list[str]) -> str:
    """Render a multi-value field for CSV using the pipe separator."""
    return SEPARATOR.join(values) if values else settings.null_value


def records_to_rows(records: list[MovieRecord]) -> list[dict[str, Any]]:
    """Assign stable ids and flatten records into CSV rows."""
    ordered = sorted(
        records, key=lambda r: (r.year or 0, r.movie_name.lower())
    )
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(ordered, start=1):
        rows.append(
            {
                "movie_id": index,
                "movie_name": record.movie_name,
                "year": record.year if record.year is not None else settings.null_value,
                "language": record.language or settings.target_language,
                "genre": _join(record.genre),
                "cast": _join(record.cast),
                "director": _join(record.director),
                "production_house": _join(record.production_house),
                "music_director": _join(record.music_director),
                "writer": _join(record.writer),
                "wikipedia_url": record.wikipedia_url,
            }
        )
    return rows


def write_csv(records: list[MovieRecord], path: Path | None = None) -> Path:
    """Write the flat CSV dataset."""
    target = Path(path or settings.output_dir / settings.csv_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = records_to_rows(records)

    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Wrote %d rows -> %s", len(rows), target)
    return target


def write_json(records: list[MovieRecord], path: Path | None = None) -> Path:
    """Write the structured JSON dataset.

    Multi-value fields stay as arrays here (rather than pipe-joined
    strings) because the downstream game needs them structurally.
    """
    target = Path(path or settings.output_dir / settings.json_name)
    target.parent.mkdir(parents=True, exist_ok=True)

    ordered = sorted(records, key=lambda r: (r.year or 0, r.movie_name.lower()))
    payload = [
        {
            "movie_id": index,
            "movie_name": record.movie_name,
            "year": record.year,
            "language": record.language or settings.target_language,
            "genre": record.genre,
            "cast": record.cast,
            "director": record.director,
            "production_house": record.production_house,
            "music_director": record.music_director,
            "writer": record.writer,
            "wikipedia_url": record.wikipedia_url,
        }
        for index, record in enumerate(ordered, start=1)
    ]

    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Wrote %d records -> %s", len(payload), target)
    return target


def write_failed_csv(state: ScraperState, path: Path | None = None) -> Path:
    """Export every failed URL with its error, for later retry."""
    target = Path(path or settings.output_dir / settings.failed_csv_name)
    target.parent.mkdir(parents=True, exist_ok=True)

    rows = state.conn.execute(
        """
        SELECT url, movie_name, year, status, attempts, last_attempt, error
          FROM movies WHERE status = ? ORDER BY year, movie_name
        """,
        (STATUS_FAILED,),
    ).fetchall()

    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["wikipedia_url", "movie_name", "year", "status", "attempts", "last_attempt", "error"]
        )
        for row in rows:
            writer.writerow(
                [
                    row["url"],
                    row["movie_name"],
                    row["year"],
                    row["status"],
                    row["attempts"],
                    row["last_attempt"] or "",
                    (row["error"] or "").replace("\n", " "),
                ]
            )

    logger.info("Wrote %d failed URLs -> %s", len(rows), target)
    return target


def write_missing_fields_csv(
    records: list[MovieRecord], path: Path | None = None
) -> Path:
    """Export per-film missing-field flags for manual enrichment."""
    target = Path(path or settings.output_dir / settings.missing_csv_name)
    target.parent.mkdir(parents=True, exist_ok=True)

    columns = [
        "movie_name",
        "year",
        "missing_genre",
        "missing_cast",
        "missing_director",
        "missing_production_house",
        "missing_music_director",
        "missing_writer",
        "wikipedia_url",
    ]

    written = 0
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in sorted(records, key=lambda r: (r.year or 0, r.movie_name.lower())):
            missing = record.missing_fields()
            if not any(missing.values()):
                continue  # nothing missing -> nothing to enrich
            writer.writerow(
                {
                    "movie_name": record.movie_name,
                    "year": record.year,
                    "missing_genre": int(missing["genre"]),
                    "missing_cast": int(missing["cast"]),
                    "missing_director": int(missing["director"]),
                    "missing_production_house": int(missing["production_house"]),
                    "missing_music_director": int(missing["music_director"]),
                    "missing_writer": int(missing["writer"]),
                    "wikipedia_url": record.wikipedia_url,
                }
            )
            written += 1

    logger.info("Wrote %d incomplete records -> %s", written, target)
    return target


def write_discrepancies_csv(
    records: list[MovieRecord], path: Path | None = None
) -> Path:
    """Export films whose list-page year disagrees with the infobox."""
    target = Path(path or settings.output_dir / settings.discrepancies_csv_name)
    target.parent.mkdir(parents=True, exist_ok=True)

    flagged = [r for r in records if r.year_discrepancy]
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["movie_name", "list_year", "infobox_year", "release_date", "wikipedia_url", "note"]
        )
        for record in flagged:
            writer.writerow(
                [
                    record.movie_name,
                    record.list_year,
                    record.infobox_year,
                    record.release_date,
                    record.wikipedia_url,
                    "; ".join(record.notes),
                ]
            )

    logger.info("Wrote %d year discrepancies -> %s", len(flagged), target)
    return target


def write_rejected_csv(
    rejected: list[tuple[MovieRecord, list[str], str]], path: Path | None = None
) -> Path:
    """Export records excluded from the dataset, with the reason why.

    Nothing is silently discarded: a rejected film is auditable here.
    """
    target = Path(path or settings.output_dir / settings.rejected_csv_name)
    target.parent.mkdir(parents=True, exist_ok=True)

    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["movie_name", "year", "language", "language_confidence", "reasons", "wikipedia_url"]
        )
        for record, reasons, confidence in rejected:
            writer.writerow(
                [
                    record.movie_name,
                    record.year,
                    record.language,
                    confidence,
                    "; ".join(reasons),
                    record.wikipedia_url,
                ]
            )

    logger.info("Wrote %d rejected records -> %s", len(rejected), target)
    return target


def write_report(report: dict[str, Any], path: Path | None = None) -> Path:
    """Write the machine-readable scraping report."""
    target = Path(path or settings.output_dir / settings.report_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    logger.info("Wrote report -> %s", target)
    return target
