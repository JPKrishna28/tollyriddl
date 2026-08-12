-- Telugu Riddle -- PostgreSQL / Supabase schema
--
-- Run this in the Supabase SQL editor before the first import, or let
-- SQLAlchemy create the tables via `create_all()` from the importer.
-- Kept as explicit SQL so the production schema is reviewable and the
-- indexes are intentional rather than inferred.

-- ---------------------------------------------------------------- movies
CREATE TABLE IF NOT EXISTS movies (
    id               SERIAL PRIMARY KEY,
    title            VARCHAR(500) NOT NULL,
    normalized_title VARCHAR(500) NOT NULL,
    year             INTEGER,
    language         VARCHAR(64)  NOT NULL DEFAULT 'Telugu',
    director         TEXT,
    production_house TEXT,
    music_director   TEXT,
    writer           TEXT,
    wikipedia_url    TEXT,
    quality_score    INTEGER NOT NULL DEFAULT 0,
    is_eligible      BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_movie_title_year UNIQUE (normalized_title, year)
);

CREATE INDEX IF NOT EXISTS ix_movies_title            ON movies (title);
CREATE INDEX IF NOT EXISTS ix_movies_normalized_title ON movies (normalized_title);
CREATE INDEX IF NOT EXISTS ix_movies_year             ON movies (year);
CREATE INDEX IF NOT EXISTS ix_movies_eligible_year    ON movies (is_eligible, year);
CREATE INDEX IF NOT EXISTS ix_movies_quality          ON movies (quality_score);

-- Speeds up the LIKE '%term%' autocomplete. pg_trgm ships with Supabase.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS ix_movies_title_trgm
    ON movies USING gin (normalized_title gin_trgm_ops);

-- --------------------------------------------------------- movie_genres
CREATE TABLE IF NOT EXISTS movie_genres (
    id       SERIAL PRIMARY KEY,
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    genre    VARCHAR(120) NOT NULL,
    CONSTRAINT uq_movie_genre UNIQUE (movie_id, genre)
);

CREATE INDEX IF NOT EXISTS ix_movie_genres_movie ON movie_genres (movie_id);
CREATE INDEX IF NOT EXISTS ix_movie_genres_genre ON movie_genres (genre);

-- ----------------------------------------------------------- movie_cast
-- cast_position preserves billing order, which the game exposes as a
-- deduction signal, so it must be stable and unique per film.
CREATE TABLE IF NOT EXISTS movie_cast (
    id            SERIAL PRIMARY KEY,
    movie_id      INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    actor_name    VARCHAR(300) NOT NULL,
    cast_position INTEGER NOT NULL,
    CONSTRAINT uq_movie_cast_position UNIQUE (movie_id, cast_position)
);

CREATE INDEX IF NOT EXISTS ix_movie_cast_movie ON movie_cast (movie_id);
CREATE INDEX IF NOT EXISTS ix_movie_cast_actor ON movie_cast (actor_name);

-- ---------------------------------------------------------- daily_games
-- One puzzle per calendar date. Pinning it here means later changes to the
-- movie pool cannot retroactively alter a past day's answer.
CREATE TABLE IF NOT EXISTS daily_games (
    id               SERIAL PRIMARY KEY,
    game_date        DATE NOT NULL UNIQUE,
    mystery_movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE RESTRICT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_daily_games_date ON daily_games (game_date);

-- -------------------------------------------------------- game_sessions
CREATE TABLE IF NOT EXISTS game_sessions (
    id             VARCHAR(64) PRIMARY KEY,
    daily_game_id  INTEGER NOT NULL REFERENCES daily_games(id) ON DELETE CASCADE,
    status         VARCHAR(16) NOT NULL DEFAULT 'active',
    attempts_used  INTEGER NOT NULL DEFAULT 0,
    bonus_unlocked BOOLEAN NOT NULL DEFAULT FALSE,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_game_sessions_daily  ON game_sessions (daily_game_id);
CREATE INDEX IF NOT EXISTS ix_game_sessions_status ON game_sessions (status);

-- --------------------------------------------------------------- guesses
-- The unique constraints enforce "no duplicate guesses" and "one guess per
-- attempt number" in the database, not merely in application code.
CREATE TABLE IF NOT EXISTS guesses (
    id              SERIAL PRIMARY KEY,
    game_session_id VARCHAR(64) NOT NULL REFERENCES game_sessions(id) ON DELETE CASCADE,
    movie_id        INTEGER NOT NULL REFERENCES movies(id) ON DELETE RESTRICT,
    attempt_number  INTEGER NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_guess_session_movie   UNIQUE (game_session_id, movie_id),
    CONSTRAINT uq_guess_session_attempt UNIQUE (game_session_id, attempt_number)
);

CREATE INDEX IF NOT EXISTS ix_guesses_session ON guesses (game_session_id);

-- ------------------------------------------------------------- lifelines
CREATE TABLE IF NOT EXISTS lifelines (
    id              SERIAL PRIMARY KEY,
    game_session_id VARCHAR(64) NOT NULL REFERENCES game_sessions(id) ON DELETE CASCADE,
    lifeline_number INTEGER NOT NULL,
    attribute       VARCHAR(64) NOT NULL,
    -- Which cell of a multi-valued attribute this lifeline bought.
    value_index     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_lifeline_session_number UNIQUE (game_session_id, lifeline_number),
    -- Scoped to the cell, not the row: a second lifeline may target another
    -- cell of the same attribute.
    CONSTRAINT uq_lifeline_session_attribute_index
        UNIQUE (game_session_id, attribute, value_index)
);

CREATE INDEX IF NOT EXISTS ix_lifelines_session ON lifelines (game_session_id);

-- Migration for databases created before per-cell lifelines. CREATE TABLE
-- IF NOT EXISTS above is a no-op on an existing table, so the column and
-- the relaxed constraint have to be applied explicitly.
ALTER TABLE lifelines ADD COLUMN IF NOT EXISTS value_index INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lifelines DROP CONSTRAINT IF EXISTS uq_lifeline_session_attribute;

DO $$
BEGIN
    ALTER TABLE lifelines ADD CONSTRAINT uq_lifeline_session_attribute_index
        UNIQUE (game_session_id, attribute, value_index);
EXCEPTION
    WHEN duplicate_table THEN NULL;  -- constraint already present
END $$;
