// Game state hook.
//
// Persistence stores only the *game id* per date -- never guesses, never
// anything about the answer. On reload the full state is re-fetched from
// the server, which remains the single source of truth.

import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError, api, localDate } from '@/services/api';
import type {
  GameState,
  GuessResult,
  RevealableAttribute,
  RevealedClue,
} from '@/types/game';

const STORAGE_PREFIX = 'telugu-riddle:game:';

function storageKey(date: string): string {
  return `${STORAGE_PREFIX}${date}`;
}

function readStoredGameId(date: string): string | null {
  try {
    return window.localStorage.getItem(storageKey(date));
  } catch {
    return null; // private mode / storage disabled
  }
}

function storeGameId(date: string, gameId: string): void {
  try {
    window.localStorage.setItem(storageKey(date), gameId);
  } catch {
    /* non-fatal: the game still works, it just will not resume */
  }
}

function clearStoredGame(date: string): void {
  try {
    window.localStorage.removeItem(storageKey(date));
  } catch {
    /* ignore */
  }
}

export interface UseGameResult {
  game: GameState | null;
  guesses: GuessResult[];
  clues: RevealedClue[];
  loading: boolean;
  submitting: boolean;
  error: string | null;
  lastResult: GuessResult | null;
  submitGuess: (movieId: number) => Promise<void>;
  useLifeline: (attribute: RevealableAttribute) => Promise<void>;
  unlockBonus: () => Promise<void>;
  dismissError: () => void;
  reload: () => Promise<void>;
}

export function useGame(gameDate?: string): UseGameResult {
  const date = gameDate ?? localDate();

  const [game, setGame] = useState<GameState | null>(null);
  const [guesses, setGuesses] = useState<GuessResult[]>([]);
  const [clues, setClues] = useState<RevealedClue[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<GuessResult | null>(null);

  // Guards against a late response from a previous date overwriting state.
  const activeDate = useRef(date);

  const applyState = useCallback((next: GameState) => {
    setGame(next);
    if (next.guesses) {
      setGuesses(next.guesses);
    }
  }, []);

  const load = useCallback(async () => {
    activeDate.current = date;
    setLoading(true);
    setError(null);
    setLastResult(null);
    setClues([]);

    try {
      const storedId = readStoredGameId(date);
      if (storedId) {
        try {
          const existing = await api.getGame(storedId);
          if (activeDate.current !== date) return;
          // A stored id from another date must not be reused.
          if (existing.game_date === date) {
            applyState(existing);
            setGuesses(existing.guesses ?? []);
            return;
          }
          clearStoredGame(date);
        } catch (err) {
          // Stale/unknown id (e.g. database reset) -- start fresh.
          if (!(err instanceof ApiError) || err.status !== 404) throw err;
          clearStoredGame(date);
        }
      }

      const fresh = await api.startGame(date);
      if (activeDate.current !== date) return;
      storeGameId(date, fresh.game_id);
      applyState(fresh);
      setGuesses(fresh.guesses ?? []);
    } catch (err) {
      if (activeDate.current !== date) return;
      setError(err instanceof Error ? err.message : 'Could not load the game.');
    } finally {
      if (activeDate.current === date) setLoading(false);
    }
  }, [date, applyState]);

  useEffect(() => {
    void load();
  }, [load]);

  const submitGuess = useCallback(
    async (movieId: number) => {
      if (!game || game.status !== 'active' || submitting) return;
      setSubmitting(true);
      setError(null);
      try {
        const response = await api.guess(game.game_id, movieId);
        setGuesses((previous) => [...previous, { ...response.result, attempt: response.attempt }]);
        setLastResult(response.result);
        setGame((previous) =>
          previous ? { ...previous, ...response.game } : response.game,
        );

        // The win/loss payload carries the answer; re-fetch to pick it up.
        if (response.game.status !== 'active') {
          const complete = await api.getGame(game.game_id);
          applyState(complete);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not submit the guess.');
      } finally {
        setSubmitting(false);
      }
    },
    [game, submitting, applyState],
  );

  const useLifelineAction = useCallback(
    async (attribute: RevealableAttribute) => {
      if (!game || game.status !== 'active') return;
      setError(null);
      try {
        const response = await api.useLifeline(game.game_id, attribute);
        setClues((previous) => [...previous, response.revealed]);
        setGame((previous) =>
          previous ? { ...previous, ...response.game } : previous,
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not use the lifeline.');
      }
    },
    [game],
  );

  const unlockBonus = useCallback(async () => {
    if (!game) return;
    setError(null);
    try {
      const next = await api.unlockBonus(game.game_id);
      applyState(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not unlock extra guesses.');
    }
  }, [game, applyState]);

  return {
    game,
    guesses,
    clues,
    loading,
    submitting,
    error,
    lastResult,
    submitGuess,
    useLifeline: useLifelineAction,
    unlockBonus,
    dismissError: () => setError(null),
    reload: load,
  };
}
