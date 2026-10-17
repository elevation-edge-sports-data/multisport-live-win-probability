"""NFL dispersion search. The production config stays unchanged."""

from __future__ import annotations

import json
from pathlib import Path

import ms_win_prob.basketball.config as basketball_config
import ms_win_prob.basketball.model as basketball_model
from ms_win_prob.football.config import NFL_CONFIG

from live_win_prob.tune import (
    nfl_config_for,
    search_nba_possession,
    search_nfl_dispersion,
    split_historical_files,
)

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


def test_nba_possession_search_restores_the_production_constant():
    before_config = basketball_config.NBA_POSSESSION_POINTS
    before_model = basketball_model.NBA_POSSESSION_POINTS
    sample = ROOT / "examples" / "nba_den_lal.json"
    report = search_nba_possession((0.6, 1.8), historical=[sample], full=[sample], root=ROOT)
    assert basketball_config.NBA_POSSESSION_POINTS == before_config == 1.12
    assert basketball_model.NBA_POSSESSION_POINTS == before_model == 1.12
    candidates = report["candidates"]
    briers = [row["historical"]["overall"]["brier"] for row in candidates]
    assert briers == sorted(briers)
    assert briers[0] != briers[1]
    assert candidates[0]["rank"] == 1
    late = candidates[0]["historical"]["<5 min"]
    assert set(late) == {"n", "mean_win_prob", "home_win_rate", "brier", "log_loss"}
    assert report["best_overall_brier"]["possession_points"] == candidates[0]["possession_points"]
    assert "split" not in report
    assert "train" not in candidates[0]


def test_split_holds_out_every_fifth_sorted_game_id(tmp_path: Path):
    paths = []
    for game_id in ("10", "06", "01", "03", "08", "02", "09", "04", "07", "05"):
        path = tmp_path / f"{game_id}_A_at_B.json"
        path.write_text(
            json.dumps([{"game_id": game_id, "extra": "same-file"}]),
            encoding="utf-8",
        )
        paths.append(path)
    split = split_historical_files(list(reversed(paths)))
    assert split["holdout_game_ids"] == ["05", "10"]
    assert split["train_game_ids"] == ["01", "02", "03", "04", "06", "07", "08", "09"]
    holdout_names = {path.name for path in split["holdout_paths"]}
    train_names = {path.name for path in split["train_paths"]}
    assert holdout_names == {"05_A_at_B.json", "10_A_at_B.json"}
    assert train_names.isdisjoint(holdout_names)
    assert len(train_names) + len(holdout_names) == 10


def test_three_way_split_repeats_train_validation_holdout(tmp_path: Path):
    paths = []
    for game_id in ("10", "06", "01", "03", "08", "02", "09", "04", "07", "05"):
        path = tmp_path / f"{game_id}_A_at_B.json"
        path.write_text(json.dumps([{"game_id": game_id}]), encoding="utf-8")
        paths.append(path)
    split = split_historical_files(paths, three_way=True)
    assert split["train_game_ids"] == ["01", "02", "03", "06", "07", "08"]
    assert split["validation_game_ids"] == ["04", "09"]
    assert split["holdout_game_ids"] == ["05", "10"]
    names = {
        role: {path.name for path in split[f"{role}_paths"]}
        for role in ("train", "validation", "holdout")
    }
    assert names["validation"] == {"04_A_at_B.json", "09_A_at_B.json"}
    assert names["holdout"] == {"05_A_at_B.json", "10_A_at_B.json"}
    assert names["train"].isdisjoint(names["validation"])
    assert names["train"].isdisjoint(names["holdout"])
    assert sum(len(group) for group in names.values()) == 10
