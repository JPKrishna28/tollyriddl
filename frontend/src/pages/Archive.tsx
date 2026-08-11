// Past games list. Shows only dates and outcomes -- never an answer for a
// puzzle the player has not finished.

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '@/services/api';
import type { ArchiveEntry } from '@/types/game';

const STATUS_STYLES: Record<ArchiveEntry['status'], string> = {
  won: 'chip-match',
  lost: 'chip-miss',
  in_progress: 'chip-gold',
  not_played: 'chip-miss',
};

const STATUS_LABELS: Record<ArchiveEntry['status'], string> = {
  won: 'Won',
  lost: 'Lost',
  in_progress: 'In progress',
  not_played: 'Not played',
};

function formatDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  });
}

export function Archive() {
  const [entries, setEntries] = useState<ArchiveEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await api.archive(30);
        if (!cancelled) setEntries(response.entries);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not load past games.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="space-y-2" aria-busy="true">
        {Array.from({ length: 6 }, (_, index) => (
          <div key={index} className="card h-14 animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="card p-6 text-center text-sm text-slate-300">{error}</div>
    );
  }

  return (
    <div className="space-y-4">
      <header>
        <h1 className="font-display text-xl font-bold text-slate-100">Past games</h1>
        <p className="mt-1 text-sm text-slate-500">
          Replay any previous day’s mystery movie.
        </p>
      </header>

      <ul className="space-y-2">
        {entries.map((entry) => (
          <li key={entry.game_date}>
            <Link
              to={entry.is_today ? '/' : `/game/${entry.game_date}`}
              className="card flex items-center justify-between gap-3 px-4 py-3.5
                         transition-colors hover:bg-white/5"
            >
              <span className="flex min-w-0 items-center gap-2">
                <span className="truncate text-sm font-medium text-slate-100">
                  {formatDate(entry.game_date)}
                </span>
                {entry.is_today && <span className="chip chip-gold">Today</span>}
              </span>
              <span className={`chip ${STATUS_STYLES[entry.status]} shrink-0`}>
                {STATUS_LABELS[entry.status]}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
