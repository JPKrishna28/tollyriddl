// The main game screen.

import { useEffect, useState } from 'react';

import { AttributePanel } from '@/components/AttributePanel';
import { GuessSlots } from '@/components/GuessSlots';
import { LifelinePanel } from '@/components/LifelinePanel';
import { MovieSearch } from '@/components/MovieSearch';
import { ResultModal } from '@/components/ResultModal';
import { useGame } from '@/hooks/useGame';

interface Props {
  gameDate?: string;
  heading?: string;
}

/** Puzzle index, counted from the first playable date. */
const PUZZLE_EPOCH = '2024-01-01';

function puzzleNumber(gameDate: string): number {
  const start = Date.parse(`${PUZZLE_EPOCH}T00:00:00`);
  const current = Date.parse(`${gameDate}T00:00:00`);
  if (Number.isNaN(start) || Number.isNaN(current)) return 0;
  return Math.floor((current - start) / 86_400_000) + 1;
}

function formatGameDate(gameDate: string): string {
  const parsed = new Date(`${gameDate}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return gameDate;
  return parsed.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

export function GameBoard({ gameDate, heading }: Props) {
  const {
    game,
    guesses,
    clues,
    loading,
    submitting,
    error,
    submitGuess,
    useLifeline,
    unlockBonus,
    dismissError,
    reload,
  } = useGame(gameDate);

  const [showResult, setShowResult] = useState(false);

  // Pop the result modal automatically when the game ends.
  useEffect(() => {
    if (game && game.status !== 'active' && game.mystery_movie) {
      setShowResult(true);
    }
  }, [game?.status, game?.mystery_movie]);

  if (loading) {
    return (
      <div
        className="grid gap-6 lg:grid-cols-2 lg:items-start"
        aria-busy="true"
        aria-live="polite"
      >
        <div className="space-y-4">
          <div className="h-44 animate-pulse rounded-2xl bg-slate-100" />
          <div className="h-52 animate-pulse rounded-2xl bg-slate-100" />
        </div>
        <div className="space-y-4">
          <div className="h-40 animate-pulse rounded-2xl bg-slate-100" />
          <div className="h-14 animate-pulse rounded-2xl bg-slate-100" />
        </div>
        <span className="sr-only">Loading today’s puzzle…</span>
      </div>
    );
  }

  if (!game) {
    return (
      <div className="card p-6 text-center">
        <p className="text-slate-600">{error ?? 'Could not load the game.'}</p>
        <button type="button" className="btn-primary mt-4" onClick={() => void reload()}>
          Try again
        </button>
      </div>
    );
  }

  const isActive = game.status === 'active';
  const guessedIds = guesses.map((guess) => guess.movie_id);
  const outOfAttempts = game.attempts_remaining <= 0;

  return (
    <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
      {/* Left on desktop, but ordered *second* on mobile: the attribute
          board is tall, and stacking it first would push the search box
          below the fold on a phone. */}
      <div className="order-2 lg:order-1">
        <AttributePanel guesses={guesses} clues={clues} />
      </div>

      {/* Right: attempts, lifelines and the search box. */}
      <div className="order-1 space-y-4 lg:order-2">
        <header className="flex items-baseline justify-between gap-3">
          <span className="text-sm font-semibold text-slate-500">
            #{puzzleNumber(game.game_date)}
          </span>
          <span className="text-sm text-slate-500">
            {heading ?? formatGameDate(game.game_date)}
          </span>
        </header>

        <GuessSlots guesses={guesses} maxAttempts={game.max_attempts} />

        <div className="border-t border-slate-200 pt-4">
          <LifelinePanel
            game={game}
            clues={clues}
            onUse={(attr) => void useLifeline(attr)}
            busy={submitting}
          />
        </div>

        {/* Guess input */}
        {isActive && !outOfAttempts && (
          <div className="space-y-2">
            <MovieSearch
              onSelect={(movie) => void submitGuess(movie.id)}
              disabled={submitting}
              guessedIds={guessedIds}
            />
            {submitting && (
              <p className="text-xs text-slate-500">Checking your guess…</p>
            )}
          </div>
        )}

        {/* Bonus unlock prompt */}
        {game.bonus_available && (
          <section className="card animate-fade-up p-5 text-center">
            <p className="font-display text-base font-semibold text-slate-900">
              Out of guesses — unlock 3 more?
            </p>
            <p className="mt-1 text-sm text-slate-600">
              You have used all {game.base_attempts} attempts. Take{' '}
              {game.bonus_attempts} more to crack it.
            </p>
            <button
              type="button"
              className="btn-primary mt-4"
              disabled={submitting}
              onClick={() => void unlockBonus()}
            >
              Unlock 3 more guesses
            </button>
          </section>
        )}

        {error && (
          <div
            role="alert"
            className="flex items-start justify-between gap-3 rounded-xl border border-miss-200
                       bg-miss-50 px-4 py-3 text-sm text-miss-700"
          >
            <span>{error}</span>
            <button
              type="button"
              onClick={dismissError}
              className="shrink-0 text-miss-500 hover:text-miss-700"
              aria-label="Dismiss"
            >
              ✕
            </button>
          </div>
        )}

        {!isActive && !showResult && (
          <button
            type="button"
            className="btn-ghost w-full"
            onClick={() => setShowResult(true)}
          >
            Show the answer
          </button>
        )}
      </div>

      {showResult && game.status !== 'active' && (
        <ResultModal game={game} onClose={() => setShowResult(false)} />
      )}
    </div>
  );
}
