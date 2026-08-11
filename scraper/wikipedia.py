"""Polite Wikipedia HTTP client with on-disk caching.

Responsibilities:
  * rate limiting (jittered 1-2s between live requests)
  * retries with exponential backoff
  * adaptive slow-down on HTTP 429
  * on-disk HTML cache so the parser can be re-run for free
  * MediaWiki API helpers (title resolution, search, categories, Wikidata)

Cached pages never hit the network again, so re-running the scraper while
improving the parser costs nothing and puts zero extra load on Wikipedia.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from requests.exceptions import HTTPError, RequestException

from config.settings import settings

logger = logging.getLogger(__name__)


class RateLimitedError(RequestException):
    """Raised when Wikipedia answers 429 and retries are exhausted."""


@dataclass
class FetchResult:
    """Outcome of a page fetch."""

    url: str
    html: str
    from_cache: bool
    status_code: int = 200


class WikipediaClient:
    """Thread-safe-ish polite client. Intended for single-threaded use."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        *,
        use_cache: bool = True,
        min_delay: float | None = None,
        max_delay: float | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir or settings.cache_dir)
        self.use_cache = use_cache and settings.cache_enabled
        self.min_delay = settings.min_delay if min_delay is None else min_delay
        self.max_delay = settings.max_delay if max_delay is None else max_delay
        # Grows when we are told to slow down; never shrinks within a run.
        self._throttle_penalty = 0.0
        self._last_request_ts = 0.0
        self._lock = threading.Lock()

        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": settings.user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
        )

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.stats: dict[str, int] = {
            "requests": 0,
            "cache_hits": 0,
            "errors": 0,
            "rate_limited": 0,
        }

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------
    def _cache_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        # Two-level fan-out keeps directory sizes sane across ~3k pages.
        sub = self.cache_dir / digest[:2]
        sub.mkdir(parents=True, exist_ok=True)
        return sub / f"{digest}.html"

    def _read_cache(self, key: str) -> str | None:
        if not self.use_cache:
            return None
        path = self._cache_path(key)
        if not path.exists():
            return None
        if settings.cache_ttl_days is not None:
            age_days = (time.time() - path.stat().st_mtime) / 86400
            if age_days > settings.cache_ttl_days:
                return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - disk level failure
            logger.warning("Cache read failed for %s: %s", key, exc)
            return None

    def _write_cache(self, key: str, content: str) -> None:
        if not self.use_cache:
            return
        try:
            self._cache_path(key).write_text(content, encoding="utf-8")
        except OSError as exc:  # pragma: no cover - disk level failure
            logger.warning("Cache write failed for %s: %s", key, exc)

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    def _respect_rate_limit(self) -> None:
        """Sleep so consecutive live requests stay >= the configured gap."""
        with self._lock:
            base = random.uniform(self.min_delay, self.max_delay)
            delay = base + self._throttle_penalty
            elapsed = time.monotonic() - self._last_request_ts
            if self._last_request_ts and elapsed < delay:
                time.sleep(delay - elapsed)
            self._last_request_ts = time.monotonic()

    def _register_throttle(self, retry_after: float | None) -> float:
        """Escalate the delay floor after a 429 and return the wait time."""
        self.stats["rate_limited"] += 1
        self._throttle_penalty = min(
            self._throttle_penalty + settings.throttle_penalty,
            settings.throttle_penalty_max,
        )
        wait = retry_after if retry_after is not None else self._throttle_penalty
        logger.warning(
            "HTTP 429 from Wikipedia - backing off %.1fs (floor now +%.1fs)",
            wait,
            self._throttle_penalty,
        )
        return wait

    # ------------------------------------------------------------------
    # Core request
    # ------------------------------------------------------------------
    def _request(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        expect_json: bool = False,
    ) -> requests.Response:
        """Perform a live request with retries and exponential backoff."""
        last_error: Exception | None = None

        for attempt in range(1, settings.max_retries + 1):
            self._respect_rate_limit()
            try:
                self.stats["requests"] += 1
                response = self.session.get(
                    url, params=params, timeout=settings.request_timeout
                )

                if response.status_code == 429:
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                    wait = self._register_throttle(retry_after)
                    if attempt == settings.max_retries:
                        raise RateLimitedError(f"429 after {attempt} attempts: {url}")
                    time.sleep(wait)
                    continue

                # 5xx are transient; retry. 4xx (except 429) are permanent.
                if response.status_code >= 500:
                    raise HTTPError(
                        f"server error {response.status_code}", response=response
                    )

                response.raise_for_status()

                if expect_json:
                    # A JSON endpoint returning HTML means we were served an
                    # error page; treat as retryable rather than crashing.
                    response.json()

                return response

            except RateLimitedError:
                raise
            except (RequestException, ValueError) as exc:
                last_error = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is not None and 400 <= status < 500 and status != 429:
                    logger.error("Permanent HTTP %s for %s", status, url)
                    raise
                if attempt == settings.max_retries:
                    break
                backoff = min(
                    settings.backoff_factor ** (attempt - 1), settings.backoff_max
                )
                backoff += random.uniform(0, 0.5)  # jitter avoids lockstep retries
                logger.warning(
                    "Request failed (attempt %d/%d) for %s: %s - retrying in %.1fs",
                    attempt,
                    settings.max_retries,
                    url,
                    exc,
                    backoff,
                )
                time.sleep(backoff)

        self.stats["errors"] += 1
        raise RequestException(
            f"Failed after {settings.max_retries} attempts: {url} ({last_error})"
        ) from last_error

    # ------------------------------------------------------------------
    # Public fetch helpers
    # ------------------------------------------------------------------
    def fetch_html(self, url: str, *, force_refresh: bool = False) -> FetchResult:
        """Fetch a page's HTML, using the on-disk cache when possible."""
        if not force_refresh:
            cached = self._read_cache(url)
            if cached is not None:
                self.stats["cache_hits"] += 1
                logger.debug("Cache hit: %s", url)
                return FetchResult(url=url, html=cached, from_cache=True)

        logger.debug("Fetching: %s", url)
        response = self._request(url)
        self._write_cache(url, response.text)
        return FetchResult(
            url=url,
            html=response.text,
            from_cache=False,
            status_code=response.status_code,
        )

    def fetch_page_by_title(
        self, title: str, *, force_refresh: bool = False
    ) -> FetchResult:
        """Fetch an article by its Wikipedia title."""
        return self.fetch_html(self.title_to_url(title), force_refresh=force_refresh)

    # ------------------------------------------------------------------
    # MediaWiki API
    # ------------------------------------------------------------------
    def api_get(self, params: dict[str, Any], *, endpoint: str | None = None) -> dict:
        """Call the MediaWiki API with caching keyed on the query itself."""
        url = endpoint or settings.api_endpoint
        query = {"format": "json", "formatversion": "2", **params}
        cache_key = f"API::{url}::{json.dumps(query, sort_keys=True)}"

        cached = self._read_cache(cache_key)
        if cached is not None:
            self.stats["cache_hits"] += 1
            try:
                return json.loads(cached)
            except json.JSONDecodeError:
                logger.debug("Corrupt API cache entry, refetching: %s", cache_key)

        response = self._request(url, params=query, expect_json=True)
        payload = response.json()
        self._write_cache(cache_key, json.dumps(payload))
        return payload

    def resolve_title(self, title: str) -> str | None:
        """Resolve a title to its canonical form, following redirects.

        Returns None when the page does not exist, so callers never
        fabricate a URL for an article that was never written.
        """
        try:
            data = self.api_get(
                {"action": "query", "titles": title, "redirects": 1}
            )
        except RequestException as exc:
            logger.warning("Title resolution failed for %r: %s", title, exc)
            return None

        pages = data.get("query", {}).get("pages", [])
        if not pages:
            return None
        page = pages[0]
        if page.get("missing") or page.get("invalid"):
            return None
        return page.get("title")

    def resolve_titles_batch(self, titles: list[str]) -> dict[str, str | None]:
        """Resolve up to 50 titles per API call.

        The query API accepts a pipe-joined title list, so one round trip
        replaces N. Returns ``{requested_title: canonical_title_or_None}``,
        following redirects and normalisations.
        """
        resolved: dict[str, str | None] = {}
        unique = [t for t in dict.fromkeys(titles) if t]

        for start in range(0, len(unique), 50):
            chunk = unique[start : start + 50]
            try:
                data = self.api_get(
                    {"action": "query", "titles": "|".join(chunk), "redirects": 1}
                )
            except RequestException as exc:
                logger.warning("Batch title resolution failed: %s", exc)
                for title in chunk:
                    resolved[title] = None
                continue

            query = data.get("query", {})
            # MediaWiki rewrites titles it normalised/redirected; chain the
            # mappings so the caller's original string finds its target.
            alias: dict[str, str] = {}
            for entry in query.get("normalized", []):
                alias[entry["from"]] = entry["to"]
            for entry in query.get("redirects", []):
                alias[entry["from"]] = entry["to"]

            existing = {
                page["title"]
                for page in query.get("pages", [])
                if not page.get("missing") and not page.get("invalid")
            }

            for title in chunk:
                target = title
                # Follow at most a few hops to avoid redirect loops.
                for _ in range(4):
                    if target in alias:
                        target = alias[target]
                    else:
                        break
                resolved[title] = target if target in existing else None

        return resolved

    def search_title(self, query: str, *, limit: int = 5) -> list[str]:
        """Full-text search fallback for when direct title lookup fails."""
        try:
            data = self.api_get(
                {
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": limit,
                    "srnamespace": 0,
                }
            )
        except RequestException as exc:
            logger.warning("Search failed for %r: %s", query, exc)
            return []
        return [hit["title"] for hit in data.get("query", {}).get("search", [])]

    def get_categories(self, title: str) -> list[str]:
        """Return category names (without the 'Category:' prefix)."""
        try:
            data = self.api_get(
                {
                    "action": "query",
                    "titles": title,
                    "prop": "categories",
                    "cllimit": "max",
                    "clshow": "!hidden",
                    "redirects": 1,
                }
            )
        except RequestException as exc:
            logger.warning("Category lookup failed for %r: %s", title, exc)
            return []

        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            return []
        return [
            category["title"].removeprefix("Category:")
            for category in pages[0].get("categories", [])
        ]

    def get_wikidata_entity(self, title: str) -> dict | None:
        """Fetch the Wikidata entity backing an article, if any."""
        if not settings.wikidata_enabled:
            return None
        try:
            data = self.api_get(
                {
                    "action": "query",
                    "titles": title,
                    "prop": "pageprops",
                    "ppprop": "wikibase_item",
                    "redirects": 1,
                }
            )
            pages = data.get("query", {}).get("pages", [])
            if not pages:
                return None
            entity_id = pages[0].get("pageprops", {}).get("wikibase_item")
            if not entity_id:
                return None

            entity_data = self.api_get(
                {"action": "wbgetentities", "ids": entity_id, "props": "claims"},
                endpoint=settings.wikidata_api,
            )
            return entity_data.get("entities", {}).get(entity_id)
        except RequestException as exc:
            logger.warning("Wikidata lookup failed for %r: %s", title, exc)
            return None

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------
    @staticmethod
    def title_to_url(title: str) -> str:
        """Build a canonical article URL from a title."""
        slug = urllib.parse.quote(title.replace(" ", "_"), safe=":/()',.!-&$")
        return f"{settings.wiki_base}{slug}"

    @staticmethod
    def url_to_title(url: str) -> str:
        """Recover an article title from its URL."""
        path = urllib.parse.urlparse(url).path
        slug = path.rsplit("/wiki/", 1)[-1] if "/wiki/" in path else path.lstrip("/")
        return urllib.parse.unquote(slug).replace("_", " ")

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "WikipediaClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header expressed in seconds."""
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        # HTTP-date form; a fixed conservative pause is good enough here.
        return 60.0
