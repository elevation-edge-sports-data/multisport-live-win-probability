"""GameState contract: prior default and optional football fields."""

from dataclasses import replace
from datetime import datetime, timezone
from statistics import NormalDist

import pytest

from ms_win_prob import (
    DEFAULT_PRIOR_HOME,
    NCAAF_CONFIG,
    NCAAH_CONFIG,
    NFL_CONFIG,
    NFL_PLAYOFF_CONFIG,
    NHL_CONFIG,
    NHL_REGULAR_CONFIG,
    GameState,
    SportConfig,
    compute_win_prob,
)
from ms_win_prob.basketball.config import NBA_CONFIG, NCAAB_CONFIG

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
    assert state.prior_source == "default"
    assert state.neutral is False
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


def test_neutral_defaults_to_false_and_rejects_a_non_bool():
    state = GameState(
        sport="nfl",
        game_id="g1",
        home="Home",
        away="Away",
        home_score=0,
        away_score=0,
        period=1,
        seconds_remaining_period=900,
        seconds_remaining_total=3600,
        status="pre",
        source="test",
        as_of=AS_OF,
    )
    assert state.neutral is False
    assert replace(state, neutral=True).neutral is True
    with pytest.raises(TypeError):
        replace(state, neutral=1)


def test_home_advantage_placeholders():
    bare = SportConfig(
        sport="nba",
        family="basketball",
        regulation_periods=4,
        period_seconds=12 * 60,
        mean_score_per_team=114.0,
        score_dispersion=1.05,
        ot_period_seconds=5 * 60,
        tie_after_ot=False,
    )
    assert bare.home_advantage == 0.0
    assert NFL_CONFIG.home_advantage == 1.5
    assert NFL_PLAYOFF_CONFIG.home_advantage == 0.0
    assert NHL_CONFIG.home_advantage == 0.13
    assert NHL_REGULAR_CONFIG.home_advantage == 0.0
    assert NBA_CONFIG.home_advantage == 1.7
    assert NCAAF_CONFIG.home_advantage == 2.5
    assert NCAAB_CONFIG.home_advantage == 3.0
    assert NCAAH_CONFIG.home_advantage == 0.15
    with pytest.raises(TypeError):
        replace(NFL_CONFIG, home_advantage=True)
    with pytest.raises(ValueError):
        replace(NFL_CONFIG, home_advantage=float("nan"))


def _margin_prior(prior: float, config) -> float:
    """Prior after adding home_advantage in full-game margin space."""
    normal = NormalDist()
    z = normal.inv_cdf(prior) + config.home_advantage / config.margin_sd
    return normal.cdf(z)


def test_non_neutral_receives_home_advantage_and_neutral_does_not():
    for config in (NCAAF_CONFIG, NCAAH_CONFIG, NCAAB_CONFIG):
        home = GameState(
            sport=config.sport,
            game_id="site",
            home="H",
            away="A",
            home_score=10,
            away_score=7,
            period=2,
            seconds_remaining_period=config.period_seconds // 2,
            seconds_remaining_total=config.regulation_seconds // 2,
            status="live",
            source="test",
            as_of=AS_OF,
            prior_home=0.6,
        )
        neutral = replace(home, neutral=True)
        boosted = _margin_prior(0.6, config)
        home_wp = compute_win_prob(home, 0.6, config)
        neutral_wp = compute_win_prob(neutral, 0.6, config)
        assert boosted > 0.6
        assert home_wp > neutral_wp
        assert home_wp == pytest.approx(
            compute_win_prob(neutral, boosted, config), abs=1e-12
        )
        assert neutral_wp == compute_win_prob(
            home, 0.6, replace(config, home_advantage=0.0)
        )

    nfl = GameState(
        sport="nfl",
        game_id="site",
        home="H",
        away="A",
        home_score=0,
        away_score=0,
        period=1,
        seconds_remaining_period=NFL_CONFIG.period_seconds,
        seconds_remaining_total=NFL_CONFIG.regulation_seconds,
        status="live",
        source="test",
        as_of=AS_OF,
        prior_home=0.6,
    )
    assert compute_win_prob(nfl, 0.6, NFL_PLAYOFF_CONFIG) == compute_win_prob(
        replace(nfl, neutral=True), 0.6, NFL_PLAYOFF_CONFIG
    )
    decided = replace(
        nfl,
        sport="ncaaf",
        status="final",
        period=4,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=21,
        away_score=14,
    )
    assert compute_win_prob(decided, 0.6, NCAAF_CONFIG) == 1.0
    assert compute_win_prob(replace(decided, neutral=True), 0.6, NCAAF_CONFIG) == 1.0


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
