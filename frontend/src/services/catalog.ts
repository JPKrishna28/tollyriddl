// Client-side movie catalogue.
//
// The autocomplete used to hit /api/movies/search on every keystroke, which
// put a network round trip between typing and seeing a result. The catalogue
// is static (id/title/year only -- no cast or crew), so it is fetched once and
// searched locally instead.
//
// The ranking below deliberately mirrors `search_movies` in
// backend/app/services/movie_service.py. If that ordering changes, change it
// here too, or the same query will rank differently in the two places.

import type { MovieSearchItem } from '@/types/game';

/** [id, title, normalizedTitle, year] -- arrays, to keep the payload small. */
type CatalogRow = [number, string, string, number | null];

interface CatalogResponse {
  version: string;
  movies: CatalogRow[];
}

interface IndexEntry {
  id: number;
  title: string;
  normalized: string;
  /** normalized with spaces stripped, for "R.R.R." -> "rrr" style matches. */
  compact: string;
  year: number | null;
}

const YEAR_IN_QUERY = /\b(19|20)\d{2}\b/;

/**
 * Port of `normalize_title` in backend/app/services/movie_service.py.
 *
 * Output must match the Python version exactly, since it is compared against
 * the `normalized_title` the server computed at import time. Two details are
 * load-bearing and easy to get wrong:
 *
 *  - Python strips marks with `unicodedata.combining(ch)`, which is *nonzero
 *    only for canonical-combining-class marks*. Telugu vowel signs (Mc/Mn,
 *    e.g. TELUGU VOWEL SIGN U) have combining class 0, so Python keeps them
 *    here. A JS `\p{M}` filter would delete them and diverge.
 *  - Those same vowel signs are not `str.isalnum()` in Python, so the next
 *    step turns them into spaces -- which is why a Telugu title normalises
 *    into fragments ("అల వైకుంఠపురములో" -> "అల వ క ఠప రమ ల"). That is the
 *    server's behaviour, quirk and all, so it is reproduced rather than
 *    "fixed": search only works if both sides agree.
 */

/** Approximates Python's `unicodedata.combining(ch) != 0`. */
const ZERO_WIDTH_COMBINING = /[̀-ͯ҃-҉֑-ֽً-ٟัิ-ฺ็-๎]/u;

/** Approximates Python's `str.isalnum()` for the scripts in this dataset. */
function isAlnum(ch: string): boolean {
  return /[\p{Nd}\p{Nl}\p{No}\p{Lu}\p{Ll}\p{Lt}\p{Lm}\p{Lo}]/u.test(ch);
}

export function normalizeTitle(title: string): string {
  if (!title) return '';
  const decomposed = title.trim().toLowerCase().normalize('NFKD');

  const stripped = [...decomposed]
    .filter((ch) => !ZERO_WIDTH_COMBINING.test(ch))
    .join('')
    .replace(/['’]/g, '')
    .replace(/&/g, ' and ');

  const kept = [...stripped]
    .map((ch) => (isAlnum(ch) || /\s/.test(ch) ? ch : ' '))
    .join('');

  return kept.split(/\s+/).filter(Boolean).join(' ');
}

let index: IndexEntry[] | null = null;
let inflight: Promise<IndexEntry[]> | null = null;

async function fetchCatalog(): Promise<IndexEntry[]> {
  const base = import.meta.env.VITE_API_URL ?? '';
  const response = await fetch(`${base}/api/movies/catalog`);
  if (!response.ok) throw new Error(`Catalog request failed (${response.status})`);
  const body = (await response.json()) as CatalogResponse;
  return body.movies.map(([id, title, normalized, year]) => ({
    id,
    title,
    normalized,
    compact: normalized.replace(/ /g, ''),
    year,
  }));
}

/**
 * Load the catalogue once. Concurrent callers share a single request, and a
 * failure is not cached -- the next call retries rather than leaving search
 * permanently broken.
 */
export function loadCatalog(): Promise<IndexEntry[]> {
  if (index) return Promise.resolve(index);
  if (inflight) return inflight;

  inflight = fetchCatalog()
    .then((entries) => {
      index = entries;
      return entries;
    })
    .finally(() => {
      inflight = null;
    });

  return inflight;
}

/** True once search can run without waiting on the network. */
export function isCatalogReady(): boolean {
  return index !== null;
}

/**
 * Rank matches the way the server does: exact first, then prefix, then
 * substring; ties broken by shorter title, newer year, then alphabetically.
 */
export function searchCatalog(query: string, limit = 10): MovieSearchItem[] {
  if (!index) return [];

  let cleaned = normalizeTitle(query);
  if (!cleaned) return [];

  // A trailing year filters instead of polluting the match: "pokiri 2006".
  let yearFilter: number | null = null;
  const yearMatch = YEAR_IN_QUERY.exec(query);
  if (yearMatch) {
    const withoutYear = normalizeTitle(query.replace(YEAR_IN_QUERY, ''));
    if (withoutYear) {
      yearFilter = Number(yearMatch[0]);
      cleaned = withoutYear;
    }
  }

  const compact = cleaned.replace(/ /g, '');
  const useCompact = compact.length > 0 && compact !== cleaned;

  const scored: { entry: IndexEntry; rank: number }[] = [];

  for (const entry of index) {
    if (yearFilter !== null && entry.year !== yearFilter) continue;

    const substring = entry.normalized.includes(cleaned);
    const compactHit = useCompact && entry.compact.includes(compact);
    if (!substring && !compactHit) continue;

    let rank = 2;
    if (entry.normalized === cleaned || entry.compact === compact) {
      rank = 0;
    } else if (entry.normalized.startsWith(cleaned)) {
      rank = 1;
    }
    scored.push({ entry, rank });
  }

  scored.sort((a, b) => {
    if (a.rank !== b.rank) return a.rank - b.rank;
    const lengthDiff = a.entry.normalized.length - b.entry.normalized.length;
    if (lengthDiff !== 0) return lengthDiff;
    // Nulls sort last, matching the server's `year DESC` on a nullable column.
    const yearA = a.entry.year ?? -Infinity;
    const yearB = b.entry.year ?? -Infinity;
    if (yearA !== yearB) return yearB - yearA;
    return a.entry.title.localeCompare(b.entry.title);
  });

  return scored
    .slice(0, limit)
    .map(({ entry }) => ({ id: entry.id, title: entry.title, year: entry.year }));
}
