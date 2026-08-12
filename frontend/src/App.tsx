import { useEffect, useState } from 'react';
import { Link, NavLink, Route, Routes } from 'react-router-dom';

import { HowToPlayModal } from '@/components/HowToPlayModal';
import { Archive } from '@/pages/Archive';
import { Game } from '@/pages/Game';

/** Set once the player has seen the instructions, so they open only on a first visit. */
const SEEN_KEY = 'telugu-riddle:seen-how-to-play';

function NavItem({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
          isActive ? 'bg-slate-100 text-slate-900' : 'text-slate-500 hover:text-slate-900'
        }`
      }
    >
      {children}
    </NavLink>
  );
}

/** Storage is unavailable in some privacy modes; a failed read just means "show it". */
function hasSeenInstructions(): boolean {
  try {
    return window.localStorage.getItem(SEEN_KEY) === '1';
  } catch {
    return false;
  }
}

function markInstructionsSeen() {
  try {
    window.localStorage.setItem(SEEN_KEY, '1');
  } catch {
    // Not being able to remember is harmless -- the modal is dismissable.
  }
}

export default function App() {
  const [showHowToPlay, setShowHowToPlay] = useState(false);

  // Open automatically for a first-time visitor.
  useEffect(() => {
    if (!hasSeenInstructions()) setShowHowToPlay(true);
  }, []);

  function closeHowToPlay() {
    markInstructionsSeen();
    setShowHowToPlay(false);
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-5xl flex-col px-4 pb-16 pt-6 sm:px-6">
      <header className="mb-6">
        <div className="flex items-center justify-between gap-3">
          <Link to="/" className="group flex items-center gap-2">
            <span className="text-xl" aria-hidden>
              🎬
            </span>
            <span className="font-display text-lg font-bold tracking-tight text-slate-900">
              Telugu Riddle
            </span>
          </Link>
          <nav className="flex items-center gap-1">
            <NavItem to="/">Today</NavItem>
            <NavItem to="/archive">Past games</NavItem>
            <button
              type="button"
              onClick={() => setShowHowToPlay(true)}
              aria-label="How to play"
              title="How to play"
              className="grid h-8 w-8 place-items-center rounded-full border border-slate-200
                         text-sm font-semibold text-slate-500 transition-colors
                         hover:border-slate-300 hover:text-slate-900"
            >
              ?
            </button>
          </nav>
        </div>
        <p className="mt-2 text-sm text-slate-600">
          Guess the mystery Telugu movie in 7 attempts.
        </p>
      </header>

      <main className="flex-1">
        <Routes>
          <Route path="/" element={<Game />} />
          <Route path="/game/:date" element={<Game />} />
          <Route path="/archive" element={<Archive />} />
          <Route
            path="*"
            element={
              <div className="card p-8 text-center">
                <p className="text-slate-600">Page not found.</p>
                <Link to="/" className="btn-primary mt-4">
                  Back to today’s puzzle
                </Link>
              </div>
            }
          />
        </Routes>
      </main>

      <footer className="mt-10 border-t border-slate-200 pt-4 text-center text-xs text-slate-500">
        <button
          type="button"
          onClick={() => setShowHowToPlay(true)}
          className="underline underline-offset-2 hover:text-slate-900"
        >
          How to play
        </button>
        <span className="mx-2">·</span>
        Movie data from Wikipedia (CC BY-SA 4.0) · 2000–2023
      </footer>

      {showHowToPlay && <HowToPlayModal onClose={closeHowToPlay} />}
    </div>
  );
}
