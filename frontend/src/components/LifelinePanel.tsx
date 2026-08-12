// Lifeline controls.
//
// Only attributes the server reports as *available* can be chosen, so a
// clue the player already earned is never offered or wasted.
//
// Picking a clue happens on the board itself: arming a lifeline here makes
// the still-hidden cells in AttributePanel clickable, so the player points at
// the individual cell they want rather than uncovering a whole row at once.

import { ATTRIBUTE_LABELS } from '@/types/game';
import type { GameState, RevealedClue } from '@/types/game';

interface Props {
  game: GameState;
  clues: RevealedClue[];
  /** Arms/disarms cell picking on the board. */
  armed: boolean;
  onArm: (armed: boolean) => void;
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

export function LifelinePanel({ game, clues, armed, onArm, busy }: Props) {
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

        // Only the first usable lifeline drives arming, so two unlocked
        // lifelines cannot both claim the same click on the board.
        const isNextUsable = canUse && used === slot;
        const isArmed = armed && isNextUsable;

        return (
          <div key={threshold} className="flex items-center gap-2">
            <Sparkle />
            <button
              type="button"
              disabled={!isNextUsable || busy}
              aria-pressed={isArmed}
              onClick={() => onArm(!isArmed)}
              className={`flex-1 rounded-full px-4 py-2 text-sm transition-colors ${
                isNextUsable && !busy
                  ? isArmed
                    ? 'bg-arm-500 text-white hover:bg-arm-600'
                    : 'bg-slate-900 text-white hover:bg-slate-700'
                  : 'cursor-not-allowed bg-slate-100 text-slate-400'
              }`}
            >
              {spent
                ? 'Lifeline used'
                : isUnlocked
                  ? available.length === 0
                    ? 'No new clues available'
                    : isArmed
                      ? 'Tap a cell to reveal — cancel'
                      : 'Reveal a cell'
                  : `Unlock Lifeline after ${threshold}th guess`}
            </button>
            <Sparkle />
          </div>
        );
      })}
    </section>
  );
}
