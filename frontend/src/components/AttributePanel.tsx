// Progressive attribute board.
//
// Accumulates everything the player has *confirmed* about the mystery
// movie: values shared with a guess, plus whatever a lifeline revealed.
// Nothing here is ever derived from the answer directly -- an unearned
// cell stays blurred, so the panel can never leak ahead of play.

import { useMemo } from 'react';

import type {
  GuessResult,
  RevealableAttribute,
  RevealedClue,
  SetResult,
} from '@/types/game';

interface Props {
  /** Chronological guess history. */
  guesses: GuessResult[];
  /** Cells bought with a lifeline. */
  clues: RevealedClue[];
  /** Bounds shown before the year is pinned down. */
  yearFloor?: number;
  yearCeiling?: number;
  /**
   * Lifeline targeting. When armed, still-hidden rows become buttons and
   * clicking one spends the lifeline on that attribute.
   */
  revealMode?: boolean;
  revealable?: RevealableAttribute[];
  onReveal?: (attribute: RevealableAttribute) => void;
}

type Group = 'year' | 'cast' | 'crew';

/** How many slots a group shows before anything is known. */
const PLACEHOLDER_COUNT: Record<string, number> = {
  genre: 3,
  cast: 9,
  director: 1,
  production_house: 2,
  music_director: 1,
  writer: 1,
};

const GROUP_STYLES: Record<Group, { ring: string; fill: string; text: string }> = {
  // Muted, not the mockup's saturated blocks -- keeps the white theme.
  year: {
    ring: 'ring-miss-200',
    fill: 'bg-miss-500',
    text: 'text-white',
  },
  cast: {
    ring: 'ring-match-200',
    fill: 'bg-match-500',
    text: 'text-white',
  },
  crew: {
    ring: 'ring-crew-200',
    fill: 'bg-crew-500',
    text: 'text-white',
  },
};

/** Union of every value confirmed for one set-valued attribute. */
function confirmedValues(
  guesses: GuessResult[],
  clues: RevealedClue[],
  key: keyof Pick<
    GuessResult,
    'genre' | 'director' | 'production_house' | 'music_director' | 'writer'
  >,
): string[] {
  const found = new Set<string>();
  for (const guess of guesses) {
    const result = guess[key] as SetResult;
    for (const value of result.common) found.add(value);
  }
  // A lifeline reveals the cell outright, so it supersedes partial matches.
  const clue = clues.find((entry) => entry.attribute === key);
  if (clue) for (const value of clue.values) found.add(value);
  return [...found];
}

function confirmedCast(guesses: GuessResult[], clues: RevealedClue[]): string[] {
  const found = new Set<string>();
  for (const guess of guesses) {
    for (const match of guess.cast.common) found.add(match.name);
  }
  const clue = clues.find((entry) => entry.attribute === 'cast');
  if (clue) for (const value of clue.values) found.add(value);
  return [...found];
}

function Pill({
  value,
  group,
}: {
  value: string | null;
  group: Group;
}) {
  const style = GROUP_STYLES[group];

  if (value === null) {
    // Unearned: a blurred bar that shows a slot exists without hinting
    // at its contents.
    return (
      <span
        aria-hidden
        className={`h-9 rounded-full ${style.fill} opacity-40 blur-[6px]`}
      />
    );
  }

  return (
    <span
      className={`flex h-9 items-center justify-center truncate rounded-full px-3
                  text-sm font-medium ${style.fill} ${style.text}`}
      title={value}
    >
      {value}
    </span>
  );
}

/** One labelled attribute row: known values first, then blurred slots. */
function Row({
  label,
  values,
  group,
  slots,
  columns,
  hint,
  revealable,
  onReveal,
}: {
  label: string;
  values: string[];
  group: Group;
  slots: number;
  columns: string;
  hint?: string;
  /** When true this row can be clicked to spend a lifeline on it. */
  revealable?: boolean;
  onReveal?: () => void;
}) {
  // Never shrink below what the player has actually earned.
  const total = Math.max(slots, values.length);
  const cells = Array.from({ length: total }, (_, index) => values[index] ?? null);

  const grid = (
    <div className={`grid gap-2 ${columns}`}>
      {cells.map((value, index) => (
        <Pill key={`${label}-${index}`} value={value} group={group} />
      ))}
    </div>
  );

  return (
    <div>
      <div className="mb-2 flex items-center justify-center gap-1.5">
        <h3 className="font-display text-sm font-semibold tracking-wide text-slate-700">
          {label}
        </h3>
        {hint && (
          <span
            title={hint}
            aria-label={hint}
            className="grid h-4 w-4 cursor-help place-items-center rounded-full
                       border border-slate-300 text-[0.6rem] text-slate-500"
          >
            i
          </span>
        )}
      </div>
      {revealable && onReveal ? (
        <button
          type="button"
          onClick={onReveal}
          aria-label={`Reveal ${label} with a lifeline`}
          className="w-full rounded-xl p-1 ring-2 ring-arm-400 ring-offset-2
                     transition-transform hover:scale-[1.02] focus:outline-none
                     focus-visible:ring-arm-600"
        >
          {grid}
        </button>
      ) : (
        grid
      )}
    </div>
  );
}

