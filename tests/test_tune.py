"""NFL dispersion search. The production config stays unchanged."""

from __future__ import annotations

from pathlib import Path

from ms_win_prob.football.config import NFL_CONFIG

from live_win_prob.tune import nfl_config_for, search_nfl_dispersion

ROOT = Path(__file__).resolve().parents[1]
NFL_SAMPLE = ROOT / "examples" / "nfl_sample.json"


def test_nfl_override_copies_config_and_leaves_production_values():
    before = (
        NFL_CONFIG.score_dispersion,
        NFL_CONFIG.mean_score_per_team,
        NFL_CONFIG.margin_sd,
    )
    chooser = nfl_config_for(3.5, 21.0)
    from datetime import datetime, timezone

    from ms_win_prob.state import GameState

    state = GameState(
        sport="nfl",
        game_id="probe",
        home="H",
        away="A",
        home_score=0,
        away_score=0,
        period=1,
        seconds_remaining_period=900,
        seconds_remaining_total=3600,
        status="pre",
        source="test",
        as_of=datetime(2026, 10, 16, tzinfo=timezone.utc),
        prior_home=0.5,
    )
    copied = chooser(state)
    assert copied is not NFL_CONFIG
    assert copied.score_dispersion == 3.5
    assert copied.mean_score_per_team == 21.0
    assert (
        NFL_CONFIG.score_dispersion,
        NFL_CONFIG.mean_score_per_team,
        NFL_CONFIG.margin_sd,
    ) == before


def test_dispersion_search_ranks_historical_brier_and_keeps_production_config():
    before = NFL_CONFIG.score_dispersion
    report = search_nfl_dispersion(
        (2.5, 6.0),
        historical=[NFL_SAMPLE],
        full=[NFL_SAMPLE],
        root=ROOT,
    )
    assert NFL_CONFIG.score_dispersion == before == 4.05
    candidates = report["candidates"]
    briers = [row["historical"]["overall"]["brier"] for row in candidates]
    assert briers == sorted(briers)
    assert candidates[0]["rank"] == 1
    assert report["best_overall_brier"]["score_dispersion"] == candidates[0]["score_dispersion"]
    late = candidates[0]["historical"]["<5 min"]
    assert set(late) == {"n", "mean_win_prob", "home_win_rate", "brier", "log_loss"}
    assert "overtime" in candidates[0]["historical"]
    assert candidates[0]["full_set"]["overall"]["n"] == candidates[0]["historical"]["overall"]["n"]
