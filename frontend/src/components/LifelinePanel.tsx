// Lifeline controls.
//
// Only attributes the server reports as *available* can be chosen, so a
// clue the player already earned is never offered or wasted.

import { useState } from 'react';

import { ATTRIBUTE_LABELS } from '@/types/game';
import type { GameState, RevealableAttribute, RevealedClue } from '@/types/game';

interface Props {
  game: GameState;
  clues: RevealedClue[];
  onUse: (attribute: RevealableAttribute) => void;
}

export function LifelinePanel({ game, clues, onUse }: Props) {
  const [picking, setPicking] = useState(false);

  const used = game.lifelines_used.length;
  const unlocked = game.lifelines_unlocked;
  const canUse = game.status === 'active' && used < unlocked;
  const available = game.lifelines_available;

  const nextThreshold = used === 0 ? 4 : 6;
  const guessesAway = Math.max(0, nextThreshold - game.attempts_used);

  return (
    <section className="card p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span aria-hidden>🔓</span>
          <h2 className="font-display text-sm font-semibold tracking-wide text-slate-200">
            Lifelines
          </h2>
        </div>
        <span className="text-xs text-slate-500">
          {used} / {game.lifelines_total} used
        </span>
      </div>

      {clues.length > 0 && (
        <ul className="mt-3 space-y-2">
          {clues.map((clue) => (
            <li
              key={clue.attribute}
              className="animate-pop-in rounded-lg border border-gold-500/20 bg-gold-500/5 px-3 py-2"
            >
              <p className="label text-gold-500/80">{ATTRIBUTE_LABELS[clue.attribute]}</p>
              <p className="mt-0.5 text-sm font-medium text-gold-400">
                {clue.values.join(' · ')}
              </p>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3">
        {game.status !== 'active' ? (
          <p className="text-xs text-slate-500">Game complete.</p>
        ) : !canUse ? (
          <p className="text-xs text-slate-500">
            {used >= game.lifelines_total
              ? 'No lifelines left.'
              : `Next lifeline unlocks in ${guessesAway} ${
                  guessesAway === 1 ? 'guess' : 'guesses'
                }.`}
          </p>
        ) : available.length === 0 ? (
          // Refusing to spend a lifeline on nothing is a deliberate rule.
          <p className="text-xs text-slate-500">No new clues available.</p>
        ) : !picking ? (
          <button type="button" className="btn-ghost w-full" onClick={() => setPicking(true)}>
            Reveal a cell
          </button>
        ) : (
          <div className="space-y-2">
            <p className="text-xs text-slate-400">Choose a clue to reveal:</p>
            <div className="flex flex-wrap gap-2">
              {available.map((attribute) => (
                <button
                  key={attribute}
                  type="button"
                  className="btn-ghost px-3 py-1.5 text-xs"
                  onClick={() => {
                    onUse(attribute);
                    setPicking(false);
                  }}
                >
                  {ATTRIBUTE_LABELS[attribute]}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="text-xs text-slate-500 underline underline-offset-2 hover:text-slate-300"
              onClick={() => setPicking(false)}
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
