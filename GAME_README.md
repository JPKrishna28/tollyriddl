# 🎬 Telugu Riddle — Guess the Mystery Movie

A daily Telugu-cinema guessing game. One hidden movie, seven attempts, and
clues drawn only from what your guesses have in common with the answer.

Built on the Wikipedia dataset produced by the scraper in this repository
(1,724 Telugu films, 2000–2023).

```
Backend   FastAPI + SQLAlchemy      (Vercel Python function)
Frontend  React + TypeScript + Tailwind (Vercel static)
Database  Supabase (PostgreSQL)
```

---

## Contents

- [How the game works](#how-the-game-works)
- [Quick start](#quick-start)
- [Supabase setup](#supabase-setup)
- [Importing the dataset](#importing-the-dataset)
- [Running locally](#running-locally)
- [Deploying to Vercel](#deploying-to-vercel)
- [API reference](#api-reference)
- [Project layout](#project-layout)
- [Testing](#testing)
- [Anti-cheat design](#anti-cheat-design)
- [Dataset assumptions](#dataset-assumptions)
- [Known limitations](#known-limitations)

---

## How the game works

You start knowing only this: *the mystery movie is a Telugu film released
between 2000 and 2023.*

Each guess must be a real movie from the dataset. The game then reveals
**only the attributes your guess shares with the answer**:

| Attribute | What you learn |
| --- | --- |
| **Year** | `✓ 2018` on an exact match, otherwise only `↑ later` / `↓ earlier` |
| **Genre** | The genres both films share |
| **Cast** | Shared actors, plus their billing position in the mystery film (`#3`) |
| **Director** | The name, only if it matches |
| **Production house** | The name, only if it matches |
| **Music director** | The name, only if it matches |
| **Writer** | The name, only if it matches |

Nothing else leaks. A wrong year tells you the direction but never the year.

**Lifelines** — after 4 guesses you may reveal one attribute; after 6, a
second. A lifeline can only reveal something still hidden: if you already
learned the director from a matching guess, that cell is not offered.

**Bonus attempts** — after the 7th guess you may explicitly unlock 3 more,
for a maximum of 10. They are never granted automatically.

**Daily puzzle** — everyone gets the same movie on the same date, chosen
deterministically from the date via SHA-256.

---

## Quick start

The fastest path (SQLite, no external services):

```bash
# 1. Backend
cd backend
pip install -r requirements.txt
export DATABASE_URL="sqlite+pysqlite:///./tollyriddl.db"
python scripts/import_movies.py --file ../output/telugu_movies_2000_2023.csv
uvicorn app.main:app --reload --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

---

## Supabase setup

1. Create a project at [supabase.com](https://supabase.com).
2. **Project Settings → Database → Connection string → Transaction pooler**
   (port `6543`). Copy it.
3. Create the schema — either run `backend/sql/schema.sql` in the Supabase
   SQL editor, or let the importer create the tables automatically.

```bash
export DATABASE_URL="postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres"
```

> **Use the pooler, not the direct connection.** Serverless functions open a
> connection per invocation; the direct port (5432) runs out of slots as soon
> as traffic scales.

---

## Importing the dataset

```bash
cd backend
python scripts/import_movies.py --file ../output/telugu_movies_2000_2023.csv
```

Accepts either the CSV (pipe-separated multi-values) or the JSON (real
arrays) — the format is detected from the extension. Options:

| Flag | Purpose |
| --- | --- |
| `--file PATH` | Dataset to import |
| `--reset` | Delete existing movie rows first |

Expected output:

```
Movies imported:     1,724
Genres imported:     3,358
Cast records:        5,749
Duplicates skipped:  0
Invalid rows:        0
Puzzle-eligible:     1,461
```

Re-running updates existing rows instead of duplicating them.

---

## Running locally

**Backend**

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

API docs at <http://localhost:8000/api/docs>.

**Frontend**

```bash
cd frontend
npm run dev
```

Vite proxies `/api` to `127.0.0.1:8000`, so the frontend calls same-origin
paths exactly as it will in production — no CORS-only-in-dev surprises.

---

## Deploying to Vercel

The repository is already configured for a single Vercel project serving
both the static frontend and the Python API.

1. Import the repository in Vercel.
2. Add environment variables (see `.env.example`):
   - `DATABASE_URL` — Supabase **pooler** connection string
   - `DAILY_SEED` — any stable string
   - `ARCHIVE_START_DATE` — e.g. `2026-01-01`
3. Deploy.

`vercel.json` maps `/api/*` to the FastAPI function (`api/index.py`) and
everything else to the built SPA. Because both live on one origin, no CORS
configuration is required.

Import the dataset once against the Supabase URL before the first play:

```bash
DATABASE_URL="<supabase-pooler-url>" python backend/scripts/import_movies.py \
    --file output/telugu_movies_2000_2023.csv
```

---

## API reference

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness + row counts |
| `GET` | `/api/stats` | Anonymous aggregate statistics |
| `GET` | `/api/movies/search?q=` | Autocomplete (id, title, year only) |
| `GET` | `/api/games/today` | Today's puzzle metadata |
| `POST` | `/api/games/start` | Start a session |
| `GET` | `/api/games/{id}` | Current state (for resuming) |
| `POST` | `/api/games/{id}/guess` | Submit a guess |
| `POST` | `/api/games/{id}/lifeline` | Reveal one attribute |
| `POST` | `/api/games/{id}/unlock-bonus` | Unlock 3 extra attempts |
| `GET` | `/api/games/archive` | Past dates and outcomes |
| `GET` | `/api/games/archive/{date}` | Check a past date is playable |

Guessing sends only an id; the server resolves everything else:

```jsonc
// POST /api/games/{id}/guess   -->  { "guess_movie_id": 123 }
{
  "attempt": 2,
  "result": {
    "title": "Pokiri",
    "is_correct": false,
    "year":   { "guess": 2006, "status": "absent", "direction": "later" },
    "genre":  { "common": ["Romance"], "status": "partial" },
    "cast":   { "common": [], "common_count": 0, "status": "absent" },
    "director": { "common": [] }
    // ... no field carries an unshared value
  }
}
```

---

## Project layout

```
tollyriddl/
├── api/index.py               # Vercel serverless entry (ASGI app)
├── vercel.json                # Routing: /api -> function, rest -> SPA
├── requirements-api.txt       # Slim deps for the serverless bundle
│
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app
│   │   ├── config.py          # Env-driven settings
│   │   ├── database.py        # Engine/session (serverless-tuned)
│   │   ├── models/            # movie.py, game.py
│   │   ├── services/
│   │   │   ├── comparison_engine.py   # <- core game logic, pure
│   │   │   ├── game_service.py        # rules, lifelines, anti-cheat
│   │   │   ├── daily_movie.py         # deterministic selection
│   │   │   └── movie_service.py       # search
│   │   ├── api/               # games.py, movies.py, health.py
│   │   └── schemas/           # Pydantic request/response models
│   ├── scripts/import_movies.py
│   ├── sql/schema.sql         # PostgreSQL/Supabase DDL
│   └── tests/                 # 67 tests
│
├── frontend/
│   └── src/
│       ├── components/        # GameBoard, GuessRow, MovieSearch,
│       │                      # LifelinePanel, ResultModal
│       ├── pages/             # Game, Archive
│       ├── hooks/useGame.ts   # State + localStorage persistence
│       ├── services/api.ts    # Typed API client
│       └── types/game.ts
│
└── output/                    # Scraped dataset (from the scraper)
```

The comparison engine is a **pure module**: it takes two dataclasses and
returns a dataclass, with no database, HTTP or framework imports. That keeps
it independently testable and stops game logic drifting into API routes or
React components.

---

## Testing

```bash
cd backend
pytest tests/ -v          # 67 tests
```

Covers:

- **Comparison engine** (36 tests) — year direction, genre/cast
  intersection, cast positions, crew matching, name normalisation
  (`S. S. Rajamouli` == `S S Rajamouli`), missing metadata, and an explicit
  test that a losing guess leaks *nothing* unshared.
- **Game rules** — duplicate guesses, unknown movie ids, guessing after the
  game ends, lifeline thresholds, already-known-clue refusal, bonus cap of
  10, future dates.
- **Determinism** — the same date always yields the same movie, independent
  of `PYTHONHASHSEED`.

Frontend type-checking:

```bash
cd frontend && npm run typecheck
```

---

## Anti-cheat design

The mystery movie is resolved **entirely server-side** and appears in no
response while a game is active. Specifically:

- `POST /guess` sends only `{ "guess_movie_id": N }`; the comparison happens
  on the server.
- A non-matching year returns a *direction*, never the year itself.
- Unshared genres, cast, and crew are omitted from the payload entirely —
  not sent-but-hidden.
- `/api/movies/search` returns id, title and year only, so the catalogue
  cannot be mined for attributes.
- The archive lists dates and outcomes, never answers.
- The client's local date is honoured (so the puzzle rolls at *your*
  midnight) but clamped to ±1 day around UTC, so setting the system clock
  forward cannot unlock future puzzles.
- Duplicate guesses and one-lifeline-per-slot are enforced by database
  unique constraints, not only in application code.
- `localStorage` holds just the game id — no guesses, no answer. Refreshing
  re-fetches authoritative state from the server.

---

## Dataset assumptions

Verified against the actual scraped output rather than assumed:

1. **CSV multi-value fields are pipe-separated**; the JSON export uses real
   arrays. The importer accepts both.
2. **`director` can hold multiple names** (15 films have co-directors), so
   every attribute — including director — is modelled as a list. Treating it
   as a scalar would silently drop credits.
3. **Cast order is billing order** and is preserved as `cast_position`,
   because the game exposes it as a deduction signal.
4. **Fields can be empty.** Coverage in the source data: cast 99%, director
   99%, music 98%, production 98%, writer 91%, genre 86%. Missing values
   compare as `unknown` rather than "no match", so a sparse film never
   produces a misleading result.
5. **Titles may contain Telugu script or punctuation** (`Nenu.. Sailaja...`,
   `N.T.R: Kathanayakudu`). Titles are displayed exactly as scraped; a
   separate normalised column is used for search and deduplication only.
6. **Movie ids are reassigned on import** — the dataset's `movie_id` is a
   CSV row number, not a stable key. Uniqueness is `(normalized_title, year)`
   so reused titles across years stay distinct.

Only movies with a year, ≥2 cast members, ≥1 genre, a director, and a
quality score ≥6 are eligible to *be* the mystery movie (1,461 of 1,724).
All 1,724 remain guessable.

---

## Known limitations

1. **Sessions are anonymous and per-browser.** `localStorage` holds the game
   id, so clearing storage or switching devices starts a new session. The
   schema supports adding user accounts later without changes.
2. **Statistics are global, not per-player**, for the same reason.
3. **Genre coverage is 86%** — a limitation of Wikipedia's categories, not
   the parser. Films with no genre simply contribute no genre clue.
4. **The archive starts at `ARCHIVE_START_DATE`.** Dates before it are not
   playable.
5. **Puzzle rotation** cycles the eligible pool in a fixed shuffled order, so
   the schedule repeats after 1,461 days (~4 years).
6. **No rate limiting** on the API. Fine behind Vercel's defaults for a
   hobby deployment; add limits before a public launch.

---

Movie data from **Wikipedia**, licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Every movie
record retains its source URL.
