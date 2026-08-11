// The single feedback panel.
//
// Only the most recent guess is rendered. Earlier guesses collapse into a
// compact one-line-per-guess list, so the DOM stays a fixed size no matter
// how many attempts the player burns -- this is what keeps the board fast
// after six or seven guesses on a phone.

import type { GuessResult, SetResult } from '@/types/game';

interface Props {
  /** Newest guess first. */
  guesses: GuessResult[];
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
      <span aria-hidden>{isLater ? '↑' : '↓'}</span>
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

/** Counts the attribute groups that produced at least one match. */
function matchCount(result: GuessResult): number {
  const groups: SetResult[] = [
    result.genre,
    result.director,
    result.production_house,
    result.music_director,
    result.writer,
  ];
  const matched = groups.filter((group) => group.common.length > 0).length;
  return (
    matched +
    (result.year.status === 'correct' ? 1 : 0) +
    (result.cast.common.length > 0 ? 1 : 0)
  );
}

export function GuessFeedback({ guesses }: Props) {
  if (guesses.length === 0) return null;

  const [latest, ...earlier] = guesses;
  const correct = latest.is_correct;
  const attempt = latest.attempt ?? guesses.length;

  return (
    <section className="space-y-3" aria-live="polite">
      {/* The verdict banner is keyed on the attempt so React swaps the
          contents of this one node instead of mounting another card. */}
      <article
        key={attempt}
        className={`card animate-fade-up overflow-hidden ${
          correct ? 'border-match-200' : 'border-miss-200'
        }`}
      >
        <header
          className={`flex items-center justify-between gap-3 border-b px-4 py-3 ${
            correct
              ? 'border-match-200 bg-match-50'
              : 'border-miss-200 bg-miss-50'
          }`}
        >
          <div className="flex min-w-0 items-center gap-2.5">
            <span
              className={`grid h-6 w-6 shrink-0 place-items-center rounded-md text-[0.7rem]
                          font-semibold ${
                            correct
                              ? 'bg-match-500 text-white'
                              : 'bg-miss-500 text-white'
                          }`}
            >
              {attempt}
            </span>
            <h3 className="truncate font-display text-base font-semibold text-slate-900">
              {latest.title}
            </h3>
          </div>
          <span
            className={`shrink-0 text-sm font-semibold ${
              correct ? 'text-match-700' : 'text-miss-700'
            }`}
          >
            {correct ? 'Correct' : 'Not it'}
          </span>
        </header>

        <div className="grid grid-cols-2 gap-4 px-4 py-4 sm:grid-cols-3">
          <div>
            <p className="label mb-1.5">Year</p>
            <YearCell result={latest.year} />
          </div>

          <MultiCell label="Genre" result={latest.genre} />

          <div className="col-span-2 sm:col-span-1">
            <p className="label mb-1.5">
              Cast
              {latest.cast.common.length > 0 &&
                ` · ${latest.cast.common.length} shared`}
            </p>
            {latest.cast.common.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {latest.cast.common.map((match) => (
                  <span key={match.name} className="chip chip-match">
                    <span aria-hidden>✓</span>
                    {match.name}
                    {/* Billing position in the mystery film is a real clue. */}
                    <span className="ml-0.5 text-[0.65rem] text-match-600">
                      #{match.mystery_position}
                    </span>
                  </span>
                ))}
              </div>
            ) : (
              <span className="chip chip-miss">
                <span aria-hidden>✗</span>
                {latest.cast.status === 'unknown' ? 'no data' : 'no shared cast'}
              </span>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 border-t border-slate-200 px-4 py-4 sm:grid-cols-4">
          <MultiCell label="Director" result={latest.director} />
          <MultiCell label="Production" result={latest.production_house} />
          <MultiCell label="Music" result={latest.music_director} />
          <MultiCell label="Writer" result={latest.writer} />
        </div>
      </article>

      {earlier.length > 0 && (
        <div className="card overflow-hidden">
          <p className="label border-b border-slate-200 px-4 py-2.5">
            Earlier guesses
          </p>
          <ul className="divide-y divide-slate-100">
            {earlier.map((result, index) => {
              const hits = matchCount(result);
              return (
                <li
                  key={`${result.movie_id}-${result.attempt ?? index}`}
                  className="flex items-center justify-between gap-3 px-4 py-2.5"
                >
                  <span className="flex min-w-0 items-center gap-2.5">
                    <span
                      className="grid h-5 w-5 shrink-0 place-items-center rounded bg-slate-100
                                 text-[0.65rem] font-semibold text-slate-500"
                    >
                      {result.attempt ?? earlier.length - index}
                    </span>
                    <span className="truncate text-sm text-slate-700">
                      {result.title}
                    </span>
                  </span>
                  <span
                    className={`shrink-0 text-xs font-medium ${
                      hits > 0 ? 'text-match-700' : 'text-slate-400'
                    }`}
                  >
                    {hits > 0 ? `${hits} match${hits === 1 ? '' : 'es'}` : 'no match'}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}