export function AttributePanel({
  guesses,
  clues,
  yearFloor = 2000,
  yearCeiling = 2023,
  revealMode = false,
  revealable = [],
  onReveal,
}: Props) {
  /** A row is clickable only while a lifeline is armed and still unspent here. */
  const canReveal = (attribute: RevealableAttribute) =>
    revealMode && revealable.includes(attribute);

  const revealProps = (attribute: RevealableAttribute) => ({
    revealable: canReveal(attribute),
    onReveal: onReveal ? () => onReveal(attribute) : undefined,
  });

  const known = useMemo(() => {
    // Narrow the year window using each guess's earlier/later direction.
    // A wrong guess still teaches the player which side the answer is on.
    let low = yearFloor;
    let high = yearCeiling;
    let exact: number | null = null;

    for (const guess of guesses) {
      const { guess: guessed, status, direction } = guess.year;
      if (guessed === null) continue;
      if (status === 'correct') {
        exact = guessed;
      } else if (direction === 'later') {
        low = Math.max(low, guessed + 1);
      } else if (direction === 'earlier') {
        high = Math.min(high, guessed - 1);
      }
    }

    const yearClue = clues.find((entry) => entry.attribute === 'year');
    if (yearClue && yearClue.values[0]) exact = Number(yearClue.values[0]);

    return {
      yearLow: low,
      yearHigh: high,
      yearExact: exact,
      genre: confirmedValues(guesses, clues, 'genre'),
      cast: confirmedCast(guesses, clues),
      director: confirmedValues(guesses, clues, 'director'),
      production: confirmedValues(guesses, clues, 'production_house'),
      music: confirmedValues(guesses, clues, 'music_director'),
      writer: confirmedValues(guesses, clues, 'writer'),
    };
  }, [guesses, clues, yearFloor, yearCeiling]);

  return (
    <div className="space-y-4">
      {/* Year + genre */}
      <section className="rounded-2xl border border-miss-200 bg-slate-50 p-4">
        <h3 className="mb-2 text-center font-display text-sm font-semibold tracking-wide text-slate-700">
          Year of Release
        </h3>
        <div
          className={`flex items-center justify-center gap-3 ${
            canReveal('year')
              ? 'cursor-pointer rounded-xl p-1 ring-2 ring-arm-400 ring-offset-2'
              : ''
          }`}
          {...(canReveal('year') && onReveal
            ? {
                role: 'button',
                tabIndex: 0,
                'aria-label': 'Reveal Year with a lifeline',
                onClick: () => onReveal('year'),
                onKeyDown: (event: React.KeyboardEvent) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onReveal('year');
                  }
                },
              }
            : {})}
        >
          {known.yearExact !== null ? (
            <span
              className="flex h-9 min-w-[7rem] items-center justify-center rounded-full
                         bg-miss-500 px-4 text-sm font-semibold text-white"
            >
              {known.yearExact}
            </span>
          ) : (
            <>
              <span
                className="flex h-9 flex-1 items-center justify-center rounded-full
                           bg-miss-500 text-sm font-medium text-white"
              >
                {known.yearLow}
              </span>
              <span aria-hidden className="text-slate-400">
                ←→
              </span>
              <span
                className="flex h-9 flex-1 items-center justify-center rounded-full
                           bg-miss-500 text-sm font-medium text-white"
              >
                {known.yearHigh}
              </span>
            </>
          )}
        </div>

        <div className="mt-4">
          <Row
            label="Genre"
            values={known.genre}
            group="year"
            slots={PLACEHOLDER_COUNT.genre}
            columns="grid-cols-3"
            hint="Genres shared with a movie you guessed."
            {...revealProps('genre')}
          />
        </div>
      </section>

      {/* Cast */}
      <section className="rounded-2xl border border-match-200 bg-slate-50 p-4">
        <Row
          label="Cast"
          values={known.cast}
          group="cast"
          slots={PLACEHOLDER_COUNT.cast}
          columns="grid-cols-3"
          hint="Actors shared with a movie you guessed."
          {...revealProps('cast')}
        />
      </section>

      {/* Crew */}
      <section className="space-y-4 rounded-2xl border border-crew-200 bg-slate-50 p-4">
        <Row
          label="Director"
          values={known.director}
          group="crew"
          slots={PLACEHOLDER_COUNT.director}
          columns="grid-cols-1"
          {...revealProps('director')}
        />
        <Row
          label="Production House"
          values={known.production}
          group="crew"
          slots={PLACEHOLDER_COUNT.production_house}
          columns="grid-cols-2"
          {...revealProps('production_house')}
        />
        <Row
          label="Music Director"
          values={known.music}
          group="crew"
          slots={PLACEHOLDER_COUNT.music_director}
          columns="grid-cols-1"
          {...revealProps('music_director')}
        />
        <Row
          label="Writer"
          values={known.writer}
          group="crew"
          slots={PLACEHOLDER_COUNT.writer}
          columns="grid-cols-1"
          {...revealProps('writer')}
        />
      </section>
    </div>
  );
}
