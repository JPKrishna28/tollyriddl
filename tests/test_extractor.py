"""Tests for movie-page extraction.

Fixtures reproduce infobox shapes observed live, including the two traps
found during recon:
  * "Dialogues by" is a separate credit and must never become the writer;
  * a bare film title can resolve to a completely different entity
    ("Balagam" is a village in Gujarat), which the film-type check catches.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.extractor import (  # noqa: E402
    MovieRecord,
    cell_values,
    extract_cast,
    extract_genres,
    extract_movie,
    extract_production_house,
    extract_release_date,
    extract_writer,
    is_film_infobox,
    parse_infobox,
)
from scraper.validator import assess_language, validate_record  # noqa: E402


def _page(infobox: str, categories: list[str], title: str = "Test Film") -> str:
    """Wrap an infobox and category list in a minimal article shell."""
    cats = "".join(f'<li><a href="/wiki/Category:{c}">{c}</a></li>' for c in categories)
    return f"""
    <h1 id="firstHeading">{title}</h1>
    <div id="mw-content-text"><div class="mw-parser-output">{infobox}</div></div>
    <div id="mw-normal-catlinks"><ul>{cats}</ul></div>
    """


FILM_INFOBOX = """
<table class="infobox vevent">
<tr><th>Directed by</th><td>Sukumar</td></tr>
<tr><th>Written by</th><td>Sukumar</td></tr>
<tr><th>Dialogues by</th><td>Srikanth Vissa</td></tr>
<tr><th>Produced by</th><td><div class="plainlist"><ul>
    <li>Naveen Yerneni</li><li>Yalamanchili Ravi Shankar</li></ul></div></td></tr>
<tr><th>Starring</th><td><div class="plainlist"><ul>
    <li>Allu Arjun</li><li>Rashmika Mandanna</li><li>Fahadh Faasil</li></ul></div></td></tr>
<tr><th>Cinematography</th><td>Miroslaw Kuba Brozek</td></tr>
<tr><th>Edited by</th><td>Karthika Srinivas</td></tr>
<tr><th>Music by</th><td>Devi Sri Prasad</td></tr>
<tr><th>Production companies</th><td><div class="plainlist"><ul>
    <li>Mythri Movie Makers</li><li>Muttamsetty Media</li></ul></div></td></tr>
