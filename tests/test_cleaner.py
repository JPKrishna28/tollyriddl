"""Tests for text normalisation.

Fixtures are real strings observed on Wikipedia during the structure recon,
not invented examples.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.cleaner import (  # noqa: E402
    clean_name,
    clean_text,
    dedupe_preserving_order,
    is_cross_reference,
    is_placeholder,
    normalise_key,
    normalise_label,
    normalise_title,
    split_values,
)


class TestCleanText:
    @pytest.mark.parametrize(
        "raw",
        ["Mahesh Babu ", " Mahesh Babu", "Mahesh Babu\n", "Mahesh  Babu", "\tMahesh Babu "],
    )
    def test_whitespace_variants_normalise(self, raw: str) -> None:
        assert clean_text(raw) == "Mahesh Babu"

    def test_strips_nbsp(self) -> None:
        assert clean_text("Production\xa0house") == "Production house"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("160 minutes [ 1 ]", "160 minutes"),
            ("Devi Sri Prasad[12]", "Devi Sri Prasad"),
            ("Sukumar [ a ]", "Sukumar"),
            ("Rajamouli [note 2]", "Rajamouli"),
        ],
    )
    def test_removes_citation_markers(self, raw: str, expected: str) -> None:
        assert clean_text(raw) == expected

    def test_removes_edit_artifacts(self) -> None:
        assert clean_text("Cast [edit]") == "Cast"

    def test_drops_redundant_iso_date(self) -> None:
        # Wikipedia's date template renders both forms; keep the readable one.
        assert clean_text("12 January 2020 ( 2020-01-12 )") == "12 January 2020"

    @pytest.mark.parametrize(
        "name",
        [
            "S. S. Rajamouli",
            "Nenu.. Sailaja...",
            "Haarika & Hassine Creations",
            "N.T.R: Kathanayakudu",
            "Ileana D'Cruz",
        ],
    )
    def test_preserves_legitimate_punctuation(self, name: str) -> None:
        assert clean_text(name) == name

    def test_handles_none_and_empty(self) -> None:
        assert clean_text(None) == ""
        assert clean_text("") == ""


class TestPlaceholders:
    @pytest.mark.parametrize(
        "raw", ["", "  ", "-", "—", "N/A", "TBA", "unknown", "[ citation needed ]", "none"]
    )
    def test_detects_placeholders(self, raw: str) -> None:
        assert is_placeholder(raw) is True

    @pytest.mark.parametrize("raw", ["Mahesh Babu", "Geetha Arts", "3 Monkeys"])
    def test_real_values_are_not_placeholders(self, raw: str) -> None:
        assert is_placeholder(raw) is False

    def test_detects_cross_references(self) -> None:
        # "see below" would read as a real name downstream.
        assert is_cross_reference("see below") is True
        assert is_cross_reference("see distribution") is True
        assert is_cross_reference("Mythri Movie Makers") is False


class TestSplitValues:
    def test_splits_br_separated_cast(self) -> None:
        # Balagam (film) renders its cast with <br>, not <li>.
        raw = "Priyadarshi\nKavya Kalyanram\nSudhakar Reddy"
        assert split_values(raw) == [
            "Priyadarshi",
            "Kavya Kalyanram",
            "Sudhakar Reddy",
        ]

    def test_splits_on_comma_and_conjunction(self) -> None:
        raw = "Bobby Kolli, Kona Venkat and K. Chakravarthy Reddy"
        assert split_values(raw) == [
            "Bobby Kolli",
            "Kona Venkat",
            "K. Chakravarthy Reddy",
        ]

    def test_keeps_ampersand_inside_company_name(self) -> None:
        # Splitting on "&" would destroy this real production house.
        assert split_values("Haarika & Hassine Creations") == [
            "Haarika & Hassine Creations"
        ]

    def test_keeps_initials_together(self) -> None:
        assert split_values("S. S. Rajamouli") == ["S. S. Rajamouli"]

    def test_empty_input(self) -> None:
        assert split_values("") == []
        assert split_values(None) == []


class TestCleanName:
    def test_strips_role_annotation(self) -> None:
        assert clean_name("Prakash Raj (special appearance)") == "Prakash Raj"

    def test_strips_leading_bullet(self) -> None:
        assert clean_name("• Ravi Teja") == "Ravi Teja"


class TestDedupe:
    def test_removes_case_insensitive_duplicates(self) -> None:
        values = ["Ravi Teja", "ravi teja", "Prakash Raj"]
        assert dedupe_preserving_order(values) == ["Ravi Teja", "Prakash Raj"]

    def test_preserves_billing_order(self) -> None:
        # Cast order is a real signal for the game; it must survive.
        values = ["Allu Arjun", "Rashmika Mandanna", "Fahadh Faasil"]
        assert dedupe_preserving_order(values) == values


class TestNormalisation:
    def test_normalise_key_ignores_punctuation(self) -> None:
        assert normalise_key("Nenu.. Sailaja...") == normalise_key("Nenu Sailaja")

    def test_normalise_key_distinguishes_real_differences(self) -> None:
        assert normalise_key("Pokiri") != normalise_key("Pokkiri")

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Annayya (2000 film)", "Annayya"),
            ("Balagam (film)", "Balagam"),
            ("Red (2021 film)", "Red"),
            ("RRR (film)", "RRR"),
            ("Pushpa: The Rise", "Pushpa: The Rise"),
        ],
    )
    def test_normalise_title_strips_disambiguators(self, raw: str, expected: str) -> None:
        assert normalise_title(raw) == expected

    def test_normalise_label(self) -> None:
        assert normalise_label("Production\xa0house") == "production house"
        assert normalise_label("Music by") == "music by"
        assert normalise_label("Directed by:") == "directed by"
