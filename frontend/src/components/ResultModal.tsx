// Win / loss modal.
//
// This is the only place the full mystery movie is displayed, and it only
// renders once the server has already ended the game and returned it.

import { useEffect } from 'react';
import { Link } from 'react-router-dom';

import type { GameState, MysteryMovie } from '@/types/game';

interface Props {
  game: GameState;
  onClose: () => void;
}

function Detail({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) return null;
  return (
    <div>
      <p className="label">{label}</p>
      <p className="mt-0.5 text-sm text-slate-800">{values.join(' · ')}</p>
    </div>
  );
}

function formatDuration(seconds: number | null): string | null {
  if (seconds === null) return null;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return minutes > 0 ? `${minutes}m ${remainder}s` : `${remainder}s`;
}

export function ResultModal({ game, onClose }: Props) {
  const won = game.status === 'won';
  const movie: MysteryMovie | undefined = game.mystery_movie;

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  if (!movie) return null;
  const duration = formatDuration(game.duration_seconds);

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="result-title"
      onClick={onClose}
    >
      <div
        className="card animate-pop-in w-full max-w-lg overflow-hidden"
        onClick={(event) => event.stopPropagation()}
      >
        <header
          className={`border-b px-6 py-5 text-center ${
            won
              ? 'border-match-200 bg-match-50'
              : 'border-miss-200 bg-miss-50'
          }`}
        >
          <p className="text-3xl" aria-hidden>
            {won ? '🎉' : '🎬'}
          </p>
          <h2
            id="result-title"
            className={`mt-2 font-display text-2xl font-bold tracking-tight ${
              won ? 'text-match-700' : 'text-miss-700'
            }`}
          >
            {won ? 'You got it!' : 'Game over'}
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            {won
              ? `Solved in ${game.attempts_used} of ${game.max_attempts} attempts`
              : "Today's mystery movie was"}
          </p>
        </header>

        <div className="px-6 pb-2">
          <h3 className="mt-4 text-center font-display text-xl font-semibold text-slate-900">
            {movie.title}
          </h3>
          {movie.year && (
            <p className="mt-0.5 text-center text-sm text-slate-500">{movie.year}</p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4 px-6 py-5">
          <Detail label="Genre" values={movie.genre} />
          <Detail label="Director" values={movie.director} />
          <Detail label="Music" values={movie.music_director} />
          <Detail label="Production" values={movie.production_house} />
          <Detail label="Writer" values={movie.writer} />
          <div className="col-span-2">
            <Detail label="Cast" values={movie.cast} />
          </div>
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-6 py-4">
          <div className="text-xs text-slate-500">
            {duration && <span>Time {duration}</span>}
            {movie.wikipedia_url && (
              <>
                {duration && <span className="mx-2">·</span>}
                <a
                  href={movie.wikipedia_url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="underline underline-offset-2 hover:text-slate-900"
                >
                  Wikipedia
                </a>
              </>
            )}
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn-ghost" onClick={onClose}>
              Close
            </button>
            <Link to="/archive" className="btn-primary">
              Past games
            </Link>
          </div>
        </footer>
      </div>
    </div>
  );
}
