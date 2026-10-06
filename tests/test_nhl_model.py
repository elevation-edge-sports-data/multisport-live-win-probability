"""NHL remaining-goals model. Strength is optional and is not read."""

import math
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from mswp import (
    GameState,
    NHL_CONFIG,
    NHL_REGULAR_CONFIG,
    NhlModel,
    SportModel,
    compute_wp,
)
from mswp.hockey.model import (
    hockey_standings_tie_probability,
    hockey_win_probability,
    team_goals_per_second,
)

AS_OF = datetime(2026, 5, 14, 0, 0, tzinfo=timezone.utc)


def nhl_state(**overrides) -> GameState:
    fields = dict(
        sport="nhl",
        game_id="nhl-test",
        home="COL",
        away="MIN",
        home_score=0,
        away_score=0,
        period=1,
        seconds_remaining_period=20 * 60,
        seconds_remaining_total=3 * 20 * 60,
        status="pre",
        source="test",
        as_of=AS_OF,
        prior_home=0.5,
    )
    fields.update(overrides)
    return GameState(**fields)


def test_nhl_config_is_playoff_sudden_death():
    assert NHL_CONFIG.sport == "nhl"
    assert NHL_CONFIG.family == "hockey"
    assert NHL_CONFIG.regulation_periods == 3
    assert NHL_CONFIG.period_seconds == 20 * 60
    assert NHL_CONFIG.mean_score_per_team == pytest.approx(3.05)
    assert NHL_CONFIG.margin_sd == pytest.approx(math.sqrt(6.1))
    assert NHL_CONFIG.ot_period_seconds == 20 * 60
    assert NHL_CONFIG.tie_after_ot is False


def test_puck_drop_prior_0_60_stays_about_0_60():
    state = nhl_state(prior_home=0.60, status="pre")
    wp = compute_wp(state, 0.60, NHL_CONFIG)
    assert wp == pytest.approx(0.60, abs=0.02)
    assert wp > 0.5

    even = nhl_state(prior_home=0.50, status="pre")
    assert compute_wp(even, 0.50, NHL_CONFIG) == pytest.approx(0.5, abs=1e-9)


def test_tied_end_of_p3_is_overtime_not_decided():
    tied = nhl_state(
        status="live",
        period=3,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=3,
        away_score=3,
        prior_home=0.60,
    )
    wp = compute_wp(tied, 0.60, NHL_CONFIG)
    assert wp not in (0.0, 1.0)
    assert 0.5 < wp < 0.75

    # Playoff overtime repeats until a goal, so the stored length cancels.
    shorter = replace(NHL_CONFIG, ot_period_seconds=5 * 60)
    assert compute_wp(tied, 0.60, shorter) == pytest.approx(wp, abs=1e-9)

    # Game win uses the shootout share, so the window length cancels.
    # The standings tie still feels the length.
    series = replace(NHL_CONFIG, tie_after_ot=True, ot_period_seconds=5 * 60)
    full = replace(NHL_CONFIG, tie_after_ot=True, ot_period_seconds=20 * 60)
    assert compute_wp(tied, 0.60, series) == pytest.approx(
        compute_wp(tied, 0.60, full), abs=1e-9
    )
    assert hockey_standings_tie_probability(tied, 0.60, series) != pytest.approx(
        hockey_standings_tie_probability(tied, 0.60, full), abs=1e-4
    )

    decided = nhl_state(
        status="live",
        period=3,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=4,
        away_score=3,
        prior_home=0.60,
    )
    assert compute_wp(decided, 0.60, NHL_CONFIG) == 1.0
    decided_loss = nhl_state(
        status="live",
        period=4,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=3,
        away_score=4,
        prior_home=0.60,
    )
    assert compute_wp(decided_loss, 0.60, NHL_CONFIG) == 0.0


def test_late_multi_goal_lead_clips_while_live():
    leading = nhl_state(
        status="live",
        period=3,
        seconds_remaining_period=2 * 60,
        seconds_remaining_total=2 * 60,
        home_score=4,
        away_score=1,
        prior_home=0.50,
    )
    assert compute_wp(leading, 0.50, NHL_CONFIG) == 0.9999
    trailing = nhl_state(
        status="live",
        period=3,
        seconds_remaining_period=2 * 60,
        seconds_remaining_total=2 * 60,
        home_score=1,
        away_score=4,
        prior_home=0.50,
    )
    assert compute_wp(trailing, 0.50, NHL_CONFIG) == 0.0001

    early = nhl_state(
        status="live",
        period=2,
        seconds_remaining_period=10 * 60,
        seconds_remaining_total=10 * 60 + 20 * 60,
        home_score=2,
        away_score=1,
        prior_home=0.50,
    )
    early_wp = compute_wp(early, 0.50, NHL_CONFIG)
    assert 0.0001 < early_wp < 0.9999


