// One guess, rendered as a card.
//
// Cards (not a wide table) are the primary layout so the board never
// scrolls horizontally on a 360px phone.

import type { GuessResult, SetResult } from '@/types/game';

interface Props {
  result: GuessResult;
  attempt: number;
  isLatest?: boolean;
}

function YearCell({ result }: { result: GuessResult['year'] }) {
  const { guess, direction, status } = result;

  if (status === 'unknown' || guess === null) {
    return <span className="chip chip-miss">Year unknown</span>;
  }
  if (status === 'correct') {
    return (
      <span className="chip chip-match">
        <span aria-hidden>✓</span> {guess}
      </span>
    );
  }
  // Direction only -- the mystery year itself is never shown here.
  const isLater = direction === 'later';
  return (
    <span className="chip chip-miss">
      <span aria-hidden className="text-gold-400">
        {isLater ? '↑' : '↓'}
      </span>
      {guess}
      <span className="ml-1 text-[0.65rem] text-slate-500">
        {isLater ? 'later' : 'earlier'}
      </span>
    </span>
  );
}

function MultiCell({ label, result }: { label: string; result: SetResult }) {
  const hasMatch = result.common.length > 0;
  return (
    <div>
      <p className="label mb-1.5">{label}</p>
      {hasMatch ? (
        <div className="flex flex-wrap gap-1.5">
          {result.common.map((value) => (
            <span key={value} className="chip chip-match">
              <span aria-hidden>✓</span> {value}
            </span>
          ))}
        </div>
      ) : (
        <span className="chip chip-miss" aria-label={`${label}: no match`}>
          <span aria-hidden>✗</span>
          {result.status === 'unknown' ? 'no data' : 'no match'}
        </span>
      )}
    </div>
  );
}

export function GuessRow({ result, attempt, isLatest }: Props) {
  const castMatches = result.cast.common;

  return (
    <article
      className={`card overflow-hidden ${isLatest ? 'animate-fade-up ring-1 ring-gold-500/25' : ''}`}
    >
      <header className="flex items-center justify-between gap-3 border-b border-white/5 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-white/5
                       text-[0.7rem] font-semibold text-slate-400"
          >
            {attempt}
          </span>
          <h3 className="truncate font-display text-base font-semibold text-slate-100">
            {result.title}
          </h3>
        </div>
        {result.is_correct && (
          <span className="chip chip-gold shrink-0">Correct</span>
        )}
      </header>

      <div className="grid grid-cols-2 gap-4 px-4 py-4 sm:grid-cols-3">
        <div>
          <p className="label mb-1.5">Year</p>
          <YearCell result={result.year} />
        </div>

        <MultiCell label="Genre" result={result.genre} />

        <div className="col-span-2 sm:col-span-1">
          <p className="label mb-1.5">
            Cast{castMatches.length > 0 && ` · ${castMatches.length} shared`}
          </p>
          {castMatches.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {castMatches.map((match) => (
                <span key={match.name} className="chip chip-match">
                  <span aria-hidden>✓</span>
                  {match.name}
                  {/* Billing position in the mystery film is a real clue. */}
                  <span className="ml-0.5 text-[0.65rem] text-match-400/70">
                    #{match.mystery_position}
                  </span>
                </span>
              ))}
            </div>
          ) : (
            <span className="chip chip-miss">
              <span aria-hidden>✗</span>
              {result.cast.status === 'unknown' ? 'no data' : 'no shared cast'}
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 border-t border-white/5 px-4 py-4 sm:grid-cols-4">
        <MultiCell label="Director" result={result.director} />
        <MultiCell label="Production" result={result.production_house} />
        <MultiCell label="Music" result={result.music_director} />
        <MultiCell label="Writer" result={result.writer} />
      </div>
    </article>
  );
}
