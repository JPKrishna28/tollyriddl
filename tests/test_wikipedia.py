"""Tests for the HTTP client: caching, rate limiting and error handling.

All network calls are mocked -- the suite never touches Wikipedia.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.wikipedia import WikipediaClient  # noqa: E402


def ok_response(text: str = "<html>page</html>") -> Mock:
    response = Mock(status_code=200, text=text, headers={})
    response.raise_for_status = Mock()
    return response


@pytest.fixture()
def client(tmp_path: Path) -> WikipediaClient:
    instance = WikipediaClient(cache_dir=tmp_path / "cache", min_delay=0, max_delay=0)
    yield instance
    instance.close()


class TestUrlHelpers:
    def test_title_to_url_encodes_spaces(self) -> None:
        assert (
            WikipediaClient.title_to_url("Pushpa: The Rise")
            == "https://en.wikipedia.org/wiki/Pushpa:_The_Rise"
        )

    def test_url_to_title_roundtrip(self) -> None:
        url = "https://en.wikipedia.org/wiki/Annayya_(2000_film)"
        assert WikipediaClient.url_to_title(url) == "Annayya (2000 film)"


class TestCaching:
    def test_second_fetch_serves_from_cache(self, client: WikipediaClient) -> None:
        with patch.object(client.session, "get", return_value=ok_response()) as get:
            first = client.fetch_html("https://en.wikipedia.org/wiki/Eega")
            second = client.fetch_html("https://en.wikipedia.org/wiki/Eega")

        # The whole point of the cache: re-runs cost no requests.
        assert get.call_count == 1
        assert first.from_cache is False
        assert second.from_cache is True
        assert second.html == first.html

    def test_force_refresh_bypasses_cache(self, client: WikipediaClient) -> None:
        with patch.object(client.session, "get", return_value=ok_response()) as get:
            client.fetch_html("https://en.wikipedia.org/wiki/Eega")
            client.fetch_html("https://en.wikipedia.org/wiki/Eega", force_refresh=True)
        assert get.call_count == 2

    def test_cache_can_be_disabled(self, tmp_path: Path) -> None:
        client = WikipediaClient(
            cache_dir=tmp_path / "c", use_cache=False, min_delay=0, max_delay=0
        )
        with patch.object(client.session, "get", return_value=ok_response()) as get:
            client.fetch_html("https://en.wikipedia.org/wiki/Eega")
            client.fetch_html("https://en.wikipedia.org/wiki/Eega")
        assert get.call_count == 2
        client.close()


class TestRateLimiting:
    def test_requests_are_spaced_apart(self, tmp_path: Path) -> None:
        client = WikipediaClient(
            cache_dir=tmp_path / "c", use_cache=False, min_delay=0.2, max_delay=0.25
        )
        with patch.object(client.session, "get", return_value=ok_response()):
            start = time.monotonic()
            for _ in range(3):
                client.fetch_html("https://en.wikipedia.org/wiki/X")
            elapsed = time.monotonic() - start

        # Three requests means at least two enforced gaps.
        assert elapsed >= 0.4
        client.close()


class TestErrorHandling:
    def test_429_backs_off_then_succeeds(self, client: WikipediaClient) -> None:
        attempts: list[int] = []

        def responder(*args, **kwargs) -> Mock:
            attempts.append(1)
            response = Mock(text="ok", headers={"Retry-After": "0"})
            response.status_code = 429 if len(attempts) < 3 else 200
            response.raise_for_status = Mock()
            return response

        with patch.object(client.session, "get", side_effect=responder):
            result = client.fetch_html("https://en.wikipedia.org/wiki/Y")

        assert result.status_code == 200
        assert len(attempts) == 3
        # The delay floor must rise so we stop provoking the rate limiter.
        assert client._throttle_penalty > 0
        assert client.stats["rate_limited"] == 2

    def test_permanent_404_is_not_retried(self, client: WikipediaClient) -> None:
        calls: list[int] = []

        def responder(*args, **kwargs) -> Mock:
            calls.append(1)
            response = Mock(status_code=404, text="", headers={})
            error = requests.exceptions.HTTPError("404")
            error.response = response
            response.raise_for_status = Mock(side_effect=error)
            return response

        with patch.object(client.session, "get", side_effect=responder):
            with pytest.raises(requests.exceptions.RequestException):
                client.fetch_html("https://en.wikipedia.org/wiki/Missing")

        assert len(calls) == 1

    def test_transient_error_is_retried(self, client: WikipediaClient) -> None:
        calls: list[int] = []

        def responder(*args, **kwargs):
            calls.append(1)
            if len(calls) < 2:
                raise requests.exceptions.ConnectionError("network down")
            return ok_response()

        with patch.object(client.session, "get", side_effect=responder):
            result = client.fetch_html("https://en.wikipedia.org/wiki/Flaky")

        assert result.status_code == 200
        assert len(calls) == 2


class TestBatchResolution:
    def test_follows_redirects_and_flags_missing(self, client: WikipediaClient) -> None:
        payload = {
            "query": {
                "normalized": [{"from": "eega", "to": "Eega"}],
                "redirects": [{"from": "Makkhi", "to": "Eega"}],
                "pages": [
                    {"title": "Eega"},
                    {"title": "No Such Film", "missing": True},
                ],
            }
        }
        with patch.object(client, "api_get", return_value=payload):
            resolved = client.resolve_titles_batch(["eega", "Makkhi", "No Such Film"])

        assert resolved["eega"] == "Eega"
        assert resolved["Makkhi"] == "Eega"
        assert resolved["No Such Film"] is None
