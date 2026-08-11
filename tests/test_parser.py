"""Tests for yearly-list parsing.

The HTML fixtures reproduce the real geometry found on Wikipedia:
a ``colspan=2`` "Opening" header, letter-spaced month cells carrying large
``rowspan`` values, day cells spanning several films, and a production
column that also spans rows. Naive positional indexing fails all of these.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.parser import (  # noqa: E402
    MovieCandidate,
    build_table_grid,
    build_year_page_titles,
    deduplicate_candidates,
    extract_wiki_link,
    is_release_table,
    map_header_columns,
    parse_year_page,
)
from scraper.pipeline import _is_plausible_article  # noqa: E402

# Mirrors the 2023 layout: month rowspan=3, a day rowspan=2, and a
# production house shared by two consecutive films.
RELEASE_TABLE = """
<div id="mw-content-text"><div class="mw-parser-output">
<table class="wikitable">
<tr>
  <th colspan="2">Opening</th><th>Title</th><th>Director</th>
  <th>Cast</th><th>Production House</th><th>Ref.</th>
</tr>
<tr>
  <td rowspan="3">J A N U A R Y</td>
  <td rowspan="2">12</td>
  <td><a href="https://en.wikipedia.org/wiki/Veera_Simha_Reddy">Veera Simha Reddy</a></td>
  <td>Gopichand Malineni</td>
  <td><a href="/wiki/Nandamuri_Balakrishna">Nandamuri Balakrishna</a><br/>Shruti Haasan</td>
  <td rowspan="2">Mythri Movie Makers</td>
  <td>[17]</td>
</tr>
<tr>
  <td><a href="https://en.wikipedia.org/wiki/Waltair_Veerayya">Waltair Veerayya</a></td>
  <td>K. S. Ravindra</td>
  <td>Chiranjeevi<br/>Ravi Teja</td>
  <td>[18]</td>
</tr>
<tr>
  <td>26</td>
  <td>Hunt</td>
  <td>Mahesh Surapaneni</td>
  <td>Sudheer Babu</td>
  <td>Bhavya Creations</td>
  <td>[20]</td>
