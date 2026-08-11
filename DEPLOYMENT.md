# Deployment — Supabase + Vercel

Project ref: `rvebezvialcfbmqkblol`

---

## Before you start: two gotchas that will bite

### 1. Your password contains `@` — it must be percent-encoded

`@` is the delimiter between credentials and host in a connection URL. Left
raw, the host is parsed as `6769@aws-0-...` and the connection fails.

```
Tollywood@6769   ->   Tollywood%406769
```

Other characters needing encoding if you change the password:

| Char | Encode as | | Char | Encode as |
| --- | --- | --- | --- | --- |
| `@` | `%40` | | `?` | `%3F` |
| `:` | `%3A` | | `#` | `%23` |
| `/` | `%2F` | | `%` | `%25` |

### 2. Use the pooler (6543), not the direct connection (5432)

The URL you have is the **direct** connection:

```
postgresql://postgres:...@db.rvebezvialcfbmqkblol.supabase.co:5432/postgres
```

Vercel opens a new database connection per function invocation. The direct
port exhausts Postgres slots as soon as traffic scales, and it resolves
IPv6-only, which some networks cannot reach. Use the **Transaction pooler**
for the deployed app:

```
postgresql://postgres.rvebezvialcfbmqkblol:<PASSWORD>@aws-0-<REGION>.pooler.supabase.com:6543/postgres
```

Get it from **Supabase → Connect → Connection string → Transaction pooler**.
Note the user is `postgres.<project-ref>`, not plain `postgres`.

The direct URL is fine for local work and for running the one-off import.

---

## Step 1 — Create the schema

**Supabase → SQL Editor → New query.** Paste the contents of
`backend/sql/schema.sql` and run it.

Creates 6 tables (`movies`, `movie_genres`, `movie_cast`, `daily_games`,
`game_sessions`, `guesses`, `lifelines`), their indexes, and the `pg_trgm`
extension used by autocomplete.

*(Verified: this DDL was executed against PostgreSQL 16 — the same major
version Supabase runs — with no errors.)*

Alternatively the importer creates the tables automatically; the explicit
SQL just makes the production schema reviewable.

---

## Step 2 — Import the dataset

Run once, locally. Fill in your region and use the **encoded** password.

```bash
cd backend
pip install -r requirements.txt

DATABASE_URL="postgresql://postgres.rvebezvialcfbmqkblol:Tollywood%406769@aws-0-<REGION>.pooler.supabase.com:6543/postgres" \
  python scripts/import_movies.py --file ../output/telugu_movies_2000_2023.csv
```

Or simply put `DATABASE_URL` in `.env` (already created for you, gitignored)
and run:

```bash
python scripts/import_movies.py --file ../output/telugu_movies_2000_2023.csv
```

Expected:

```
Movies imported:     1,724
Genres imported:     3,358
Cast records:        5,749
Duplicates skipped:  0
Invalid rows:        0
Puzzle-eligible:     1,461
```

Verify in Supabase → Table Editor → `movies` (1,724 rows).

---

## Step 3 — Push to GitHub

```bash
git init
git add .
git commit -m "Telugu Riddle: scraper, game backend, frontend"
git branch -M main
git remote add origin git@github.com:<you>/tollyriddl.git
git push -u origin main
```

`.gitignore` already excludes `.env`, `node_modules/`, `cache/`, `output/*.db`.

> Confirm `git status` does **not** list `.env` before committing.

---

## Step 4 — Create the Vercel project

1. [vercel.com/new](https://vercel.com/new) → import the repository.
2. **Framework Preset:** *Other* — `vercel.json` already defines the build.
3. Leave build/output settings untouched; `vercel.json` supplies:
   - build: `cd frontend && npm install && npm run build`
   - output: `frontend/dist`
   - `/api/*` → the Python function at `api/index.py`
4. **Do not deploy yet** — add the environment variables first.

---

## Step 5 — Environment variables

**Vercel → Project → Settings → Environment Variables.** Apply each to
Production, Preview, and Development.

### Required

| Key | Value |
| --- | --- |
| `DATABASE_URL` | `postgresql://postgres.rvebezvialcfbmqkblol:Tollywood%406769@aws-0-<REGION>.pooler.supabase.com:6543/postgres` |
| `DAILY_SEED` | `telugu-mystery` — any stable string |
| `ARCHIVE_START_DATE` | `2026-01-01` |

### Optional (defaults already applied in code)

| Key | Default | Purpose |
| --- | --- | --- |
| `BASE_ATTEMPTS` | `7` | Guesses before the bonus prompt |
| `BONUS_ATTEMPTS` | `3` | Extra guesses when unlocked |
| `LIFELINE_1_AFTER` | `4` | First lifeline threshold |
| `LIFELINE_2_AFTER` | `6` | Second lifeline threshold |
| `MIN_QUALITY_SCORE` | `6` | Daily-puzzle eligibility |
| `MIN_CAST` | `2` | Minimum cast for eligibility |
| `MIN_GENRES` | `1` | Minimum genres for eligibility |
| `ARCHIVE_MAX_DAYS` | `30` | Days shown in Past Games |
| `SEARCH_LIMIT` | `12` | Autocomplete result cap |
| `DEBUG` | `false` | Verbose logging |

### Keys you do **not** need

- ❌ `SUPABASE_URL`
- ❌ `SUPABASE_ANON_KEY`
- ❌ `SUPABASE_SERVICE_ROLE_KEY`
- ❌ `VITE_API_URL` — leave unset; frontend and API share one origin
- ❌ `CORS_ORIGINS` — same-origin needs no CORS

This app talks to Postgres directly through SQLAlchemy. Keeping the
`service_role` key out of the deployment is deliberate: it bypasses row-level
security and has no business in a public web app.

> ⚠️ `DAILY_SEED` fixes the puzzle schedule. Changing it later reshuffles
> **every** date, including ones already played. Set it once.

---

## Step 6 — Deploy

Click **Deploy**. Then verify:

```bash
curl https://<your-app>.vercel.app/api/health
# {"status":"ok","database":true,"movies":1724,"eligible_movies":1461}
```

If `movies` is 0, the import in Step 2 did not reach this database.

Open the site and play a guess. API docs live at
`https://<your-app>.vercel.app/api/docs`.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `could not translate host name "6769@aws-0-..."` | Unencoded `@` in the password | Use `%40` |
| `password authentication failed` | Wrong password, or pooler user is not `postgres.<ref>` | Re-copy from Supabase → Connect |
| `remaining connection slots are reserved` | Using the direct port on serverless | Switch to the pooler (6543) |
| `/api/health` shows `movies: 0` | Imported into a different database | Re-run Step 2 against the same URL |
| `Network is unreachable` locally | Direct host is IPv6-only | Use the pooler URL |
| 404 on every `/api/*` route | `vercel.json` not picked up | Ensure it is at the repository root |
| Frontend loads, API calls fail | `VITE_API_URL` set unnecessarily | Clear it — same origin |

---

## Updating the dataset later

Re-run the scraper, then re-import. Existing rows are updated rather than
duplicated:

```bash
python main.py --start-year 2000 --end-year 2023        # refresh dataset
cd backend
python scripts/import_movies.py --file ../output/telugu_movies_2000_2023.csv
```

Adding movies changes which films are *eligible*, which can shift future
puzzle selection. Dates already played are pinned in `daily_games` and are
never retroactively altered.
