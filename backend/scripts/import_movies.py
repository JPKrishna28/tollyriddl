#!/usr/bin/env python3
"""Import the scraped Telugu movie dataset into the database.

Adapted to the dataset this repository actually produces:

  * CSV  -- multi-value fields are pipe-separated ("Action|Drama")
  * JSON -- multi-value fields are real arrays

Both are accepted; the format is detected from the file extension.

Usage:
    python scripts/import_movies.py --file ../output/telugu_movies_2000_2023.csv
    python scripts/import_movies.py --file ../output/telugu_movies_2000_2023.json --reset
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import create_all, get_session_factory  # noqa: E402
from app.models import Movie, MovieCast, MovieGenre  # noqa: E402
from app.services.daily_movie import is_eligible, quality_score  # noqa: E402
from app.services.movie_service import normalize_title  # noqa: E402

REQUIRED_COLUMNS = {"movie_name", "year"}


@dataclass
class ImportStats:
    movies_imported: int = 0
    movies_updated: int = 0
    genres_imported: int = 0
    cast_imported: int = 0
    duplicates_skipped: int = 0
    invalid_rows: int = 0
    eligible: int = 0
    problems: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = [
            "",
            "=" * 46,
            "DATASET IMPORT SUMMARY",
            "=" * 46,
            "",
            f"Movies imported:     {self.movies_imported:,}",
            f"Movies updated:      {self.movies_updated:,}",
            f"Genres imported:     {self.genres_imported:,}",
            f"Cast records:        {self.cast_imported:,}",
            f"Duplicates skipped:  {self.duplicates_skipped:,}",
            f"Invalid rows:        {self.invalid_rows:,}",
            f"Puzzle-eligible:     {self.eligible:,}",
            "",
            "=" * 46,
        ]
        if self.problems:
            lines.append("")
            lines.append(f"First {min(len(self.problems), 10)} problems:")
            lines.extend(f"  - {problem}" for problem in self.problems[:10])
        return "\n".join(lines)


def split_values(value: Any) -> list[str]:
    """Normalise a multi-value field from either CSV or JSON form."""
    if value is None:
        return []
    if isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        items = [part.strip() for part in str(value).split("|")]

    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue  # same name twice in one field adds nothing
        seen.add(key)
        out.append(item)
    return out


def join_values(values: list[str]) -> str | None:
    return "|".join(values) if values else None


def read_rows(path: Path) -> Iterator[dict[str, Any]]:
    """Yield raw rows from a CSV or JSON dataset."""
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise SystemExit("JSON dataset must be an array of movie objects")
        yield from payload
        return

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(
                f"Dataset is missing required column(s): {', '.join(sorted(missing))}"
            )
        yield from reader


def parse_year(value: Any) -> int | None:
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return year if 1900 < year < 2100 else None


def import_dataset(path: Path, *, reset: bool = False) -> ImportStats:
    stats = ImportStats()
    create_all()
    factory = get_session_factory()

    with factory() as session:
        if reset:
            # Children first: FK cascades are not guaranteed on SQLite.
            session.execute(delete(MovieCast))
            session.execute(delete(MovieGenre))
            session.execute(delete(Movie))
            session.commit()
            print("Cleared existing movie tables.")

        seen_keys: set[tuple[str, int | None]] = set()

        for index, row in enumerate(read_rows(path), start=2):
            title = str(row.get("movie_name") or row.get("title") or "").strip()
            if not title:
                stats.invalid_rows += 1
                stats.problems.append(f"row {index}: empty movie_name")
                continue

            year = parse_year(row.get("year"))
            if year is None:
                stats.invalid_rows += 1
                stats.problems.append(f"row {index}: bad year for {title!r}")
                continue

            normalized = normalize_title(title)
            key = (normalized, year)
            if key in seen_keys:
                stats.duplicates_skipped += 1
                continue
            seen_keys.add(key)

            genres = split_values(row.get("genre") or row.get("genres"))
            cast = split_values(row.get("cast"))
            directors = split_values(row.get("director") or row.get("directors"))
            houses = split_values(row.get("production_house"))
            music = split_values(row.get("music_director"))
            writers = split_values(row.get("writer") or row.get("writers"))

            score = quality_score(
                year=year,
                genres=genres,
                cast=cast,
                director=join_values(directors),
                production_house=join_values(houses),
                music_director=join_values(music),
                writer=join_values(writers),
            )
            eligible = is_eligible(
                year=year,
                genres=genres,
                cast=cast,
                director=join_values(directors),
                score=score,
            )

            existing = session.execute(
                select(Movie).where(
                    Movie.normalized_title == normalized, Movie.year == year
                )
            ).scalar_one_or_none()

            if existing is not None:
                # Re-running the importer refreshes metadata instead of
                # inserting a second copy of the same film.
                existing.title = title
                existing.language = str(row.get("language") or "Telugu").strip() or "Telugu"
                existing.director = join_values(directors)
                existing.production_house = join_values(houses)
                existing.music_director = join_values(music)
                existing.writer = join_values(writers)
                existing.wikipedia_url = str(row.get("wikipedia_url") or "").strip() or None
                existing.quality_score = score
                existing.is_eligible = eligible

                existing.genres.clear()
                existing.cast.clear()
                session.flush()
                movie = existing
                stats.movies_updated += 1
            else:
                movie = Movie(
                    title=title,
                    normalized_title=normalized,
                    year=year,
                    language=str(row.get("language") or "Telugu").strip() or "Telugu",
                    director=join_values(directors),
                    production_house=join_values(houses),
                    music_director=join_values(music),
                    writer=join_values(writers),
                    wikipedia_url=str(row.get("wikipedia_url") or "").strip() or None,
                    quality_score=score,
                    is_eligible=eligible,
                )
                session.add(movie)
                session.flush()
                stats.movies_imported += 1

            for genre in genres:
                session.add(MovieGenre(movie_id=movie.id, genre=genre))
                stats.genres_imported += 1

            # Billing order is preserved exactly as scraped -- it is a
            # deduction signal in the game, so it must be deterministic.
            for position, actor in enumerate(cast, start=1):
                session.add(
                    MovieCast(
                        movie_id=movie.id, actor_name=actor, cast_position=position
                    )
                )
                stats.cast_imported += 1

            if eligible:
                stats.eligible += 1

            if (stats.movies_imported + stats.movies_updated) % 200 == 0:
                session.commit()

        session.commit()

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Import the Telugu movie dataset.")
    parser.add_argument(
        "--file",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "output" / "telugu_movies_2000_2023.csv",
        help="Path to the dataset CSV or JSON",
    )
    parser.add_argument(
        "--reset", action="store_true", help="Delete existing movie rows first"
    )
    args = parser.parse_args()

    if not args.file.exists():
        print(f"Dataset not found: {args.file}", file=sys.stderr)
        return 1

    print(f"Importing {args.file} ...")
    stats = import_dataset(args.file, reset=args.reset)
    print(stats.report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
