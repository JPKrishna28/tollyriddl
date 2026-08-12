// Shared types mirroring the backend payloads.
// Note what is absent: there is no field carrying the mystery movie while
// a game is active. `mysteryMovie` only appears once status is won/lost.

export type GameStatus = 'active' | 'won' | 'lost';

export type AttributeStatus = 'correct' | 'partial' | 'absent' | 'unknown';

export type YearDirection = 'same' | 'earlier' | 'later' | 'unknown';

export type RevealableAttribute =
  | 'year'
  | 'genre'
  | 'cast'
  | 'director'
  | 'production_house'
  | 'music_director'
  | 'writer';

export interface MovieSearchItem {
  id: number;
  title: string;
  year: number | null;
}

export interface YearResult {
  guess: number | null;
  status: AttributeStatus;
  direction: YearDirection;
  /** Present only when the guess year equals the mystery year. */
  mystery?: number;
}

export interface SetResult {
  guess: string[];
  common: string[];
  status: AttributeStatus;
}

export interface CastMatch {
  name: string;
  position: number;
  guess_position: number;
  /** Billing rank in the mystery film is intentionally not sent by the API. */
}

export interface CastResult {
  guess: string[];
  common: CastMatch[];
  common_count: number;
  status: AttributeStatus;
}

export interface GuessResult {
  movie_id: number;
  title: string;
  is_correct: boolean;
  year: YearResult;
  genre: SetResult;
  cast: CastResult;
  director: SetResult;
  production_house: SetResult;
  music_director: SetResult;
  writer: SetResult;
  /** Attempt number, attached when replaying history. */
  attempt?: number;
}

export interface MysteryMovie {
  id: number;
  title: string;
  year: number | null;
  language: string;
  genre: string[];
  cast: string[];
  director: string[];
  production_house: string[];
  music_director: string[];
  writer: string[];
  wikipedia_url: string | null;
}

export interface LifelineUsed {
  lifeline_number: number;
  attribute: RevealableAttribute;
  /** Which cell of the attribute this lifeline uncovered. */
  value_index: number;
  /** The single value bought, so a reload can rebuild the board. */
  values: string[];
}

export interface GameState {
  game_id: string;
  game_date: string;
  status: GameStatus;
  attempts_used: number;
  attempts_remaining: number;
  max_attempts: number;
  base_attempts: number;
  bonus_attempts: number;
  bonus_unlocked: boolean;
  bonus_available: boolean;
  lifelines_used: LifelineUsed[];
  lifelines_unlocked: number;
  lifelines_total: number;
  lifelines_available: RevealableAttribute[];
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  guesses?: GuessResult[];
  /** Only sent after the game ends. */
  mystery_movie?: MysteryMovie;
}

export interface RevealedClue {
  attribute: RevealableAttribute;
  /** Always a single value: a lifeline buys one cell, not a whole row. */
  values: string[];
  value_index: number;
  lifeline_number: number;
}

export interface ArchiveEntry {
  game_date: string;
  is_today: boolean;
  status: 'not_played' | 'won' | 'lost' | 'in_progress';
}

export interface ArchiveResponse {
  today: string;
  entries: ArchiveEntry[];
}

export interface TodayInfo {
  game_date: string;
  available: boolean;
  base_attempts: number;
  bonus_attempts: number;
  lifeline_1_after: number;
  lifeline_2_after: number;
}

export const ATTRIBUTE_LABELS: Record<RevealableAttribute, string> = {
  year: 'Year',
  genre: 'Genre',
  cast: 'Cast',
  director: 'Director',
  production_house: 'Production',
  music_director: 'Music',
  writer: 'Writer',
};
