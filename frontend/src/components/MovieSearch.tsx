// Autocomplete search box with keyboard navigation.

import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '@/services/api';
import type { MovieSearchItem } from '@/types/game';

interface Props {
  onSelect: (movie: MovieSearchItem) => void;
  disabled?: boolean;
  guessedIds: number[];
  placeholder?: string;
}

export function MovieSearch({ onSelect, disabled, guessedIds, placeholder }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<MovieSearchItem[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [highlighted, setHighlighted] = useState(0);

  const containerRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const term = query.trim();
    if (term.length < 2) {
      setResults([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    // Debounce so typing does not fire a request per keystroke.
    const timer = window.setTimeout(async () => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const found = await api.searchMovies(term, controller.signal);
        setResults(found);
        setHighlighted(0);
        setOpen(true);
      } catch (err) {
        if ((err as Error).name !== 'AbortError') setResults([]);
      } finally {
        setLoading(false);
      }
    }, 220);

    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    function onClickOutside(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  const choose = useCallback(
    (movie: MovieSearchItem) => {
      if (guessedIds.includes(movie.id)) return; // already used this attempt
      onSelect(movie);
      setQuery('');
      setResults([]);
      setOpen(false);
    },
    [onSelect, guessedIds],
  );

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || results.length === 0) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setHighlighted((index) => (index + 1) % results.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setHighlighted((index) => (index - 1 + results.length) % results.length);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const movie = results[highlighted];
      if (movie) choose(movie);
    } else if (event.key === 'Escape') {
      setOpen(false);
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <div className="relative">
        <span
          className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500"
          aria-hidden
        >
          ⌕
        </span>
        <input
          type="text"
          value={query}
          disabled={disabled}
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={placeholder ?? 'Search a Telugu movie…'}
          className="w-full rounded-xl border border-slate-300 bg-white py-3.5 pl-11 pr-4
                     text-base text-slate-900 placeholder:text-slate-400
                     focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200
                     disabled:opacity-50"
          role="combobox"
          aria-expanded={open}
          aria-controls="movie-search-results"
          aria-autocomplete="list"
        />
        {loading && (
          <span className="absolute right-4 top-1/2 -translate-y-1/2 text-xs text-slate-500">
            …
          </span>
        )}
      </div>

      {open && (
        <ul
          id="movie-search-results"
          role="listbox"
          className="absolute z-30 mt-2 max-h-72 w-full overflow-y-auto rounded-xl border
                     border-slate-200 bg-white shadow-lg divide-y divide-slate-100"
        >
          {results.length === 0 && !loading && (
            <li className="px-4 py-3 text-sm text-slate-500">
              No movies match “{query.trim()}”.
            </li>
          )}
          {results.map((movie, index) => {
            const already = guessedIds.includes(movie.id);
            return (
              <li key={movie.id} role="option" aria-selected={index === highlighted}>
                <button
                  type="button"
                  disabled={already}
                  onMouseEnter={() => setHighlighted(index)}
                  onClick={() => choose(movie)}
                  className={`flex w-full items-center justify-between gap-3 px-4 py-3 text-left
                              text-sm transition-colors
                              ${index === highlighted ? 'bg-slate-50' : ''}
                              ${already ? 'cursor-not-allowed opacity-40' : 'hover:bg-slate-50'}`}
                >
                  <span className="truncate font-medium text-slate-900">{movie.title}</span>
                  <span className="shrink-0 text-xs text-slate-500">
                    {already ? 'already guessed' : movie.year ?? ''}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
