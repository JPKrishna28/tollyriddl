// Thin API client. Every call goes to a same-origin /api path, which works
// both in Vite dev (proxied) and on Vercel (rewrite to the Python function).

import type {
  ArchiveResponse,
  GameState,
  GuessResult,
  MovieSearchItem,
  RevealableAttribute,
  RevealedClue,
  TodayInfo,
} from '@/types/game';

const BASE = import.meta.env.VITE_API_URL ?? '';

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
  } catch {
    // Network-level failure: surface a code the UI can branch on.
    throw new ApiError('Network unavailable. Check your connection.', 'network', 0);
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    let code = 'http_error';
    try {
      const body = await response.json();
      // FastAPI wraps our structured errors inside `detail`.
      const detail = body?.detail;
      if (typeof detail === 'string') {
        message = detail;
      } else if (detail && typeof detail === 'object') {
        message = detail.detail ?? message;
        code = detail.code ?? code;
      }
    } catch {
      /* response had no JSON body; keep the generic message */
    }
    throw new ApiError(message, code, response.status);
  }

  return (await response.json()) as T;
}

/** The player's local calendar date, so the puzzle rolls over at their midnight. */
export function localDate(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

export const api = {
  today: () => request<TodayInfo>(`/api/games/today?client_date=${localDate()}`),

  searchMovies: (query: string, signal?: AbortSignal) =>
    request<MovieSearchItem[]>(
      `/api/movies/search?q=${encodeURIComponent(query)}`,
      { signal },
    ),

  startGame: (gameDate?: string) =>
    request<GameState>('/api/games/start', {
      method: 'POST',
      body: JSON.stringify({
        game_date: gameDate ?? null,
        client_date: localDate(),
      }),
    }),

  getGame: (gameId: string) => request<GameState>(`/api/games/${gameId}`),

  guess: (gameId: string, movieId: number) =>
    request<{ attempt: number; result: GuessResult; game: GameState }>(
      `/api/games/${gameId}/guess`,
      { method: 'POST', body: JSON.stringify({ guess_movie_id: movieId }) },
    ),

  useLifeline: (gameId: string, attribute: RevealableAttribute) =>
    request<{ revealed: RevealedClue; game: GameState }>(
      `/api/games/${gameId}/lifeline`,
      { method: 'POST', body: JSON.stringify({ attribute }) },
    ),

  unlockBonus: (gameId: string) =>
    request<GameState>(`/api/games/${gameId}/unlock-bonus`, { method: 'POST' }),

  archive: (limit = 30) =>
    request<ArchiveResponse>(
      `/api/games/archive?limit=${limit}&client_date=${localDate()}`,
    ),
};
