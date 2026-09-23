"""GameState contract: prior default and optional football fields."""

from datetime import datetime, timezone

import pytest

from mswp import DEFAULT_PRIOR_HOME, GameState

AS_OF = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)


def test_down_is_optional_and_prior_defaults_to_half():
    state = GameState(
        sport="nfl",
        game_id="g1",
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
    )
    assert state.prior_home == DEFAULT_PRIOR_HOME == 0.5
    assert state.down is None
    assert state.distance is None
    assert state.yardline is None
    assert state.possession is None
    assert state.timeouts is None
    assert state.strength is None
    assert state.extra_attacker is None


def test_optional_fields_can_be_set_without_changing_the_required_shape():
    state = GameState(
        sport="nfl",
        game_id="g1",
        home="Home",
        away="Away",
        home_score=10,
        away_score=7,
        period=2,
        seconds_remaining_period=120,
        seconds_remaining_total=15 * 60 + 120,
        status="live",
        source="test",
        as_of=AS_OF,
        prior_home=0.61,
        down=2,
        distance=5,
        yardline=38,
        possession="away",
        timeouts={"home": 3, "away": 1},
        strength=None,
        extra_attacker=None,
    )
    assert state.down == 2
    assert dict(state.timeouts) == {"home": 3, "away": 1}


def test_status_must_be_a_known_value():
    with pytest.raises(ValueError):
        GameState(
            sport="nfl",
            game_id="g1",
            home="Home",
            away="Away",
            home_score=0,
            away_score=0,
            period=1,
            seconds_remaining_period=900,
            seconds_remaining_total=3600,
            status="halftime",
            source="test",
            as_of=AS_OF,
        )
