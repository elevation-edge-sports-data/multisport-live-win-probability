"""College football is a second football config, not a second model copy."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from mswp import NCAAF_CONFIG, NcaafModel, GameState, NFL_CONFIG, SportModel, compute_wp

AS_OF = datetime(2026, 10, 11, 19, 0, tzinfo=timezone.utc)


def ncaaf_state(**overrides) -> GameState:
    fields = dict(
        sport="ncaaf",
        game_id="ncaaf-test",
        home="TEX",
        away="OU",
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


def test_ncaaf_config_margin_is_sixteen_points():
    assert NCAAF_CONFIG.sport == "ncaaf"
    assert NCAAF_CONFIG.family == "football"
    assert NCAAF_CONFIG.regulation_periods == 4
    assert NCAAF_CONFIG.period_seconds == 15 * 60
    assert NCAAF_CONFIG.mean_score_per_team == 27.0
    assert NCAAF_CONFIG.margin_sd == pytest.approx(16.0)
    assert NCAAF_CONFIG.tie_after_ot is False


def test_tipoff_with_prior_0_60_stays_about_0_60():
    state = ncaaf_state(prior_home=0.60, status="pre")
    assert compute_wp(state, 0.60, NCAAF_CONFIG) == pytest.approx(0.60, abs=1e-9)


def test_tied_end_of_regulation_starts_overtime_and_stays_a_small_favorite():
    tied = ncaaf_state(
        status="live",
        period=4,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=24,
        away_score=24,
        prior_home=0.60,
    )
    wp = compute_wp(tied, 0.60, NCAAF_CONFIG)
    assert wp not in (0.0, 1.0)
    assert 0.5 < wp < 0.75

    # The possession stub does not read the unused overtime clock.
    shorter = replace(NCAAF_CONFIG, ot_period_seconds=45)
    assert compute_wp(tied, 0.60, shorter) == wp

    decided = ncaaf_state(
        status="live",
        period=4,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=31,
        away_score=24,
        prior_home=0.60,
    )
    assert compute_wp(decided, 0.60, NCAAF_CONFIG) == 1.0


def test_extra_period_clock_is_not_the_process():
    early = ncaaf_state(
        status="live",
        period=5,
        seconds_remaining_period=12 * 60,
        seconds_remaining_total=12 * 60,
        prior_home=0.60,
    )
    late = ncaaf_state(
        status="live",
        period=5,
        seconds_remaining_period=30,
        seconds_remaining_total=30,
        prior_home=0.60,
    )
    assert compute_wp(early, 0.60, NCAAF_CONFIG) == compute_wp(late, 0.60, NCAAF_CONFIG)
    assert 0.5 < compute_wp(early, 0.60, NCAAF_CONFIG) < 0.75


def test_one_team_already_scored_uses_the_current_score():
    trailing_on_offense = ncaaf_state(
        status="live",
        period=5,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=24,
        away_score=31,
        possession="home",
        down=1,
        distance=10,
        yardline=75,
        prior_home=0.60,
    )
    wp = compute_wp(trailing_on_offense, 0.60, NCAAF_CONFIG)
    assert 0.0001 <= wp <= 0.9999
    assert wp != 0.0 and wp != 1.0

    impossible = ncaaf_state(
        status="live",
        period=5,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=38,
        away_score=24,
        possession="away",
        prior_home=0.50,
    )
    assert compute_wp(impossible, 0.50, NCAAF_CONFIG) == 1.0


def test_third_extra_period_is_a_two_point_try():
    drive = ncaaf_state(
        status="live",
        period=6,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        prior_home=0.60,
    )
    tries = ncaaf_state(
        status="live",
        period=7,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        prior_home=0.60,
    )
    drive_wp = compute_wp(drive, 0.60, NCAAF_CONFIG)
    try_wp = compute_wp(tries, 0.60, NCAAF_CONFIG)
    assert 0.5 < drive_wp < 0.75
    assert 0.5 < try_wp < 0.75
    assert drive_wp != try_wp


def test_regulation_ignores_a_partial_situation():
    full = ncaaf_state(
        status="live",
        period=2,
        seconds_remaining_period=400,
        seconds_remaining_total=400 + 2 * 900,
        home_score=14,
        away_score=10,
        prior_home=0.55,
        down=1,
        distance=10,
        yardline=75,
        possession="home",
    )
    bare = ncaaf_state(
        status="live",
        period=2,
        seconds_remaining_period=400,
        seconds_remaining_total=400 + 2 * 900,
        home_score=14,
        away_score=10,
        prior_home=0.55,
    )
    bare_wp = compute_wp(bare, 0.55, NCAAF_CONFIG)
    for name in ("down", "distance", "yardline", "possession"):
        partial = replace(full, **{name: None})
        assert compute_wp(partial, 0.55, NCAAF_CONFIG) == bare_wp
    assert compute_wp(full, 0.55, NCAAF_CONFIG) != bare_wp


def test_ncaaf_model_delegates_to_compute_wp():
    model = NcaafModel()
    assert isinstance(model, SportModel)
    state = ncaaf_state(prior_home=0.60)
    assert model.sport_config() is NCAAF_CONFIG
    assert model.win_probability(state, 0.60) == compute_wp(state, 0.60, NCAAF_CONFIG)
    assert model.sport_config() is not NFL_CONFIG


def test_final_home_win_is_one_from_the_score():
    final = ncaaf_state(
        status="final",
        period=6,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=38,
        away_score=31,
        possession="away",
        down=4,
        distance=12,
        yardline=40,
    )
    assert compute_wp(final, 0.57, NCAAF_CONFIG) == 1.0