</tr>
</table>
</div></div>
"""

# Box-office tables also carry a Title column and must be rejected.
BOX_OFFICE_TABLE = """
<div id="mw-content-text"><div class="mw-parser-output">
<table class="wikitable">
<caption>Highest grossing Telugu films of 2023</caption>
<tr><th>Rank</th><th>Title</th><th>Production company</th><th>Worldwide gross</th></tr>
<tr><td>1</td><td>Waltair Veerayya</td><td>Mythri Movie Makers</td><td>&#8377;236 crore</td></tr>
</table>
</div></div>
"""

AWARDS_TABLE = """
<div id="mw-content-text"><div class="mw-parser-output">
<table class="wikitable">
<tr><th>Date</th><th>Event</th><th>Host</th><th>Location</th></tr>
<tr><td>1 Jan</td><td>SIIMA</td><td>Someone</td><td>Dubai</td></tr>
</table>
</div></div>
"""


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


class TestTableGrid:
    def test_rowspan_expands_into_every_covered_row(self) -> None:
        table = soup_of(RELEASE_TABLE).find("table")
        grid = build_table_grid(table)

        # Every row must be the same logical width despite differing <td> counts.
        widths = {len(row) for row in grid}
        assert widths == {7}

    def test_spanned_month_repeats_down_the_column(self) -> None:
        table = soup_of(RELEASE_TABLE).find("table")
        grid = build_table_grid(table)
        months = [row[0].get_text(" ", strip=True) for row in grid[1:]]
        assert months == ["J A N U A R Y"] * 3

    def test_title_column_stays_aligned_under_spans(self) -> None:
        # The regression this guards: on the second data row the month and
        # day cells are inherited, so a naive cells[2] would read the
        # director instead of the title.
        table = soup_of(RELEASE_TABLE).find("table")
        grid = build_table_grid(table)
        titles = [row[2].get_text(" ", strip=True) for row in grid[1:]]
        assert titles == ["Veera Simha Reddy", "Waltair Veerayya", "Hunt"]

    def test_shared_production_house_applies_to_both_films(self) -> None:
        table = soup_of(RELEASE_TABLE).find("table")
        grid = build_table_grid(table)
        houses = [row[5].get_text(" ", strip=True) for row in grid[1:]]
        assert houses[:2] == ["Mythri Movie Makers", "Mythri Movie Makers"]

    def test_malformed_span_does_not_crash(self) -> None:
        html = '<table><tr><td rowspan="abc">x</td><td>y</td></tr></table>'
        grid = build_table_grid(soup_of(html).find("table"))
        assert len(grid) == 1


class TestHeaderMapping:
    def test_colspan_header_offsets_later_columns(self) -> None:
        # "Opening" spans two columns, so Title sits at index 2, not 1.
        table = soup_of(RELEASE_TABLE).find("table")
        mapping, header_row = map_header_columns(build_table_grid(table))
        assert header_row == 0
        assert mapping["title"] == 2
        assert mapping["director"] == 3
        assert mapping["cast"] == 4
        assert mapping["production house"] == 5

    def test_accepts_release_table(self) -> None:
        table = soup_of(RELEASE_TABLE).find("table")
        mapping, _ = map_header_columns(build_table_grid(table))
        assert is_release_table(mapping) is True

    def test_rejects_box_office_table(self) -> None:
        table = soup_of(BOX_OFFICE_TABLE).find("table")
        mapping, _ = map_header_columns(build_table_grid(table))
        assert is_release_table(mapping) is False

    def test_rejects_awards_table(self) -> None:
        table = soup_of(AWARDS_TABLE).find("table")
        mapping, _ = map_header_columns(build_table_grid(table))
        assert is_release_table(mapping) is False


class TestWikiLinks:
    def test_reads_absolute_href(self) -> None:
        # Live pages emit absolute URLs; a /wiki/-only matcher finds nothing.
        cell = soup_of(
            '<td><a href="https://en.wikipedia.org/wiki/Waltair_Veerayya">W</a></td>'
        ).find("td")
        url, title = extract_wiki_link(cell)
        assert url == "https://en.wikipedia.org/wiki/Waltair_Veerayya"
        assert title == "Waltair Veerayya"

    def test_reads_relative_href(self) -> None:
        cell = soup_of('<td><a href="/wiki/Eega">Eega</a></td>').find("td")
        url, title = extract_wiki_link(cell)
        assert url == "https://en.wikipedia.org/wiki/Eega"
        assert title == "Eega"

    def test_ignores_red_links(self) -> None:
        cell = soup_of(
            '<td><a href="/w/index.php?title=X&amp;redlink=1">X</a></td>'
        ).find("td")
        assert extract_wiki_link(cell) == (None, None)

    def test_ignores_non_article_namespaces(self) -> None:
        cell = soup_of(
            '<td><a href="/wiki/Wikipedia:Citation_needed">c</a></td>'
        ).find("td")
        assert extract_wiki_link(cell) == (None, None)


class TestParseYearPage:
    def test_extracts_all_films(self) -> None:
        films = parse_year_page(RELEASE_TABLE, 2023)
        assert [f.movie_name for f in films] == [
            "Veera Simha Reddy",
            "Waltair Veerayya",
            "Hunt",
        ]

    def test_captures_crew_from_correct_columns(self) -> None:
        films = parse_year_page(RELEASE_TABLE, 2023)
        first = films[0]
        assert first.list_director == "Gopichand Malineni"
        assert first.list_cast == ["Nandamuri Balakrishna", "Shruti Haasan"]
        assert first.list_production_house == "Mythri Movie Makers"

    def test_reconstructs_release_date(self) -> None:
        films = parse_year_page(RELEASE_TABLE, 2023)
        assert films[0].release_date_text == "January 12"

    def test_unlinked_title_still_captured(self) -> None:
        # ~30% of listed films have no article; they must not be dropped here.
        hunt = parse_year_page(RELEASE_TABLE, 2023)[2]
        assert hunt.movie_name == "Hunt"
        assert hunt.wikipedia_url is None

    def test_box_office_table_contributes_nothing(self) -> None:
        assert parse_year_page(BOX_OFFICE_TABLE, 2023) == []

    def test_awards_table_contributes_nothing(self) -> None:
        assert parse_year_page(AWARDS_TABLE, 2023) == []


class TestDeduplication:
    def test_same_title_same_year_merges(self) -> None:
        rows = [
            MovieCandidate("Pokiri", 2006, "https://en.wikipedia.org/wiki/Pokiri"),
            MovieCandidate("pokiri", 2006, "https://en.wikipedia.org/wiki/Pokiri"),
        ]
        assert len(deduplicate_candidates(rows)) == 1

    def test_same_title_different_years_kept_apart(self) -> None:
        # Remakes and reused titles are different films.
        rows = [
            MovieCandidate("Postman", 2000),
            MovieCandidate("Postman", 2013),
        ]
        assert len(deduplicate_candidates(rows)) == 2

    def test_merge_prefers_populated_fields(self) -> None:
        rows = [
            MovieCandidate("Eega", 2012),
            MovieCandidate("Eega", 2012, list_director="S. S. Rajamouli"),
        ]
        merged = deduplicate_candidates(rows)
        assert len(merged) == 1
        assert merged[0].list_director == "S. S. Rajamouli"

    def test_alternate_spellings_sharing_a_url_merge(self) -> None:
        url = "https://en.wikipedia.org/wiki/Nenu_Sailaja"
        rows = [
            MovieCandidate("Nenu.. Sailaja...", 2016, url),
            MovieCandidate("Nenu Sailaja", 2016, url),
        ]
        assert len(deduplicate_candidates(rows)) == 1


class TestRedirectGuard:
    """A film with no article often redirects to an aggregate page.

    Following those blindly put rows like "List of Telugu films of 2020"
    into the dataset, so redirect targets are sanity-checked.
    """

    @pytest.mark.parametrize(
        "target,movie",
        [
            ("List of Telugu films of 2020", "Eureka"),
            ("List of Baahubali characters", "Sivudu"),
            ("List of One Piece characters", "Mr. 7"),
            ("List of programs broadcast by Star Maa", "Kanulu Moosina Neevaye"),
            ("Sukumar filmography", "Some Film"),
        ],
    )
    def test_rejects_aggregate_redirect_targets(self, target: str, movie: str) -> None:
        assert _is_plausible_article(target, movie) is False

    @pytest.mark.parametrize(
        "target,movie",
        [
            ("Yogi (2007 film)", "Yogi"),
            ("Annayya (2000 film)", "Annayya"),
            ("Eega", "Eega"),
            ("Nenu Sailaja", "Nenu.. Sailaja..."),
        ],
    )
    def test_accepts_genuine_article_targets(self, target: str, movie: str) -> None:
        assert _is_plausible_article(target, movie) is True

    def test_rejects_unrelated_article(self) -> None:
        assert _is_plausible_article("Zee Telugu", "Kalisundam Raa") is False


class TestYearPageTitles:
    def test_canonical_pattern_comes_first(self) -> None:
        assert build_year_page_titles(2015)[0] == "List of Telugu films of 2015"

    def test_provides_fallback_patterns(self) -> None:
        # Page names vary; a single hardcoded pattern is not acceptable.
        assert len(build_year_page_titles(2015)) > 1