<tr><th>Release date</th><td><span class="dtstart">2021-12-17</span> 17 December 2021</td></tr>
<tr><th>Country</th><td>India</td></tr>
<tr><th>Language</th><td>Telugu</td></tr>
</table>
"""

# A village infobox: same bare title, entirely different entity.
SETTLEMENT_INFOBOX = """
<table class="infobox ib-settlement vcard">
<tr><th>Country</th><td>India</td></tr>
<tr><th>State</th><td>Gujarat</td></tr>
<tr><th>District</th><td>Junagadh</td></tr>
</table>
"""

# Older/plainer film infobox with <br>-separated cast and no list markup.
BR_CAST_INFOBOX = """
<table class="infobox vevent">
<tr><th>Directed by</th><td>Venu Yeldandi</td></tr>
<tr><th>Screenplay by</th><td>Venu Yeldandi</td></tr>
<tr><th>Story by</th><td>Ramesh Eligeti</td></tr>
<tr><th>Starring</th><td>Priyadarshi<br/>Kavya Kalyanram<br/>Sudhakar Reddy</td></tr>
<tr><th>Music by</th><td>Bheems Ceciroleo</td></tr>
<tr><th>Production company</th><td>Dil Raju Productions</td></tr>
<tr><th>Language</th><td>Telugu</td></tr>
</table>
"""


def rows_of(html: str) -> dict:
    return parse_infobox(BeautifulSoup(html, "lxml").find("table"))


class TestInfoboxTypeDetection:
    def test_film_infobox_recognised(self) -> None:
        table = BeautifulSoup(FILM_INFOBOX, "lxml").find("table")
        assert is_film_infobox(table) is True

    def test_settlement_infobox_rejected(self) -> None:
        # This is what stops the Gujarat village entering the dataset.
        table = BeautifulSoup(SETTLEMENT_INFOBOX, "lxml").find("table")
        assert is_film_infobox(table) is False

    def test_missing_infobox_rejected(self) -> None:
        assert is_film_infobox(None) is False


class TestWriterExtraction:
    def test_dialogue_writer_is_not_the_writer(self) -> None:
        # The core misattribution guard from the spec.
        writers = extract_writer(rows_of(FILM_INFOBOX))
        assert writers == ["Sukumar"]
        assert "Srikanth Vissa" not in writers

    def test_cinematographer_and_editor_excluded(self) -> None:
        writers = extract_writer(rows_of(FILM_INFOBOX))
        assert "Miroslaw Kuba Brozek" not in writers
        assert "Karthika Srinivas" not in writers

    def test_screenplay_and_story_both_collected(self) -> None:
        writers = extract_writer(rows_of(BR_CAST_INFOBOX))
        assert writers == ["Venu Yeldandi", "Ramesh Eligeti"]


class TestCastExtraction:
    def test_reads_plainlist_items_in_order(self) -> None:
        assert extract_cast(rows_of(FILM_INFOBOX)) == [
            "Allu Arjun",
            "Rashmika Mandanna",
            "Fahadh Faasil",
        ]

    def test_reads_br_separated_cast(self) -> None:
        # Some film infoboxes carry no <li> markup at all.
        assert extract_cast(rows_of(BR_CAST_INFOBOX)) == [
            "Priyadarshi",
            "Kavya Kalyanram",
            "Sudhakar Reddy",
        ]

    def test_crew_never_leaks_into_cast(self) -> None:
        cast = extract_cast(rows_of(FILM_INFOBOX))
        for crew in ("Sukumar", "Devi Sri Prasad", "Naveen Yerneni"):
            assert crew not in cast


class TestProductionHouse:
    def test_prefers_company_over_producer_names(self) -> None:
        # "Produced by" lists people, not companies.
        houses = extract_production_house(rows_of(FILM_INFOBOX))
        assert houses == ["Mythri Movie Makers", "Muttamsetty Media"]
        assert "Naveen Yerneni" not in houses

    def test_falls_back_to_producer_when_no_company(self) -> None:
        html = """
        <table class="infobox vevent">
        <tr><th>Produced by</th><td>D. V. V. Danayya</td></tr>
        </table>
        """
        assert extract_production_house(rows_of(html)) == ["D. V. V. Danayya"]


class TestReleaseDate:
    def test_prefers_dtstart_microformat(self) -> None:
        soup = BeautifulSoup(FILM_INFOBOX, "lxml")
        date, year = extract_release_date(soup, rows_of(FILM_INFOBOX))
        assert date == "2021-12-17"
        assert year == 2021


class TestGenres:
    def test_mined_from_categories(self) -> None:
        # Infoboxes carry no Genre row, so categories are the only source.
        genres = extract_genres(["2021 action drama films", "2021 Telugu-language films"], {})
        assert "Action" in genres
        assert "Drama" in genres

    def test_ignores_subject_matter_categories(self) -> None:
        genres = extract_genres(
            ["Films about funerals", "Films directed by S. S. Rajamouli"], {}
        )
        assert genres == []

    def test_returns_empty_rather_than_guessing(self) -> None:
        assert extract_genres([], {}) == []


class TestExtractMovie:
    def test_full_film_page(self) -> None:
        html = _page(
            FILM_INFOBOX,
            ["2021 films", "2021 Telugu-language films", "2021 action drama films"],
            title="Pushpa: The Rise",
        )
        record = extract_movie(html, url="https://en.wikipedia.org/wiki/Pushpa:_The_Rise",
                               list_year=2021, fallback_title="Pushpa: The Rise")

        assert record.movie_name == "Pushpa: The Rise"
        assert record.year == 2021
        assert record.is_film is True
        assert record.director == ["Sukumar"]
        assert record.music_director == ["Devi Sri Prasad"]
        assert record.cast[0] == "Allu Arjun"
        assert "Action" in record.genre

    def test_year_discrepancy_flagged_not_overwritten(self) -> None:
        # The list page's year stays authoritative; the mismatch is recorded.
        html = _page(FILM_INFOBOX, ["2021 Telugu-language films"])
        record = extract_movie(html, url="https://en.wikipedia.org/wiki/X", list_year=2020)
        assert record.year == 2020
        assert record.infobox_year == 2021
        assert record.year_discrepancy is True
        assert record.notes

    def test_missing_fields_stay_empty(self) -> None:
        html = _page('<table class="infobox vevent"></table>', ["2005 films"])
        record = extract_movie(html, url="https://en.wikipedia.org/wiki/Y", list_year=2005)
        # Nothing may be invented for absent data.
        assert record.director == []
        assert record.cast == []
        assert record.music_director == []
        assert record.missing_fields()["director"] is True


class TestLanguageValidation:
    def test_telugu_category_gives_high_confidence(self) -> None:
        record = MovieRecord(
            movie_name="Eega", year=2012, language="Telugu", is_film=True,
            categories=["2012 Telugu-language films", "2012 films"],
            wikipedia_url="https://en.wikipedia.org/wiki/Eega",
        )
        result = assess_language(record)
        assert result.is_valid is True
        assert result.confidence == "high"

    def test_non_film_page_rejected(self) -> None:
        record = MovieRecord(
            movie_name="Balagam", year=2023, is_film=False,
            categories=["Cities and towns in Junagadh district"],
            wikipedia_url="https://en.wikipedia.org/wiki/Balagam",
        )
        result = assess_language(record)
        assert result.is_valid is False
        assert "Page does not describe a film" in result.reasons

    def test_other_language_film_rejected(self) -> None:
        record = MovieRecord(
            movie_name="Arjuna", year=2020, language="Kannada", is_film=True,
            categories=["2020 films", "Kannada-language films"],
            wikipedia_url="https://en.wikipedia.org/wiki/Arjuna_(film)",
        )
        assert assess_language(record).is_valid is False

    def test_list_page_reached_via_redirect_is_rejected(self) -> None:
        """A film-looking URL can still serve a list page.

        Some article titles are redirects to the yearly list; the URL looks
        innocent ("/wiki/Love_Cycle") while the served page -- and therefore
        the extracted title -- is "List of Telugu films of 2013". Only the
        parsed title reveals this, so validation checks it explicitly.
        """
        record = MovieRecord(
            movie_name="List of Telugu films of 2013",
            year=2013,
            language="Telugu",
            is_film=True,
            categories=["2013 Telugu-language films"],
            wikipedia_url="https://en.wikipedia.org/wiki/Love_Cycle",
        )
        result = validate_record(record)
        assert result.is_valid is False
        assert any("Aggregate" in reason for reason in result.reasons)

    def test_aggregate_url_also_rejected(self) -> None:
        record = MovieRecord(
            movie_name="Eureka",
            year=2020,
            language="Telugu",
            is_film=True,
            categories=["2020 Telugu-language films"],
            wikipedia_url="https://en.wikipedia.org/wiki/List_of_Telugu_films_of_2020",
        )
        assert validate_record(record).is_valid is False

    def test_year_outside_range_invalid(self) -> None:
        record = MovieRecord(
            movie_name="Old Film", year=1995, language="Telugu", is_film=True,
            categories=["1995 Telugu-language films"],
            wikipedia_url="https://en.wikipedia.org/wiki/Old_Film",
        )
        assert validate_record(record).is_valid is False

    def test_empty_name_invalid(self) -> None:
        record = MovieRecord(
            movie_name="", year=2010, language="Telugu", is_film=True,
            categories=["2010 Telugu-language films"],
            wikipedia_url="https://en.wikipedia.org/wiki/X",
        )
        assert validate_record(record).is_valid is False
