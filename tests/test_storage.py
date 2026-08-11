"""Tests for resume state and output writers.

Resume is a core requirement: a crash after N movies must restart at N+1,
never at zero. These tests exercise that by reopening the database, which
is exactly what a restarted process does.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.extractor import MovieRecord  # noqa: E402
from scraper.storage import (  # noqa: E402
    CSV_COLUMNS,
    ScraperState,
    records_to_rows,
    write_csv,
    write_json,
    write_missing_fields_csv,
)


@pytest.fixture()
def state(tmp_path: Path) -> ScraperState:
    store = ScraperState(tmp_path / "state.db")
    yield store
    store.close()


def make_record(name: str = "Eega", year: int = 2012, **kwargs) -> MovieRecord:
    defaults = dict(
        movie_name=name,
        year=year,
        language="Telugu",
        genre=["Fantasy", "Action"],
        cast=["Sudeepa", "Nani", "Samantha"],
        director=["S. S. Rajamouli"],
        production_house=["Vaaraahi Chalana Chitram"],
        music_director=["M. M. Keeravani"],
        writer=["S. S. Rajamouli"],
        wikipedia_url=f"https://en.wikipedia.org/wiki/{name.replace(' ', '_')}",
        language_confidence="high",
    )
    defaults.update(kwargs)
    return MovieRecord(**defaults)


class TestQueue:
    def test_add_movie_is_idempotent(self, state: ScraperState) -> None:
        url = "https://en.wikipedia.org/wiki/Eega"
        assert state.add_movie(url, "Eega", 2012) is True
        assert state.add_movie(url, "Eega", 2012) is False

    def test_pending_respects_limit_and_year(self, state: ScraperState) -> None:
        for index in range(5):
            state.add_movie(f"https://en.wikipedia.org/wiki/M{index}", f"M{index}", 2010)
        state.add_movie("https://en.wikipedia.org/wiki/N", "N", 2015)

        assert len(state.pending_movies(limit=3)) == 3
        assert len(state.pending_movies(years=[2015])) == 1


class TestResume:
    def test_completed_work_is_not_repeated_after_restart(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        first = ScraperState(db)
        for index in range(3):
            first.add_movie(
                f"https://en.wikipedia.org/wiki/M{index}", f"Movie {index}", 2010
            )
        first.mark_success(
            "https://en.wikipedia.org/wiki/M0",
            make_record("Movie 0", 2010),
            language_confidence="high",
            is_valid=True,
        )
        first.close()

        # A fresh process opening the same database must skip Movie 0.
        second = ScraperState(db)
        pending = [row["movie_name"] for row in second.pending_movies()]
        assert pending == ["Movie 1", "Movie 2"]
        assert second.stats()["success"] == 1
        second.close()

    def test_payload_survives_restart(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        first = ScraperState(db)
        url = "https://en.wikipedia.org/wiki/Eega"
        first.add_movie(url, "Eega", 2012)
        first.mark_success(
            url, make_record(), language_confidence="high", is_valid=True
        )
        first.close()

        second = ScraperState(db)
        records = second.load_records()
        assert len(records) == 1
        assert records[0].cast == ["Sudeepa", "Nani", "Samantha"]
        second.close()

    def test_failures_are_recorded_and_retryable(self, state: ScraperState) -> None:
        url = "https://en.wikipedia.org/wiki/Broken"
        state.add_movie(url, "Broken", 2011)
        state.mark_failed(url, "connection timeout")

        failed = state.failed_movies()
        assert len(failed) == 1
        assert "timeout" in failed[0]["error"]
        assert failed[0]["attempts"] == 1

        assert state.reset_failed() == 1
        assert len(state.pending_movies()) == 1

    def test_invalid_records_are_kept_not_discarded(self, state: ScraperState) -> None:
        # Nothing may be silently dropped; rejects stay auditable.
        url = "https://en.wikipedia.org/wiki/Arjuna_(film)"
        state.add_movie(url, "Arjuna", 2020)
        state.mark_success(
            url,
            make_record("Arjuna", 2020, language="Kannada"),
            language_confidence="low",
            is_valid=False,
        )
        assert state.load_records(only_valid=True) == []
        assert len(state.load_records(only_valid=False)) == 1


class TestOutputs:
    def test_csv_uses_pipe_separator_and_schema(self, tmp_path: Path) -> None:
        target = write_csv([make_record()], tmp_path / "out.csv")
        with target.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        assert list(rows[0]) == CSV_COLUMNS
        assert rows[0]["cast"] == "Sudeepa|Nani|Samantha"
        assert rows[0]["genre"] == "Fantasy|Action"
        assert rows[0]["language"] == "Telugu"

    def test_json_keeps_arrays_structural(self, tmp_path: Path) -> None:
        target = write_json([make_record()], tmp_path / "out.json")
        payload = json.loads(target.read_text(encoding="utf-8"))

        # The game needs arrays, not delimited strings.
        assert payload[0]["cast"] == ["Sudeepa", "Nani", "Samantha"]
        assert payload[0]["genre"] == ["Fantasy", "Action"]
        assert payload[0]["movie_id"] == 1

    def test_ids_are_sequential_and_sorted_by_year(self) -> None:
        rows = records_to_rows(
            [make_record("Later", 2015), make_record("Earlier", 2001)]
        )
        assert [row["movie_id"] for row in rows] == [1, 2]
        assert [row["movie_name"] for row in rows] == ["Earlier", "Later"]

    def test_empty_fields_render_as_empty_not_invented(self, tmp_path: Path) -> None:
        sparse = make_record("Sparse", 2003, genre=[], writer=[], music_director=[])
        target = write_csv([sparse], tmp_path / "sparse.csv")
        row = list(csv.DictReader(target.open(encoding="utf-8")))[0]

        assert row["genre"] == ""
        assert row["writer"] == ""
        assert row["music_director"] == ""

    def test_missing_fields_csv_lists_only_incomplete_records(
        self, tmp_path: Path
    ) -> None:
        complete = make_record("Complete", 2012)
        sparse = make_record("Sparse", 2013, genre=[], cast=[])
        target = write_missing_fields_csv([complete, sparse], tmp_path / "missing.csv")
        rows = list(csv.DictReader(target.open(encoding="utf-8")))

        assert len(rows) == 1
        assert rows[0]["movie_name"] == "Sparse"
        assert rows[0]["missing_genre"] == "1"
        assert rows[0]["missing_director"] == "0"
