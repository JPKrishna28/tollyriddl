# Telugu Movie Dataset Scraper (2000–2023)

A production-quality Wikipedia scraper that builds a structured dataset of
Telugu-language films released between 2000 and 2023, designed to power a
movie-based guessing/trivia game.

Wikipedia is the **primary and authoritative source**. Wikidata is used only
as a secondary gap-filler, and TMDB enrichment is optional and disabled by
default — the scraper is fully functional with Wikipedia alone.

---

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [CLI options](#cli-options)
- [Output files](#output-files)
- [Dataset schema](#dataset-schema)
- [How extraction works](#how-extraction-works)
- [Caching](#caching)
- [Resume and retry](#resume-and-retry)
- [Data quality and validation](#data-quality-and-validation)
- [Testing](#testing)
- [Known limitations](#known-limitations)
- [Attribution and ethics](#attribution-and-ethics)

---

## Installation

**Python 3.11+** is required (developed and tested on 3.12).

```bash
git clone <your-repo-url> telugu-movie-scraper
cd telugu-movie-scraper

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### Dependencies

| Package          | Purpose                                        |
| ---------------- | ---------------------------------------------- |
| `requests`       | HTTP client                                    |
| `beautifulsoup4` | HTML parsing                                   |
| `lxml`           | Fast parser backend for BeautifulSoup          |
| `pandas`         | Tabular convenience for downstream analysis    |
| `tenacity`       | Retry primitives                               |
| `tqdm`           | Progress bars                                  |
| `pytest`         | Test suite (dev only)                          |

---

## Quick start

Start small. The scraper is deliberately built so you can validate output
before committing to a full run.

```bash
# 1. Smoke test: one year, 20 movies
python main.py --start-year 2020 --end-year 2020 --limit 20

# 2. Broader test: all years, 100 movies
python main.py --start-year 2000 --end-year 2023 --limit 100

# 3. Full dataset
python main.py --start-year 2000 --end-year 2023
```

The full run performs the entire pipeline automatically:

```
Find yearly Telugu movie pages
        ↓
Extract movie list          ↓ deduplicate
        ↓
Resolve Wikipedia URLs
        ↓
Visit individual movie pages
        ↓
Extract metadata → clean → validate Telugu language
        ↓
Save progress (SQLite, after every movie)
        ↓
CSV + JSON + missing-fields report + statistics
```

---

## CLI options

### Year selection

```bash
python main.py --start-year 2000 --end-year 2023   # a range
python main.py --year 2015                          # a single year
```

### Modes

```bash
python main.py --retry-failed     # re-attempt every failed page
python main.py --validate         # re-run validation, rewrite reports (no network)
python main.py --stats            # progress statistics, then exit
python main.py --discover-only    # build the master film list only
python main.py --export-only      # regenerate outputs from stored data (no network)
```

### Options

| Flag                    | Description                                              |
| ----------------------- | -------------------------------------------------------- |
| `--limit N`             | Scrape at most N movies (test runs)                       |
| `--no-cache`            | Bypass the on-disk HTML cache                             |
| `--no-resolve`          | Skip API lookups for films without a wikilink             |
| `--enrich-tmdb`         | Fill remaining gaps via TMDB (needs `TMDB_API_KEY`)       |
| `--min-delay` / `--max-delay` | Override the request rate limit (seconds)           |
| `--db PATH`             | Use an alternate state database                           |
| `--verbose` / `-v`      | Debug logging                                             |
| `--quiet` / `-q`        | Errors only                                               |

---

## Output files

```
output/
├── telugu_movies_2000_2023.csv    # flat dataset, pipe-separated multi-values
├── telugu_movies_2000_2023.json   # structured dataset, arrays preserved
├── missing_fields.csv             # per-film gaps, for manual enrichment
├── failed_urls.csv                # every failure with its error
├── rejected_movies.csv            # excluded records + the reason why
├── year_discrepancies.csv         # list-year vs infobox-year mismatches
├── scraping_report.json           # machine-readable run statistics
└── scraper_state.db               # SQLite resume state
logs/
└── scraper.log                    # INFO / WARNING / ERROR
```

---

## Dataset schema

### CSV columns

```
movie_id, movie_name, year, language, genre, cast, director,
production_house, music_director, writer, wikipedia_url
```

Multi-value fields use `|` as the separator:

```csv
3,Ala Vaikunthapurramuloo,2020,Telugu,Action|Drama|Comedy,Allu Arjun|Pooja Hegde|Tabu,Trivikram Srinivas,Geetha Arts|Haarika & Hassine Creations,Thaman S,Trivikram Srinivas,https://...
```

### JSON structure

Multi-value fields stay as **arrays**, so the game can query them
structurally ("which actor appeared in this movie?") without re-parsing
strings:

```json
{
  "movie_id": 1,
  "movie_name": "Pushpa: The Rise",
  "year": 2021,
  "language": "Telugu",
  "genre": ["Action", "Drama", "Crime"],
  "cast": ["Allu Arjun", "Rashmika Mandanna", "Fahadh Faasil"],
  "director": ["Sukumar"],
  "production_house": ["Mythri Movie Makers", "Muttamsetty Media"],
  "music_director": ["Devi Sri Prasad"],
  "writer": ["Sukumar"],
  "wikipedia_url": "https://en.wikipedia.org/wiki/Pushpa:_The_Rise"
}
```

Cast order is preserved as billed on Wikipedia.

---

## How extraction works

The parser was designed **after** inspecting real pages across every era
(2000, 2005, 2010, 2015, 2020, 2023). The decisions below each address a
concrete problem found in the live HTML.

### 1. Yearly list pages

`List of Telugu films of {year}` resolves for all 24 years, but the scraper
never relies on a single pattern. It tries several title forms, follows
redirects, and falls back to the MediaWiki **search API** if none resolve.

### 2. Table geometry (the hard part)

Each yearly page carries 3–5 `wikitable`s. Two problems make naive parsing
silently wrong:

- **`colspan`** — the "Opening" header spans two columns (month + day), so
  every later column is offset by one.
- **`rowspan`** — month cells span up to 7 rows, day cells span several
  films, and the production-house column spans rows too. A given `<tr>`
  therefore has *fewer* `<td>`s than the table has columns.

Indexing by position puts a director where a title belongs. The scraper
instead expands each table into a **virtual grid** where every logical
coordinate resolves to the cell occupying it, then maps header labels to
column indices.

Box-office tables (`Rank | Title | Worldwide gross`) and award tables
(`Date | Event | Host`) also contain a `Title` column, so tables are
filtered by header signature rather than accepted on sight.

### 3. Movie pages

Roughly 56–84% of listed titles are wikilinked (varies by year). Unlinked
films are resolved through batched API lookups trying
`X (YEAR film)` → `X (film)` → `X`. A title that resolves to an aggregate
page (e.g. `Eureka` → `List of Telugu films of 2020`) is **rejected**, not
followed — otherwise list pages end up as dataset rows.

Fields come from the infobox via normalised label matching:

| Field            | Labels handled                                            |
| ---------------- | --------------------------------------------------------- |
| Director         | `Directed by`, `Director`                                  |
| Writer           | `Written by`, `Screenplay by`, `Story by`                  |
| Music director   | `Music by`, `Music`, `Composer`, `Score by`                |
| Production house | `Production company/companies`, `Studio`, `Banner`         |
| Cast             | `Starring`, `Cast`, `Stars`                                |

**Writer credits are strict.** `Dialogues by` appears as its own infobox row
on many Telugu films; dialogue writers, lyricists, cinematographers and
editors are explicitly **excluded** from the writer field.

**Production house prefers companies over people.** `Produced by` names
individual producers, so it is only consulted when no company row exists.

### 4. Genre

No film infobox on Wikipedia carries a `Genre` row. Genre is mined from
**categories** (`2021 action drama films` → `Action`, `Drama`) against a
controlled vocabulary, so descriptive categories such as
`Films about funerals` contribute nothing. If no genre can be determined,
the field is left empty — never guessed.

### 5. Cast

Two markup shapes exist in the wild: `.plainlist` `<li>` items, and plain
`<br>`-separated text with no list markup. Both are handled, order
preserved. Only the infobox cast row is read — the article body is never
scanned, so no crew member is mistaken for an actor.

---

## Caching

Every fetched page is stored under `cache/`, keyed by a SHA-256 of the URL
and fanned out into subdirectories. API responses are cached too.

```
if cached:  use local HTML
else:       download, then cache
```

Re-running the scraper after a parser change costs **zero** network requests
and puts no additional load on Wikipedia. Cached pages never expire by
default (film articles for 2000–2023 are effectively static); use
`--no-cache` to force refetching.

---

## Resume and retry

Progress lives in `output/scraper_state.db` (SQLite). Every film is recorded
with `url`, `status`, `attempts`, `last_attempt` and `error` **before** any
page is fetched, and the row is committed after each movie.

Statuses: `pending` → `success` / `failed`.

If the scraper crashes after 500 of 1,500 movies, rerunning the same command
resumes at 501. `Ctrl-C` is safe for the same reason.

```bash
python main.py --start-year 2000 --end-year 2023   # resumes automatically
python main.py --retry-failed                      # re-attempt failures
python main.py --stats                             # inspect the queue
```

Because scraped payloads are stored alongside the status, the CSV/JSON can
be regenerated without re-fetching anything:

```bash
python main.py --export-only
```

---

## Data quality and validation

### Telugu-language validation

Appearing on a yearly Telugu-film list is treated as **evidence, not
proof**. The bare title "Balagam" resolves to a village in Gujarat; the film
lives at "Balagam (film)". Several signals are combined into a confidence
grade:

| Confidence | Basis                                                       |
| ---------- | ----------------------------------------------------------- |
| `high`     | Category `<year> Telugu-language films`, or infobox `Language = Telugu` on a confirmed film |
| `medium`   | Weaker Telugu signal, or list membership on a confirmed film |
| `low`      | Not a film, or the page states a different language          |

Only `high` and `medium` enter the dataset. Films explicitly labelled
Kannada, Hindi, Tamil, etc. are rejected, as are non-film pages.

### Quality rules

Before a record is saved:

- `movie_name` must not be empty
- `year` must fall within 2000–2023
- `wikipedia_url` must be a valid article URL (namespace pages rejected)
- missing fields are preserved as empty — **never fabricated**
- duplicates are removed on `(normalised title, year)` plus URL
- **nothing is silently discarded**: rejects land in `rejected_movies.csv`
  with reasons, failures in `failed_urls.csv`

### Year discrepancies

If the list page says 2005 but the infobox says 2006, the **list year is
kept** and the mismatch is flagged in `year_discrepancies.csv` rather than
silently overwritten.

### Reports

```bash
python main.py --validate
```

```
Movies missing genre: 12
Movies missing cast: 4
Movies missing director: 2
...
```

Per-film detail goes to `output/missing_fields.csv` so records can be
enriched manually later.

---

## Testing

```bash
pytest tests/ -v
```

The suite covers text cleaning, table-grid geometry (rowspan/colspan),
release-table detection, redirect guarding, infobox extraction, the
writer/dialogue distinction, and language validation. Fixtures reproduce
real markup observed on Wikipedia rather than idealised HTML.

---

## Known limitations

1. **Films without Wikipedia articles are not scraped.** Depending on the
   year, 15–45% of listed titles have no article. They appear in discovery
   but cannot yield metadata, and are skipped rather than guessed at.
2. **Genre depends on category curation.** Older and smaller films often
   carry only `2003 films`, yielding no genre.
3. **Writer coverage is inherently lower** than director/cast, because many
   Telugu film infoboxes list only `Dialogues by` — deliberately excluded.
4. **Wikipedia data is community-maintained** and contains occasional
   errors, inconsistent name spellings, and incomplete infoboxes. The
   scraper reproduces the source faithfully rather than correcting it.
5. **Anthology and multilingual films** may carry several language
   categories; they are included when Telugu is among them.
6. **List pages themselves are inconsistent** across years — some include
   dubbed or straight-to-OTT releases, which affects year-over-year counts.

---

## Attribution and ethics

Content is sourced from **English Wikipedia** and is available under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Any
redistribution of this dataset should attribute Wikipedia and preserve the
same licence. Every record carries its `wikipedia_url` so it can be traced
back to its source.

The scraper is designed to be a well-behaved client:

- descriptive `User-Agent` with contact information
- 1–2 second jittered delay between live requests
- automatic slow-down on HTTP 429, honouring `Retry-After`
- exponential backoff with jitter on transient failures
- aggressive caching so repeat runs generate no traffic
- no attempt to bypass rate limits or anti-bot mechanisms

Only publicly available pages are accessed. For bulk research use, consider
Wikipedia's [database dumps](https://dumps.wikimedia.org/) instead.
