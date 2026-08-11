// The main game screen.

import { useEffect, useState } from 'react';

import { GuessRow } from '@/components/GuessRow';
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
            index < used ? 'bg-gold-500' : 'bg-white/10'
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
        <p className="text-slate-300">{error ?? 'Could not load the game.'}</p>
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
            <p className="mt-1 font-display text-lg font-semibold text-slate-100">
              Guess the Telugu movie
            </p>
          </div>
          <div className="text-right">
            <p className="font-display text-xl font-bold text-gold-400">
              {game.attempts_used}
              <span className="text-slate-500"> / {game.max_attempts}</span>
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
        <section className="card animate-fade-up border-gold-500/20 p-5 text-center">
          <p className="font-display text-base font-semibold text-slate-100">
            Out of guesses — unlock 3 more?
          </p>
          <p className="mt-1 text-sm text-slate-400">
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
          className="flex items-start justify-between gap-3 rounded-xl border border-red-500/25
                     bg-red-500/10 px-4 py-3 text-sm text-red-200"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={dismissError}
            className="shrink-0 text-red-300/70 hover:text-red-200"
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      )}

      {/* Lifelines */}
      <LifelinePanel game={game} clues={clues} onUse={(attr) => void useLifeline(attr)} />

      {/* Guess history -- newest first so the latest result is visible
          without scrolling on a phone. */}
      <section className="space-y-3">
        {guesses.length === 0 ? (
          <div className="card px-5 py-8 text-center">
            <p className="text-sm text-slate-400">
              The mystery movie is a Telugu film released between 2000 and 2023.
            </p>
            <p className="mt-1 text-xs text-slate-600">
              Make your first guess — matching attributes will be revealed.
            </p>
          </div>
        ) : (
          <>
            <h2 className="label px-1">Your guesses</h2>
            {[...guesses].reverse().map((result, index) => (
              <GuessRow
                key={`${result.movie_id}-${result.attempt ?? index}`}
                result={result}
                attempt={result.attempt ?? guesses.length - index}
                isLatest={index === 0}
              />
            ))}
          </>
        )}
      </section>

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
