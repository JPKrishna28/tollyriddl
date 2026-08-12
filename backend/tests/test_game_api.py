"""End-to-end API tests: game rules, lifelines, bonus attempts, anti-cheat.

The security assertions here are the important ones. The mystery movie
must never appear in any response while a game is active, and every rule
must hold even when the client sends hostile input.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest


def start_game(client, **kwargs) -> dict:
    response = client.post("/api/games/start", json=kwargs or {})
    assert response.status_code == 200, response.text
    return response.json()


def movie_id(sample_movies, title: str) -> int:
    return next(m.id for m in sample_movies if m.title == title)


def _burn_attempts(db_session, game_id: str, count: int) -> None:
    """Advance the attempt counter without submitting real guesses.

    Guessing real movies would also *reveal* attributes, which would then
    make those lifeline cells legitimately unavailable. This isolates the
    unlock-threshold behaviour from the already-known-clue behaviour.
    """
    from app.models import GameSession

    session = db_session.get(GameSession, game_id)
    session.attempts_used = count
    db_session.commit()


class TestStartAndState:
    def test_start_returns_active_game_with_seven_attempts(self, client) -> None:
        game = start_game(client)
        assert game["status"] == "active"
        assert game["attempts_used"] == 0
        assert game["attempts_remaining"] == 7
        assert game["max_attempts"] == 7

    def test_start_never_leaks_the_answer(self, client) -> None:
        game = start_game(client)
        assert "mystery_movie" not in game
        assert "Mystery Film" not in str(game)

    def test_state_survives_a_refresh(self, client, sample_movies) -> None:
        game = start_game(client)
        client.post(
            f"/api/games/{game['game_id']}/guess",
            json={"guess_movie_id": movie_id(sample_movies, "Shares Director")},
        )
        # Simulates the browser reloading and re-fetching the session.
        reloaded = client.get(f"/api/games/{game['game_id']}").json()
        assert reloaded["attempts_used"] == 1
        assert len(reloaded["guesses"]) == 1

    def test_unknown_game_is_404(self, client) -> None:
        assert client.get("/api/games/does-not-exist").status_code == 404


class TestGuessing:
    def test_partial_match_reveals_only_shared_data(self, client, sample_movies) -> None:
        game = start_game(client)
        response = client.post(
            f"/api/games/{game['game_id']}/guess",
            json={"guess_movie_id": movie_id(sample_movies, "Shares Cast And Year")},
        )
        assert response.status_code == 200
        result = response.json()["result"]

        # Same year -> revealed; shared actor -> name revealed.
        assert result["year"]["status"] == "correct"
        assert result["year"]["mystery"] == 2015
        assert [m["name"] for m in result["cast"]["common"]] == ["Actor C"]

        # The actor's billing rank in the *mystery* film stays server-side:
        # sending it would leak ordering the player must deduce.
        assert "mystery_position" not in result["cast"]["common"][0]
        assert result["cast"]["common"][0]["guess_position"] == 1

        # Nothing else is shared, so nothing else is disclosed.
        assert result["director"]["common"] == []
        assert "Director One" not in str(result)
        assert "Actor A" not in str(result)

    def test_losing_guess_hides_the_mystery_year(self, client, sample_movies) -> None:
        game = start_game(client)
        result = client.post(
            f"/api/games/{game['game_id']}/guess",
            json={"guess_movie_id": movie_id(sample_movies, "Shares Nothing")},
        ).json()["result"]

        assert result["year"]["direction"] == "earlier"  # mystery 2015 < guess 2020
        assert "mystery" not in result["year"]
        assert "2015" not in str(result["year"])

    def test_correct_guess_wins_and_reveals_everything(self, client, sample_movies) -> None:
        game = start_game(client)
        payload = client.post(
            f"/api/games/{game['game_id']}/guess",
            json={"guess_movie_id": movie_id(sample_movies, "Mystery Film")},
        ).json()

        assert payload["result"]["is_correct"] is True
        assert payload["game"]["status"] == "won"

        # Only now is the full movie disclosed.
        final = client.get(f"/api/games/{game['game_id']}").json()
        assert final["mystery_movie"]["title"] == "Mystery Film"
        assert final["mystery_movie"]["director"] == ["Director One"]

    def test_duplicate_guess_rejected(self, client, sample_movies) -> None:
        game = start_game(client)
        target = movie_id(sample_movies, "Shares Director")
        client.post(f"/api/games/{game['game_id']}/guess", json={"guess_movie_id": target})

        repeat = client.post(
            f"/api/games/{game['game_id']}/guess", json={"guess_movie_id": target}
        )
        assert repeat.status_code == 409
        assert repeat.json()["detail"]["code"] == "duplicate_guess"

    def test_unknown_movie_id_rejected(self, client) -> None:
        game = start_game(client)
        response = client.post(
            f"/api/games/{game['game_id']}/guess", json={"guess_movie_id": 999999}
        )
        assert response.status_code == 404

    def test_guessing_after_a_win_is_rejected(self, client, sample_movies) -> None:
        game = start_game(client)
        client.post(
            f"/api/games/{game['game_id']}/guess",
            json={"guess_movie_id": movie_id(sample_movies, "Mystery Film")},
        )
        blocked = client.post(
            f"/api/games/{game['game_id']}/guess",
            json={"guess_movie_id": movie_id(sample_movies, "Shares Nothing")},
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "game_complete"

    def test_sparse_movie_does_not_crash_comparison(self, client, sample_movies) -> None:
        game = start_game(client)
        response = client.post(
            f"/api/games/{game['game_id']}/guess",
            json={"guess_movie_id": movie_id(sample_movies, "Sparse Film")},
        )
        assert response.status_code == 200
        assert response.json()["result"]["cast"]["status"] == "unknown"


class TestLifelines:
    def test_locked_before_the_fourth_guess(self, client) -> None:
        game = start_game(client)
        response = client.post(
            f"/api/games/{game['game_id']}/lifeline", json={"attribute": "director"}
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "lifeline_locked"

    def test_unlocks_after_four_guesses(self, client, sample_movies, db_session) -> None:
        game = start_game(client)
        _burn_attempts(db_session, game["game_id"], 4)

        response = client.post(
            f"/api/games/{game['game_id']}/lifeline", json={"attribute": "director"}
        )
        assert response.status_code == 200
        assert response.json()["revealed"]["values"] == ["Director One"]

    def test_already_known_attribute_is_not_offered(self, client, sample_movies) -> None:
        """A clue earned by guessing must not be re-sold as a lifeline."""
        game = start_game(client)
        # "Shares Director" reveals the director through a normal match.
        client.post(
            f"/api/games/{game['game_id']}/guess",
            json={"guess_movie_id": movie_id(sample_movies, "Shares Director")},
        )
        others = [
            m for m in sample_movies
            if m.title not in {"Mystery Film", "Shares Director"}
        ]
        for movie in others[:3]:
            client.post(
                f"/api/games/{game['game_id']}/guess", json={"guess_movie_id": movie.id}
            )

        state = client.get(f"/api/games/{game['game_id']}").json()
        assert "director" not in state["lifelines_available"]

        wasted = client.post(
            f"/api/games/{game['game_id']}/lifeline", json={"attribute": "director"}
        )
        assert wasted.status_code == 409
        assert wasted.json()["detail"]["code"] == "attribute_unavailable"

    def test_same_lifeline_cannot_be_spent_twice(self, client, db_session) -> None:
        game = start_game(client)
        _burn_attempts(db_session, game["game_id"], 4)

        first = client.post(
            f"/api/games/{game['game_id']}/lifeline", json={"attribute": "director"}
        )
        assert first.status_code == 200
        repeat = client.post(
            f"/api/games/{game['game_id']}/lifeline", json={"attribute": "director"}
        )
        assert repeat.status_code == 409

    def test_reveals_one_cell_not_the_whole_row(self, client, db_session) -> None:
        """A lifeline on cast buys a single actor, not the entire cast."""
        game = start_game(client)
        _burn_attempts(db_session, game["game_id"], 4)

        response = client.post(
            f"/api/games/{game['game_id']}/lifeline", json={"attribute": "cast"}
        )
        assert response.status_code == 200
        revealed = response.json()["revealed"]
        # Mystery Film has three actors; only one may cross the wire.
        assert len(revealed["values"]) == 1
        assert revealed["values"][0] in {"Actor A", "Actor B", "Actor C"}
        assert revealed["value_index"] == 0

    def test_player_chooses_which_cell_to_reveal(self, client, db_session) -> None:
        game = start_game(client)
        _burn_attempts(db_session, game["game_id"], 4)

        response = client.post(
            f"/api/games/{game['game_id']}/lifeline",
            json={"attribute": "cast", "value_index": 2},
        )
        assert response.status_code == 200
        assert response.json()["revealed"]["values"] == ["Actor C"]

    def test_multi_valued_attribute_can_be_bought_again(
        self, client, db_session
    ) -> None:
        """cast stays available until every actor has been uncovered."""
        game = start_game(client)
        _burn_attempts(db_session, game["game_id"], 6)

        first = client.post(
            f"/api/games/{game['game_id']}/lifeline",
            json={"attribute": "cast", "value_index": 0},
        )
        assert first.status_code == 200

        state = client.get(f"/api/games/{game['game_id']}").json()
        assert "cast" in state["lifelines_available"]

        second = client.post(
            f"/api/games/{game['game_id']}/lifeline",
            json={"attribute": "cast", "value_index": 1},
        )
        assert second.status_code == 200
        assert second.json()["revealed"]["values"] == ["Actor B"]

    def test_the_same_cell_cannot_be_bought_twice(self, client, db_session) -> None:
        game = start_game(client)
        _burn_attempts(db_session, game["game_id"], 6)

        client.post(
            f"/api/games/{game['game_id']}/lifeline",
            json={"attribute": "cast", "value_index": 1},
        )
        repeat = client.post(
            f"/api/games/{game['game_id']}/lifeline",
            json={"attribute": "cast", "value_index": 1},
        )
        assert repeat.status_code == 409
        assert repeat.json()["detail"]["code"] == "cell_already_revealed"

    def test_out_of_range_cell_rejected(self, client, db_session) -> None:
        game = start_game(client)
        _burn_attempts(db_session, game["game_id"], 4)
        response = client.post(
            f"/api/games/{game['game_id']}/lifeline",
            json={"attribute": "cast", "value_index": 99},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "bad_value_index"

    def test_spent_cells_survive_a_reload(self, client, db_session) -> None:
        """A refreshed client must rebuild exactly the cells it paid for."""
        game = start_game(client)
        _burn_attempts(db_session, game["game_id"], 4)
        client.post(
            f"/api/games/{game['game_id']}/lifeline",
            json={"attribute": "cast", "value_index": 1},
        )

        state = client.get(f"/api/games/{game['game_id']}").json()
        used = state["lifelines_used"]
        assert len(used) == 1
        assert used[0]["values"] == ["Actor B"]
        assert used[0]["value_index"] == 1
        # The unbought actors must not ride along in the payload.
        assert "Actor C" not in str(used)

    def test_unknown_attribute_rejected(self, client, db_session) -> None:
        game = start_game(client)
        _burn_attempts(db_session, game["game_id"], 4)
        response = client.post(
            f"/api/games/{game['game_id']}/lifeline", json={"attribute": "budget"}
        )
        assert response.status_code == 400


class TestBonusAttempts:
    def test_cannot_unlock_early(self, client) -> None:
        game = start_game(client)
        response = client.post(f"/api/games/{game['game_id']}/unlock-bonus")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "bonus_too_early"

    def test_unlock_grants_exactly_three_more(self, client, db_session) -> None:
        from app.models import GameSession

        game = start_game(client)
        # Drive the counter to the base limit without needing 7 movies.
        session = db_session.get(GameSession, game["game_id"])
        session.attempts_used = 7
        db_session.commit()

        payload = client.post(f"/api/games/{game['game_id']}/unlock-bonus").json()
        assert payload["bonus_unlocked"] is True
        assert payload["max_attempts"] == 10
        assert payload["attempts_remaining"] == 3

    def test_cannot_unlock_twice(self, client, db_session) -> None:
        from app.models import GameSession

        game = start_game(client)
        session = db_session.get(GameSession, game["game_id"])
        session.attempts_used = 7
        db_session.commit()

        client.post(f"/api/games/{game['game_id']}/unlock-bonus")
        second = client.post(f"/api/games/{game['game_id']}/unlock-bonus")
        assert second.status_code == 409
        assert second.json()["detail"]["code"] == "bonus_already"

    def test_total_never_exceeds_ten(self, client, db_session) -> None:
        from app.models import GameSession

        game = start_game(client)
        session = db_session.get(GameSession, game["game_id"])
        session.attempts_used = 7
        db_session.commit()
        client.post(f"/api/games/{game['game_id']}/unlock-bonus")

        session = db_session.get(GameSession, game["game_id"])
        session.attempts_used = 10
        db_session.commit()

        state = client.get(f"/api/games/{game['game_id']}").json()
        assert state["attempts_remaining"] == 0
        assert state["max_attempts"] == 10


class TestArchiveAndDates:
    def test_future_date_refused(self, client) -> None:
        tomorrow = (date.today() + timedelta(days=2)).isoformat()
        response = client.post("/api/games/start", json={"game_date": tomorrow})
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "future_date"

    def test_archive_lists_past_dates_only(self, client) -> None:
        payload = client.get("/api/games/archive?limit=5").json()
        today = date.fromisoformat(payload["today"])
        for entry in payload["entries"]:
            assert date.fromisoformat(entry["game_date"]) <= today

    def test_archive_does_not_leak_answers(self, client) -> None:
        payload = client.get("/api/games/archive?limit=5").json()
        assert "Mystery Film" not in str(payload)

    def test_archive_reports_session_outcomes_per_date(
        self, client, db_session, sample_movies
    ) -> None:
        """Each date reports the status of its own sessions.

        The listing resolves every date in one join, so a mix of outcomes
        across dates must not bleed from one entry into another.
        """
        from app.models import DailyGame, GameSession, GameStatus

        today = date.today()
        expected = {
            (today - timedelta(days=1)): GameStatus.WON,
            (today - timedelta(days=2)): GameStatus.LOST,
            (today - timedelta(days=3)): GameStatus.ACTIVE,
        }
        mystery_id = movie_id(sample_movies, "Mystery Film")

        for game_date, status in expected.items():
            daily = DailyGame(game_date=game_date, mystery_movie_id=mystery_id)
            db_session.add(daily)
            db_session.flush()
            db_session.add(
                GameSession(
                    id=f"session-{game_date.isoformat()}",
                    daily_game_id=daily.id,
                    status=status,
                )
            )
        db_session.commit()

        entries = {
            entry["game_date"]: entry["status"]
            for entry in client.get("/api/games/archive?limit=10").json()["entries"]
        }

        assert entries[(today - timedelta(days=1)).isoformat()] == "won"
        assert entries[(today - timedelta(days=2)).isoformat()] == "lost"
        assert entries[(today - timedelta(days=3)).isoformat()] == "in_progress"
        # A date with no DailyGame row at all stays untouched.
        assert entries[(today - timedelta(days=4)).isoformat()] == "not_played"

    def test_client_date_cannot_skip_far_ahead(self, client) -> None:
        """A tampered local clock must not unlock future puzzles."""
        far_future = (date.today() + timedelta(days=400)).isoformat()
        payload = client.get(f"/api/games/today?client_date={far_future}").json()
        # Clamped back to the server's notion of today.
        assert date.fromisoformat(payload["game_date"]) <= date.today() + timedelta(days=1)


class TestDeterministicDailyMovie:
    def test_same_date_always_yields_the_same_movie(self, db_session, sample_movies) -> None:
        from app.services.daily_movie import get_daily_movie_id

        target = date(2026, 5, 5)
        picks = {get_daily_movie_id(db_session, target) for _ in range(5)}
        assert len(picks) == 1

    def test_selection_is_stable_across_processes(self) -> None:
        """Selection must not depend on PYTHONHASHSEED."""
        from app.services.daily_movie import pick_movie_id

        pool = list(range(1, 200))
        first = pick_movie_id(date(2026, 3, 1), pool)
        second = pick_movie_id(date(2026, 3, 1), pool)
        assert first == second

    def test_different_dates_differ(self) -> None:
        from app.services.daily_movie import pick_movie_id

        pool = list(range(1, 200))
        picks = {
            pick_movie_id(date(2026, 3, day), pool) for day in range(1, 15)
        }
        # Consecutive days should not collapse onto one movie.
        assert len(picks) > 10

    def test_empty_pool_returns_none(self) -> None:
        from app.services.daily_movie import pick_movie_id

        assert pick_movie_id(date(2026, 3, 1), []) is None


class TestHealthAndSearch:
    def test_health_reports_database(self, client) -> None:
        payload = client.get("/api/health").json()
        assert payload["status"] == "ok"
        assert payload["database"] is True

    def test_search_returns_minimal_fields_only(self, client) -> None:
        results = client.get("/api/movies/search?q=mystery").json()
        assert results
        # Crew/cast must not be reachable through search.
        for key in ("director", "cast", "genre", "music_director"):
            assert key not in results[0]

    def test_empty_query_returns_nothing(self, client) -> None:
        assert client.get("/api/movies/search?q=").json() == []