def test_optional_hockey_fields_do_not_change_the_number():
    bare = nhl_state(
        status="live",
        period=2,
        seconds_remaining_period=8 * 60,
        seconds_remaining_total=8 * 60 + 20 * 60,
        home_score=2,
        away_score=1,
        prior_home=0.55,
    )
    bare_wp = compute_wp(bare, 0.55, NHL_CONFIG)
    assert isinstance(bare_wp, float)
    for strength, extra in (
        ("Even Strength", False),
        ("Power Play", True),
        ("Shorthanded", None),
    ):
        marked = replace(bare, strength=strength, extra_attacker=extra)
        assert compute_wp(marked, 0.55, NHL_CONFIG) == bare_wp
    footballish = replace(
        bare,
        possession="home",
        down=1,
        distance=10,
        yardline=40,
        timeouts={"home": 1, "away": 1},
    )
    assert compute_wp(footballish, 0.55, NHL_CONFIG) == bare_wp


def test_same_state_twice_is_deterministic():
    state = nhl_state(
        status="live",
        period=3,
        seconds_remaining_period=412,
        seconds_remaining_total=412,
        home_score=2,
        away_score=2,
        prior_home=0.47,
    )
    assert compute_wp(state, 0.47, NHL_CONFIG) == compute_wp(state, 0.47, NHL_CONFIG)


def test_nhl_model_satisfies_sport_model():
    model = NhlModel()
    assert isinstance(model, SportModel)
    state = nhl_state(prior_home=0.60)
    assert model.sport == "nhl"
    assert model.sport_config() is NHL_CONFIG
    assert model.win_probability(state, 0.60) == compute_wp(state, 0.60, NHL_CONFIG)


def test_scoreless_regular_season_ot_is_a_shootout_for_game_win():
    assert NHL_REGULAR_CONFIG.ot_period_seconds == 5 * 60
    assert NHL_REGULAR_CONFIG.tie_after_ot is True
    assert NHL_REGULAR_CONFIG.mean_score_per_team == NHL_CONFIG.mean_score_per_team
    end = nhl_state(
        status="live",
        period=4,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=2,
        away_score=2,
        prior_home=0.60,
    )
    game = compute_wp(end, 0.60, NHL_REGULAR_CONFIG)
    standings = hockey_standings_tie_probability(end, 0.60, NHL_REGULAR_CONFIG)
    rate_home, rate_away = team_goals_per_second(0.60, NHL_REGULAR_CONFIG)
    assert game != pytest.approx(0.5)
    assert game == pytest.approx(rate_home / (rate_home + rate_away))
    assert standings == 0.5
    assert hockey_win_probability(end, 0.60, NHL_REGULAR_CONFIG) == pytest.approx(game)


def test_scoreless_playoff_ot_is_not_a_shootout():
    end = nhl_state(
        status="live",
        period=4,
        seconds_remaining_period=0,
        seconds_remaining_total=0,
        home_score=2,
        away_score=2,
        prior_home=0.60,
    )
    live = nhl_state(
        status="live",
        period=4,
        seconds_remaining_period=20 * 60,
        seconds_remaining_total=20 * 60,
        home_score=2,
        away_score=2,
        prior_home=0.60,
    )
    game = compute_wp(end, 0.60, NHL_CONFIG)
    assert game != pytest.approx(0.5)
    assert game == pytest.approx(compute_wp(live, 0.60, NHL_CONFIG))
    assert hockey_standings_tie_probability(end, 0.60, NHL_CONFIG) == pytest.approx(game)
    assert hockey_standings_tie_probability(end, 0.60, NHL_REGULAR_CONFIG) == 0.5


def test_colorado_minnesota_stays_on_playoff_overtime():
    from pathlib import Path

    from live_wp.replay import config_for_state, load_replay

    root = Path(__file__).resolve().parents[1]
    states = load_replay(root / "examples" / "nhl_col_min_g5.json")
    config = config_for_state(states[0])
    assert config is NHL_CONFIG
    assert config.ot_period_seconds == 20 * 60
    assert config.tie_after_ot is False
    assert any(state.period > 3 for state in states)


def test_final_home_win_is_one_from_the_score():
    final = nhl_state(
        status="final",
        period=4,
        seconds_remaining_period=16 * 60 + 8,
        seconds_remaining_total=16 * 60 + 8,
        home_score=4,
        away_score=3,
        strength="Even Strength",
        extra_attacker=False,
    )
    assert compute_wp(final, 0.42, NHL_CONFIG) == 1.0
