"""NFL remaining-score model. Situation is optional and is not a rating update."""

from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

import pytest

from mswp import (
    GameState,
    NFLModel,
    NFL_CONFIG,
    NFL_PLAYOFF_CONFIG,
    SportModel,
    compute_wp,
)
from mswp.football.model import football_win_probability, team_points_per_second

from live_wp.replay import config_for_state, load_replay

AS_OF = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)


def nfl_state(**overrides) -> GameState:
    fields = dict(
        sport="nfl",
        game_id="test-game",
        home="Home",
        away="Away",
        home_score=0,
        away_score=0,
        period=1,
        seconds_remaining_period=15 * 60,
        seconds_remaining_total=60 * 60,
        status="pre",
        source="test",
        as_of=AS_OF,
        prior_home=0.5,
    )
    fields.update(overrides)
    return GameState(**fields)


def test_tipoff_with_prior_0_60_stays_about_0_60():
    state = nfl_state(prior_home=0.60, status="pre")
    wp = compute_wp(state, 0.60, NFL_CONFIG)
    assert wp == pytest.approx(0.60, abs=1e-9)


def test_home_up_18_with_about_one_minute_in_q4():
    state = nfl_state(
        status="live",
        period=4,
        seconds_remaining_period=60,
        seconds_remaining_total=60,
        home_score=27,
        away_score=9,
        prior_home=0.50,
    )
    wp = compute_wp(state, 0.50, NFL_CONFIG)
    assert wp == 0.9999

    trailing = nfl_state(
        status="live",
        period=4,
        seconds_remaining_period=60,
        seconds_remaining_total=60,
        home_score=9,
        away_score=27,
        prior_home=0.50,
    )
    assert compute_wp(trailing, 0.50, NFL_CONFIG) == 0.0001


def test_tie_at_0_00_q4_uses_the_ot_path():
    tied = nfl_state(
        status="live",
        period=4,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=20,
        away_score=20,
        prior_home=0.60,
    )
    wp = compute_wp(tied, 0.60, NFL_CONFIG)
    # A 0.60 team is a small favorite to start a 10-minute overtime.
    assert 0.5 < wp < 0.75

    decided = nfl_state(
        status="live",
        period=4,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=21,
        away_score=20,
        prior_home=0.60,
    )
    assert compute_wp(decided, 0.60, NFL_CONFIG) == 1.0

    decided_loss = nfl_state(
        status="live",
        period=4,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=20,
        away_score=21,
        prior_home=0.60,
    )
    assert compute_wp(decided_loss, 0.60, NFL_CONFIG) == 0.0


def test_same_state_twice_is_deterministic():
    state = nfl_state(
        status="live",
        period=3,
        seconds_remaining_period=412,
        seconds_remaining_total=15 * 60 + 412,
        home_score=14,
        away_score=17,
        prior_home=0.47,
    )
    assert compute_wp(state, 0.47, NFL_CONFIG) == compute_wp(state, 0.47, NFL_CONFIG)


def test_missing_optional_football_fields_still_returns_a_number():
    state = nfl_state(
        status="live",
        period=2,
        seconds_remaining_period=500,
        seconds_remaining_total=2 * 15 * 60 + 500,
        home_score=7,
        away_score=3,
        prior_home=0.55,
    )
    assert state.down is None
    assert state.distance is None
    assert state.yardline is None
    assert state.possession is None
    assert state.timeouts is None

    wp = compute_wp(state, state.prior_home, NFL_CONFIG)
    assert isinstance(wp, float)
    assert 0.0001 <= wp <= 0.9999

    timeouts_only = nfl_state(
        status="live",
        period=2,
        seconds_remaining_period=500,
        seconds_remaining_total=2 * 15 * 60 + 500,
        home_score=7,
        away_score=3,
        prior_home=0.55,
        timeouts={"home": 3, "away": 2},
    )
    assert compute_wp(timeouts_only, 0.55, NFL_CONFIG) == wp

    partial = nfl_state(
        status="live",
        period=2,
        seconds_remaining_period=500,
        seconds_remaining_total=2 * 15 * 60 + 500,
        home_score=7,
        away_score=3,
        prior_home=0.55,
        down=3,
        distance=7,
        possession="home",
    )
    assert partial.yardline is None
    assert compute_wp(partial, 0.55, NFL_CONFIG) == wp


def _live_situation(**overrides) -> GameState:
    fields = dict(
        status="live",
        period=3,
        seconds_remaining_period=8 * 60,
        seconds_remaining_total=8 * 60 + 15 * 60,
        home_score=14,
        away_score=14,
        prior_home=0.5,
        down=1,
        distance=10,
        yardline=45,
        possession="home",
    )
    fields.update(overrides)
    return nfl_state(**fields)


def test_missing_any_situation_field_matches_clock_and_score():
    full = _live_situation()
    bare = _live_situation(down=None, distance=None, yardline=None, possession=None)
    bare_wp = compute_wp(bare, 0.5, NFL_CONFIG)
    for name in ("down", "distance", "yardline", "possession"):
        partial = _live_situation(**{name: None})
        assert compute_wp(partial, 0.5, NFL_CONFIG) == bare_wp
    assert compute_wp(full, 0.5, NFL_CONFIG) != bare_wp


def test_opponent_ten_is_better_for_the_team_with_the_ball():
    own_ten = _live_situation(yardline=10)
    opponent_ten = _live_situation(yardline=90)
    assert compute_wp(opponent_ten, 0.5, NFL_CONFIG) > compute_wp(own_ten, 0.5, NFL_CONFIG)


