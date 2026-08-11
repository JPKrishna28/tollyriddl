// The main game screen.

import { useEffect, useMemo, useState } from 'react';

import { GuessFeedback } from '@/components/GuessFeedback';
import { LifelinePanel } from '@/components/LifelinePanel';
import { MovieSearch } from '@/components/MovieSearch';
import { ResultModal } from '@/components/ResultModal';
import { useGame } from '@/hooks/useGame';

interface Props {
  gameDate?: string;
  heading?: string;
}

function AttemptPips({ used, max }: { used: number; max: number }) {
  return (
    <div className="flex items-center gap-1" aria-hidden>
      {Array.from({ length: max }, (_, index) => (
        <span
          key={index}
          className={`h-1.5 w-5 rounded-full transition-colors ${
            index < used ? 'bg-slate-800' : 'bg-slate-200'
          }`}
        />
      ))}
    </div>
  );
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

  // Newest first. Memoised so the reversed copy is not rebuilt on every
  // keystroke in the search box.
  const latestFirst = useMemo(() => [...guesses].reverse(), [guesses]);

  // Pop the result modal automatically when the game ends.
  useEffect(() => {
    if (game && game.status !== 'active' && game.mystery_movie) {
      setShowResult(true);
    }
  }, [game?.status, game?.mystery_movie]);

  if (loading) {
    return (
      <div className="space-y-4" aria-busy="true" aria-live="polite">
        <div className="card h-28 animate-pulse" />
        <div className="card h-14 animate-pulse" />
        <div className="card h-40 animate-pulse" />
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
    <div className="space-y-5">
      {/* Status header */}
      <section className="card px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="label">{heading ?? 'Today’s mystery movie'}</p>
            <p className="mt-1 font-display text-lg font-semibold text-slate-900">
              Guess the Telugu movie
            </p>
          </div>
          <div className="text-right">
            <p className="font-display text-xl font-bold text-slate-900">
              {game.attempts_used}
              <span className="text-slate-400"> / {game.max_attempts}</span>
            </p>
            <p className="text-[0.7rem] uppercase tracking-wider text-slate-500">attempts</p>
          </div>
        </div>
        <div className="mt-3">
          <AttemptPips used={game.attempts_used} max={game.max_attempts} />
        </div>
      </section>

      {/* Guess input */}
      {isActive && !outOfAttempts && (
        <section className="space-y-2">
          <MovieSearch
            onSelect={(movie) => void submitGuess(movie.id)}
            disabled={submitting}
            guessedIds={guessedIds}
          />
          {submitting && <p className="text-xs text-slate-500">Checking your guess…</p>}
        </section>
      )}

      {/* Bonus unlock prompt */}
      {game.bonus_available && (
        <section className="card animate-fade-up p-5 text-center">
          <p className="font-display text-base font-semibold text-slate-900">
            Out of guesses — unlock 3 more?
          </p>
          <p className="mt-1 text-sm text-slate-600">
            You have used all {game.base_attempts} attempts. Take {game.bonus_attempts}{' '}
            more to crack it.
          </p>
          <button
            type="button"
            className="btn-primary mt-4"
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

      {/* Lifelines */}
      <LifelinePanel game={game} clues={clues} onUse={(attr) => void useLifeline(attr)} />

      {/* Feedback -- one panel for the latest guess, with earlier attempts
          collapsed to a single line each. */}
      {guesses.length === 0 ? (
        <div className="card px-5 py-8 text-center">
          <p className="text-sm text-slate-600">
            The mystery movie is a Telugu film released between 2000 and 2023.
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Make your first guess — matching attributes will be revealed.
          </p>
        </div>
      ) : (
        <GuessFeedback guesses={latestFirst} />
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

      {showResult && game.status !== 'active' && (
        <ResultModal game={game} onClose={() => setShowResult(false)} />
      )}
    </div>
  );
}
