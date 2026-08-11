import { Link, NavLink, Route, Routes } from 'react-router-dom';

import { Archive } from '@/pages/Archive';
import { Game } from '@/pages/Game';

function NavItem({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
          isActive ? 'bg-white/10 text-slate-100' : 'text-slate-400 hover:text-slate-200'
        }`
      }
    >
      {children}
    </NavLink>
  );
}

export default function App() {
  return (
    <div className="mx-auto flex min-h-screen w-full max-w-2xl flex-col px-4 pb-16 pt-6 sm:px-6">
      <header className="mb-6">
        <div className="flex items-center justify-between gap-3">
          <Link to="/" className="group flex items-center gap-2">
            <span className="text-xl" aria-hidden>
              🎬
            </span>
            <span className="font-display text-lg font-bold tracking-tight text-slate-50">
              Telugu Riddle
            </span>
          </Link>
          <nav className="flex items-center gap-1">
            <NavItem to="/">Today</NavItem>
            <NavItem to="/archive">Past games</NavItem>
          </nav>
        </div>
        <p className="mt-2 text-sm text-slate-500">
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
                <p className="text-slate-300">Page not found.</p>
                <Link to="/" className="btn-primary mt-4">
                  Back to today’s puzzle
                </Link>
              </div>
            }
          />
        </Routes>
      </main>

      <footer className="mt-10 border-t border-white/5 pt-4 text-center text-xs text-slate-600">
        Movie data from Wikipedia (CC BY-SA 4.0) · 2000–2023
      </footer>
    </div>
  );
}
