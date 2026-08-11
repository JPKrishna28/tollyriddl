// Fixed grid of guess slots.
//
// Every attempt the player is entitled to has a slot from the start, so the
// board never grows as guesses land -- filled slots simply replace empty
// ones. Expanding a filled slot shows what that guess shared.

import { useState } from 'react';

import type { GuessResult } from '@/types/game';

interface Props {
  /** Chronological guess history. */
  guesses: GuessResult[];
  /** Total slots to render (7, or 10 once bonus is unlocked). */
  maxAttempts: number;
}

/** Every value a single guess confirmed, grouped for the expanded view. */
function sharedFrom(result: GuessResult): { label: string; values: string[] }[] {
  const groups = [
    { label: 'Genre', values: result.genre.common },
    { label: 'Cast', values: result.cast.common.map((match) => match.name) },
    { label: 'Director', values: result.director.common },
    { label: 'Production', values: result.production_house.common },
    { label: 'Music', values: result.music_director.common },
    { label: 'Writer', values: result.writer.common },
  ];
  return groups.filter((group) => group.values.length > 0);
}

function FilledSlot({
  index,
  result,
}: {
  index: number;
  result: GuessResult;
}) {
  const [open, setOpen] = useState(false);
  const shared = sharedFrom(result);
  const hasDetail = shared.length > 0 || result.year.status === 'correct';

  return (
    <div
      className={`rounded-lg border ${
        result.is_correct
          ? 'border-match-200 bg-match-50'
          : 'border-slate-200 bg-slate-100'
      }`}
    >
      <button
        type="button"
        onClick={() => hasDetail && setOpen((value) => !value)}
        aria-expanded={hasDetail ? open : undefined}
        className={`flex w-full items-center gap-2 px-3 py-2 text-left ${
          hasDetail ? 'cursor-pointer' : 'cursor-default'
        }`}
      >
        <span className="shrink-0 text-xs font-semibold text-slate-500">
          {index}.
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-900">
          {result.title}
        </span>
        {result.year.guess !== null && (
          <span className="shrink-0 text-xs text-slate-500">
            {result.year.guess}
          </span>
        )}
        {hasDetail && (
          <span
            aria-hidden
            className={`shrink-0 text-slate-400 transition-transform ${
              open ? 'rotate-180' : ''
            }`}
          >
            ⌄
          </span>
        )}
      </button>

      {open && hasDetail && (
        <div className="space-y-1.5 border-t border-slate-200 px-3 py-2">
          {result.year.status === 'correct' && (
            <p className="text-xs text-match-700">Year matches</p>
          )}
          {shared.map((group) => (
            <p key={group.label} className="text-xs text-slate-600">
              <span className="font-semibold text-slate-500">{group.label}: </span>
              {group.values.join(' · ')}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

export function GuessSlots({ guesses, maxAttempts }: Props) {
  // Slot count follows the entitlement, never the history length.
  const slots = Array.from({ length: maxAttempts }, (_, index) => guesses[index]);

  return (
    <div>
      <h2 className="mb-3 text-center font-display text-lg font-bold text-slate-900">
        Guessed Movies
      </h2>
      <div className="grid grid-cols-2 gap-2">
        {slots.map((result, index) => {
          // An odd final slot is centred rather than left hanging in a
          // half-empty row.
          const isLoneLast =
            index === slots.length - 1 && slots.length % 2 === 1;
          const span = isLoneLast ? 'col-span-2 mx-auto w-1/2' : '';

          return result ? (
            <div key={`${result.movie_id}-${index}`} className={span}>
              <FilledSlot index={index + 1} result={result} />
            </div>
          ) : (
            <div
              key={`empty-${index}`}
              className={`flex items-center gap-2 rounded-lg border border-slate-200
                          bg-slate-100 px-3 py-2 ${span}`}
            >
              <span className="text-xs font-semibold text-slate-400">
                {index + 1}.
              </span>
              <span className="flex-1 text-center text-sm text-slate-400">---</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
