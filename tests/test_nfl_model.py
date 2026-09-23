"""NFL remaining-score model. No down, distance, or rating update required."""

from datetime import datetime, timezone

import pytest

from mswp import GameState, NFLModel, NFL_CONFIG, SportModel, compute_wp

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

    with_football_details = nfl_state(
        status="live",
        period=2,
        seconds_remaining_period=500,
        seconds_remaining_total=2 * 15 * 60 + 500,
        home_score=7,
        away_score=3,
        prior_home=0.55,
        down=3,
        distance=7,
        yardline=42,
        possession="home",
        timeouts={"home": 3, "away": 2},
    )
    assert compute_wp(with_football_details, 0.55, NFL_CONFIG) == wp


def test_nfl_model_follows_the_sport_protocol():
    model = NFLModel()
    assert isinstance(model, SportModel)
    state = nfl_state(prior_home=0.60)
    assert model.sport_config() is NFL_CONFIG
    assert model.win_probability(state, 0.60) == compute_wp(state, 0.60, NFL_CONFIG)
