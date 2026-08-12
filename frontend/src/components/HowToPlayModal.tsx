// "How to play" modal.
//
// Shown automatically the first time someone opens the site, and on demand
// from the header afterwards. Nothing here reads game state, so it is safe
// to render before the puzzle has loaded.

import { useEffect, useRef } from 'react';

interface Props {
  onClose: () => void;
}

function Step({
  number,
  title,
  children,
}: {
  number: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="flex gap-3">
      <span
        aria-hidden
        className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full
                   bg-slate-900 text-xs font-semibold text-white"
      >
        {number}
      </span>
      <div>
        <p className="text-sm font-semibold text-slate-900">{title}</p>
        <p className="mt-0.5 text-sm leading-relaxed text-slate-600">{children}</p>
      </div>
    </li>
  );
}

/** A sample board row, so the colour coding is shown rather than described. */
function Swatch({ className, children }: { className: string; children: string }) {
  return (
    <span
      className={`flex h-8 items-center justify-center truncate rounded-full px-3
                  text-xs font-medium text-white ${className}`}
    >
      {children}
    </span>
  );
}

export function HowToPlayModal({ onClose }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Move focus into the dialog so keyboard and screen-reader users land here.
  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="how-to-play-title"
      onClick={onClose}
    >
      <div
        className="card animate-pop-in my-auto w-full max-w-lg overflow-hidden"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="border-b border-slate-200 px-6 py-5 text-center">
          <p className="text-3xl" aria-hidden>
            🎬
          </p>
          <h2
            id="how-to-play-title"
            className="mt-2 font-display text-2xl font-bold tracking-tight text-slate-900"
          >
            How to play
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            Guess the mystery Telugu movie in 7 attempts. A new puzzle every day.
          </p>
        </header>

        <div className="space-y-5 px-6 py-5">
          <ol className="space-y-4">
            <Step number={1} title="Guess any Telugu movie">
              Type a title in the search box and pick it from the list. Any movie
              from 2000–2023 works — your first guess is just a probe.
            </Step>
            <Step number={2} title="Read what the guess reveals">
              The board fills in with everything your guess{' '}
              <strong className="font-semibold text-slate-800">shares</strong> with
              the mystery movie: same actors, same director, same genre, and so on.
            </Step>
            <Step number={3} title="Narrow the year">
              Each guess tells you whether the answer is earlier or later, so the
              year range tightens with every attempt.
            </Step>
            <Step number={4} title="Use your lifelines">
              After guess 4 and guess 6 you unlock a lifeline. Each one reveals a
              cell of your choice outright — a director, the year, the cast.
            </Step>
            <Step number={5} title="Run out? Take 3 more">
              If all 7 attempts are gone you can unlock 3 bonus guesses instead of
              losing.
            </Step>
          </ol>

          <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="label">The board</p>
            <div className="mt-2 grid grid-cols-3 gap-2">
              <Swatch className="bg-miss-500">2004</Swatch>
              <Swatch className="bg-match-500">Actor</Swatch>
              <Swatch className="bg-crew-500">Director</Swatch>
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2">
              <span
                aria-hidden
                className="h-8 rounded-full bg-slate-400 opacity-40 blur-[6px]"
              />
              <span
                aria-hidden
                className="h-8 rounded-full bg-slate-400 opacity-40 blur-[6px]"
              />
              <span
                aria-hidden
                className="h-8 rounded-full bg-slate-400 opacity-40 blur-[6px]"
              />
            </div>
            <p className="mt-3 text-sm leading-relaxed text-slate-600">
              A coloured pill is something you have{' '}
              <strong className="font-semibold text-slate-800">confirmed</strong> about
              the answer. A blurred bar is a slot you have not earned yet — the game
              never shows you a value you did not uncover.
            </p>
          </section>
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-slate-200 px-6 py-4">
          <button ref={closeRef} type="button" className="btn-primary" onClick={onClose}>
            Got it
          </button>
        </footer>
      </div>
    </div>
  );
}