def test_first_and_ten_beats_fourth_and_fifteen():
    first = _live_situation(down=1, distance=10, yardline=45)
    fourth = _live_situation(down=4, distance=15, yardline=45)
    assert compute_wp(first, 0.5, NFL_CONFIG) > compute_wp(fourth, 0.5, NFL_CONFIG)


def test_decided_game_ignores_situation():
    home_win = nfl_state(
        status="final",
        period=4,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=20,
        away_score=13,
        down=4,
        distance=15,
        yardline=10,
        possession="away",
    )
    assert compute_wp(home_win, 0.5, NFL_CONFIG) == 1.0
    home_loss = nfl_state(
        status="final",
        period=4,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=13,
        away_score=20,
        down=1,
        distance=10,
        yardline=90,
        possession="home",
    )
    assert compute_wp(home_loss, 0.5, NFL_CONFIG) == 0.0
    clock_win = nfl_state(
        status="live",
        period=4,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=21,
        away_score=20,
        down=4,
        distance=20,
        yardline=5,
        possession="away",
    )
    assert compute_wp(clock_win, 0.5, NFL_CONFIG) == 1.0


def test_situation_is_deterministic():
    state = _live_situation(yardline=72, down=3, distance=6)
    assert compute_wp(state, 0.5, NFL_CONFIG) == compute_wp(state, 0.5, NFL_CONFIG)


def test_2025_overtime_does_not_end_on_an_opening_touchdown():
    tied = nfl_state(
        status="live",
        period=4,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=20,
        away_score=20,
        prior_home=0.60,
    )
    # Tied at 0:00 of regulation. The first team has not possessed.
    assert tied.possession is None
    start = compute_wp(tied, 0.60, NFL_CONFIG)
    assert 0.5 < start < 0.75

    # First possession scored a touchdown. The other team has not possessed.
    opened = nfl_state(
        status="live",
        period=5,
        seconds_remaining_period=8 * 60,
        seconds_remaining_total=8 * 60,
        home_score=27,
        away_score=20,
        possession=None,
        prior_home=0.60,
    )
    opened_wp = compute_wp(opened, 0.60, NFL_CONFIG)
    assert opened_wp != 1.0
    assert opened_wp < 0.9999
    assert football_win_probability(opened, 0.60, NFL_CONFIG) != 1.0

    safety = nfl_state(
        status="live",
        period=5,
        seconds_remaining_period=8 * 60,
        seconds_remaining_total=8 * 60,
        home_score=22,
        away_score=20,
        possession=None,
        prior_home=0.60,
    )
    assert compute_wp(safety, 0.60, NFL_CONFIG) == 1.0
    assert compute_wp(opened, 0.60, NFL_PLAYOFF_CONFIG) != 1.0


def test_regular_season_ot_clock_can_expire_tied():
    expired = nfl_state(
        status="live",
        period=5,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=23,
        away_score=23,
        prior_home=0.60,
    )
    assert compute_wp(expired, 0.60, NFL_CONFIG) == 0.5

    playoff = compute_wp(expired, 0.60, NFL_PLAYOFF_CONFIG)
    assert playoff != 0.5
    assert 0.5 < playoff < 0.75
    assert NFL_PLAYOFF_CONFIG.ot_period_seconds == 15 * 60
    assert NFL_PLAYOFF_CONFIG.tie_after_ot is False
    assert NFL_CONFIG.ot_period_seconds == 10 * 60
    assert NFL_CONFIG.tie_after_ot is True


def test_tied_overtime_is_not_more_regulation_scoring():
    tied = nfl_state(
        status="live",
        period=4,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=20,
        away_score=20,
        prior_home=0.60,
    )
    rate_home, rate_away = team_points_per_second(0.60, NFL_CONFIG)
    mean = (rate_home - rate_away) * NFL_CONFIG.ot_period_seconds
    scale = NFL_CONFIG.ot_period_seconds / NFL_CONFIG.regulation_seconds
    legacy = NormalDist().cdf(mean / (NFL_CONFIG.margin_sd * scale**0.5))
    assert compute_wp(tied, 0.60, NFL_CONFIG) != pytest.approx(legacy, abs=1e-4)


def test_demo_replays_stay_on_regular_season_overtime():
    root = Path(__file__).resolve().parents[1]
    for name in ("nfl_jax_den.json", "nfl_nyg_den.json"):
        state = load_replay(root / "examples" / name)[0]
        config = config_for_state(state)
        assert config is NFL_CONFIG
        assert config.ot_period_seconds == 10 * 60
        assert config.tie_after_ot is True


def test_nfl_overtime_still_uses_the_timed_clock():
    early = nfl_state(
        status="live",
        period=5,
        seconds_remaining_period=9 * 60,
        seconds_remaining_total=9 * 60,
        prior_home=0.60,
    )
    late = nfl_state(
        status="live",
        period=5,
        seconds_remaining_period=30,
        seconds_remaining_total=30,
        prior_home=0.60,
    )
    early_wp = compute_wp(early, 0.60, NFL_CONFIG)
    late_wp = compute_wp(late, 0.60, NFL_CONFIG)
    assert 0.5 < late_wp < early_wp < 0.75


def test_nfl_model_follows_the_sport_protocol():
    model = NFLModel()
    assert isinstance(model, SportModel)
    state = nfl_state(prior_home=0.60)
    assert model.sport_config() is NFL_CONFIG
    assert model.win_probability(state, 0.60) == compute_wp(state, 0.60, NFL_CONFIG)
