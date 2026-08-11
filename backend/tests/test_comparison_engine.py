"""Tests for the comparison engine.

Covers every case listed in the spec, plus the information-disclosure
guarantees: a losing guess must never leak the mystery movie's actual
year, director, or any other unshared value.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.comparison_engine import (  # noqa: E402
    Movie,
    Status,
    YearDirection,
    attribute_value,
    compare,
    compare_cast,
    compare_multi,
    compare_year,
    normalise,
)


def movie(**kwargs) -> Movie:
    defaults = dict(
        movie_id=1,
        title="Test Movie",
        year=2010,
        genres=("Drama",),
        cast=("Actor A", "Actor B"),
        directors=("Director X",),
        production_houses=("House Y",),
        music_directors=("Composer Z",),
        writers=("Writer W",),
    )
    defaults.update(kwargs)
    return Movie(**defaults)


class TestYear:
    def test_same_year_is_correct(self) -> None:
        result = compare_year(2010, 2010)
        assert result.status is Status.CORRECT
        assert result.direction is YearDirection.SAME
        assert result.mystery == 2010  # safe: player already knows it

    def test_mystery_earlier_than_guess(self) -> None:
        # Mystery 2005, guess 2010 -> "before 2010"
        result = compare_year(2010, 2005)
        assert result.direction is YearDirection.EARLIER
        assert result.status is Status.ABSENT

    def test_mystery_later_than_guess(self) -> None:
        # Mystery 2015, guess 2010 -> "after 2010"
        result = compare_year(2010, 2015)
        assert result.direction is YearDirection.LATER

    def test_mismatched_year_never_leaks_the_value(self) -> None:
        result = compare_year(2010, 2015)
        assert result.mystery is None
        assert "mystery" not in result.to_dict()

    def test_missing_year_is_unknown_not_a_crash(self) -> None:
        assert compare_year(None, 2010).status is Status.UNKNOWN
        assert compare_year(2010, None).status is Status.UNKNOWN


class TestGenre:
    def test_intersection_only(self) -> None:
        result = compare_multi(("Comedy", "Drama"), ("Action", "Drama"))
        assert result.common == ["Drama"]
        assert result.status is Status.PARTIAL

    def test_non_matching_genres_are_not_revealed(self) -> None:
        result = compare_multi(("Comedy", "Drama"), ("Action", "Drama"))
        assert "Action" not in result.common  # mystery-only value stays hidden

    def test_identical_sets_are_correct(self) -> None:
        result = compare_multi(("Action", "Drama"), ("Drama", "Action"))
        assert result.status is Status.CORRECT

    def test_no_overlap_is_absent(self) -> None:
        assert compare_multi(("Comedy",), ("Horror",)).status is Status.ABSENT

    def test_empty_side_is_unknown(self) -> None:
        assert compare_multi((), ("Drama",)).status is Status.UNKNOWN


class TestCast:
    def test_intersection_with_positions(self) -> None:
        # Mystery A|B|C, guess B|D|A -> A and B shared.
        result = compare_cast(("Actor B", "Actor D", "Actor A"),
                              ("Actor A", "Actor B", "Actor C"))
        names = [m.name for m in result.common]
        assert names == ["Actor B", "Actor A"]  # guess order

        by_name = {m.name: m for m in result.common}
        assert by_name["Actor B"].guess_position == 1
        assert by_name["Actor B"].mystery_position == 2
        assert by_name["Actor A"].guess_position == 3
        assert by_name["Actor A"].mystery_position == 1

    def test_unshared_actors_are_not_revealed(self) -> None:
        result = compare_cast(("Actor B",), ("Actor A", "Actor B", "Actor C"))
        names = [m.name for m in result.common]
        assert names == ["Actor B"]
        assert "Actor A" not in names and "Actor C" not in names

    def test_no_shared_cast(self) -> None:
        result = compare_cast(("Actor X",), ("Actor A",))
        assert result.common == []
        assert result.status is Status.ABSENT

    def test_empty_cast_is_unknown(self) -> None:
        assert compare_cast((), ("Actor A",)).status is Status.UNKNOWN

    def test_duplicate_actor_counted_once(self) -> None:
        result = compare_cast(("Actor A", "Actor A"), ("Actor A",))
        assert len(result.common) == 1

    def test_positions_are_deterministic(self) -> None:
        guess = ("Actor B", "Actor A")
        mystery = ("Actor A", "Actor B")
        first = compare_cast(guess, mystery)
        second = compare_cast(guess, mystery)
        assert [m.to_dict() for m in first.common] == [
            m.to_dict() for m in second.common
        ]


class TestCrew:
    def test_director_match(self) -> None:
        result = compare_multi(("Sukumar",), ("Sukumar",))
        assert result.status is Status.CORRECT
        assert result.common == ["Sukumar"]

    def test_director_mismatch_hides_mystery_name(self) -> None:
        result = compare_multi(("Rajamouli",), ("Sukumar",))
        assert result.common == []
        assert "Sukumar" not in result.to_dict()["guess"]
        assert result.status is Status.ABSENT

    def test_co_directors_partially_match(self) -> None:
        # The dataset really does have multi-director films.
        result = compare_multi(("A", "B"), ("B", "C"))
        assert result.common == ["B"]
        assert result.status is Status.PARTIAL


class TestNormalisation:
    @pytest.mark.parametrize(
        "left,right",
        [
            ("S. S. Rajamouli", "S S Rajamouli"),
            ("Devi Sri Prasad", "devi sri prasad"),
            ("Ileana D'Cruz", "Ileana DCruz"),
            ("Thaman  S", "Thaman S"),
        ],
    )
    def test_equivalent_spellings_match(self, left: str, right: str) -> None:
        assert normalise(left) == normalise(right)

    def test_distinct_names_do_not_match(self) -> None:
        assert normalise("Ram Charan") != normalise("Ram Pothineni")

    def test_display_value_keeps_original_spelling(self) -> None:
        result = compare_multi(("S. S. Rajamouli",), ("S S Rajamouli",))
        # Matching is fuzzy; what the player sees is not.
        assert result.common == ["S. S. Rajamouli"]


class TestCompare:
    def test_correct_guess_detected_by_id(self) -> None:
        mystery = movie(movie_id=42, title="Rangasthalam")
        result = compare(mystery, mystery)
        assert result.is_correct is True

    def test_same_title_different_movie_is_not_correct(self) -> None:
        # Reused titles across years must not collide.
        mystery = movie(movie_id=1, title="Postman", year=2000)
        guess = movie(movie_id=2, title="Postman", year=2013)
        assert compare(mystery, guess).is_correct is False

    def test_result_payload_shape(self) -> None:
        payload = compare(movie(movie_id=1), movie(movie_id=2)).to_dict()
        for key in (
            "year", "genre", "cast", "director",
            "production_house", "music_director", "writer",
        ):
            assert key in payload
        assert payload["is_correct"] is False

    def test_missing_metadata_does_not_crash(self) -> None:
        sparse = Movie(movie_id=2, title="Sparse")  # every field empty
        result = compare(movie(movie_id=1), sparse)
        assert result.year.status is Status.UNKNOWN
        assert result.cast.status is Status.UNKNOWN
        assert result.director.status is Status.UNKNOWN

    def test_losing_guess_leaks_nothing_unshared(self) -> None:
        mystery = movie(
            movie_id=1, year=2018, genres=("Thriller",), cast=("Secret Actor",),
            directors=("Secret Director",), production_houses=("Secret House",),
            music_directors=("Secret Composer",), writers=("Secret Writer",),
        )
        guess = movie(
            movie_id=2, year=2005, genres=("Comedy",), cast=("Other Actor",),
            directors=("Other Director",), production_houses=("Other House",),
            music_directors=("Other Composer",), writers=("Other Writer",),
        )
        blob = str(compare(mystery, guess).to_dict())
        for secret in (
            "Secret Actor", "Secret Director", "Secret House",
            "Secret Composer", "Secret Writer", "Thriller", "2018",
        ):
            assert secret not in blob

    def test_revealed_attributes_tracks_earned_clues(self) -> None:
        mystery = movie(movie_id=1, year=2010, directors=("Shared Director",))
        guess = movie(movie_id=2, year=2010, directors=("Shared Director",))
        revealed = compare(mystery, guess).revealed_attributes()
        assert "year" in revealed
        assert "director" in revealed


class TestFromDict:
    def test_parses_json_dataset_arrays(self) -> None:
        parsed = Movie.from_dict({
            "movie_id": 7, "movie_name": "Eega", "year": 2012,
            "genre": ["Fantasy", "Action"], "cast": ["Sudeepa", "Nani"],
            "director": ["S. S. Rajamouli"], "production_house": ["Vaaraahi"],
            "music_director": ["M. M. Keeravani"], "writer": ["S. S. Rajamouli"],
        })
        assert parsed.title == "Eega"
        assert parsed.genres == ("Fantasy", "Action")
        assert parsed.cast == ("Sudeepa", "Nani")

    def test_parses_pipe_separated_csv_strings(self) -> None:
        parsed = Movie.from_dict({
            "movie_id": 7, "movie_name": "Eega", "year": "2012",
            "genre": "Fantasy|Action", "cast": "Sudeepa|Nani",
            "director": "S. S. Rajamouli",
        })
        assert parsed.genres == ("Fantasy", "Action")
        assert parsed.cast == ("Sudeepa", "Nani")
        assert parsed.year == 2012

    def test_blank_values_become_empty(self) -> None:
        parsed = Movie.from_dict({
            "movie_id": 1, "movie_name": "X", "year": "", "genre": "", "cast": "",
        })
        assert parsed.year is None
        assert parsed.genres == ()


class TestAttributeValue:
    def test_reads_each_attribute(self) -> None:
        subject = movie(year=2018)
        assert attribute_value(subject, "year") == ["2018"]
        assert attribute_value(subject, "director") == ["Director X"]
        assert attribute_value(subject, "cast") == ["Actor A", "Actor B"]

    def test_unknown_attribute_rejected(self) -> None:
        with pytest.raises(ValueError):
            attribute_value(movie(), "budget")
