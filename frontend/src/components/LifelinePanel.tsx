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
  /** Blocks a second click while a spend is in flight. */
  busy?: boolean;
}

function Sparkle() {
  return (
    <span aria-hidden className="text-slate-400">
      ✦
    </span>
  );
}

export function LifelinePanel({ game, clues, onUse, busy }: Props) {
  const [picking, setPicking] = useState<number | null>(null);

  const used = game.lifelines_used.length;
  const unlocked = game.lifelines_unlocked;
  const available = game.lifelines_available;
  const thresholds = [4, 6];

  return (
    <section className="space-y-2">
      {thresholds.map((threshold, slot) => {
        const spent = used > slot;
        const isUnlocked = unlocked > slot;
        const canUse =
          game.status === 'active' && isUnlocked && !spent && available.length > 0;
        const clue = clues[slot];

        // A spent lifeline shows what it bought, not a dead button.
        if (spent && clue) {
          return (
            <div
              key={threshold}
              className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"
            >
              <p className="label">{ATTRIBUTE_LABELS[clue.attribute]}</p>
              <p className="mt-0.5 text-sm font-medium text-slate-900">
                {clue.values.join(' · ')}
              </p>
            </div>
          );
        }

        return (
          <div key={threshold} className="flex items-center gap-2">
            <Sparkle />
            {picking === slot ? (
              <div className="flex-1 rounded-lg border border-slate-200 bg-white p-2">
                <p className="mb-1.5 text-xs text-slate-600">
                  Choose a clue to reveal:
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {available.map((attribute) => (
                    <button
                      key={attribute}
                      type="button"
                      disabled={busy}
                      className="btn-ghost px-2.5 py-1 text-xs"
                      onClick={() => {
                        onUse(attribute);
                        setPicking(null);
                      }}
                    >
                      {ATTRIBUTE_LABELS[attribute]}
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  className="mt-1.5 text-xs text-slate-500 underline underline-offset-2
                             hover:text-slate-900"
                  onClick={() => setPicking(null)}
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                type="button"
                disabled={!canUse || busy}
                onClick={() => setPicking(slot)}
                className={`flex-1 rounded-full px-4 py-2 text-sm transition-colors ${
                  canUse && !busy
                    ? 'bg-slate-900 text-white hover:bg-slate-700'
                    : 'cursor-not-allowed bg-slate-100 text-slate-400'
                }`}
              >
                {spent
                  ? 'Lifeline used'
                  : isUnlocked
                    ? available.length > 0
                      ? 'Reveal a cell'
                      : 'No new clues available'
                    : `Unlock Lifeline after ${threshold}th guess`}
              </button>
            )}
            <Sparkle />
          </div>
        );
      })}
    </section>
  );
}
