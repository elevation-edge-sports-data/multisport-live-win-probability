"""Dispersion, possession, and strength searches. Production values stay unchanged."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import ms_win_prob.basketball.config as basketball_config
import ms_win_prob.basketball.model as basketball_model
from ms_win_prob.football.config import NFL_CONFIG

import ms_win_prob.hockey.model as hockey_model
import ms_win_prob.hockey.strength as strength_module
import live_win_prob.tune as tune
from live_win_prob.__main__ import main
from live_win_prob.tune import (
    nfl_config_for,
    search_nba_possession,
    search_nfl_dispersion,
    search_nhl_strength,
    split_historical_files,
    strength_rate_multipliers,
    temporary_hockey_strength,
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
    assert basketball_config.NBA_POSSESSION_POINTS == before_config == 1.30
    assert basketball_model.NBA_POSSESSION_POINTS == before_model == 1.30
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


def test_default_split_is_three_way_and_rejects_two_way(tmp_path: Path):
    paths = []
    for game_id in ("10", "06", "01", "03", "08", "02", "09", "04", "07", "05"):
        path = tmp_path / f"{game_id}_A_at_B.json"
        path.write_text(
            json.dumps([{"game_id": game_id, "extra": "same-file"}]),
            encoding="utf-8",
        )
        paths.append(path)
    default = split_historical_files(list(reversed(paths)))
    explicit = split_historical_files(paths, three_way=True)
    assert default["train_game_ids"] == explicit["train_game_ids"] == [
        "01",
        "02",
        "03",
        "06",
        "07",
        "08",
    ]
    assert default["validation_game_ids"] == explicit["validation_game_ids"] == ["04", "09"]
    assert default["holdout_game_ids"] == explicit["holdout_game_ids"] == ["05", "10"]
    with pytest.raises(ValueError, match="only the three-way split is supported"):
        split_historical_files(paths, three_way=False)


def test_search_signatures_accept_three_way_and_reject_split():
    for fn in (search_nfl_dispersion, search_nba_possession, search_nhl_strength):
        params = inspect.signature(fn).parameters
        assert "three_way" in params
        assert params["three_way"].default is False
        assert "split" not in params
    with pytest.raises(TypeError):
        search_nfl_dispersion(split=True)
    with pytest.raises(TypeError):
        search_nba_possession(split=True)
    with pytest.raises(TypeError):
        search_nhl_strength(split=True)


def test_nfl_three_way_search_scores_train_validation_and_holdout():
    before = NFL_CONFIG.score_dispersion
    report = search_nfl_dispersion(
        (4.05,),
        historical=[NFL_SAMPLE],
        full=[NFL_SAMPLE],
        root=ROOT,
        three_way=True,
    )
    assert NFL_CONFIG.score_dispersion == before == 4.05
    assert report["ranked_by"] == "train overall brier"
    split = report["split"]
    assert split["train_game_ids"] == ["nfl-sample-001"]
    assert split["validation_game_ids"] == []
    assert split["holdout_game_ids"] == []
    row = report["candidates"][0]
    assert "historical" not in row
    assert row["train"]["overall"]["n"] == row["full_set"]["overall"]["n"]
    assert row["train"]["overall"]["n"] > 0
    assert row["validation"]["overall"]["n"] == 0
    assert row["holdout"]["overall"]["n"] == 0


def test_tune_cli_passes_three_way_and_rejects_split(monkeypatch, capsys):
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_nfl(**kwargs):
        calls.append(("nfl", kwargs))
        return {"candidates": [{"train": {"overall": {"n": 1}}}]}

    def fake_nba(**kwargs):
        calls.append(("nba", kwargs))
        return {"candidates": [{"train": {"overall": {"n": 1}}}]}

    def fake_nhl(**kwargs):
        calls.append(("nhl", kwargs))
        return {"grids": [{"candidates": [{"train": {"overall": {"n": 1}}}]}]}

    monkeypatch.setattr(tune, "search_nfl_dispersion", fake_nfl)
    monkeypatch.setattr(tune, "search_nba_possession", fake_nba)
    monkeypatch.setattr(tune, "search_nhl_strength", fake_nhl)
    monkeypatch.setattr(tune, "write_report", lambda report, path: None)
    monkeypatch.setattr(tune, "format_tuning_report", lambda report: "")
    monkeypatch.setattr(tune, "format_nba_possession_report", lambda report: "")
    monkeypatch.setattr(tune, "format_nhl_strength_report", lambda report: "")
    monkeypatch.setattr(tune, "historical_nfl_paths", lambda root=None: [Path("nfl.json")])
    monkeypatch.setattr(tune, "historical_nba_paths", lambda root=None: [Path("nba.json")])
    monkeypatch.setattr(tune, "historical_nhl_paths", lambda root=None: [Path("nhl.json")])

    assert main(["tune-nfl"]) == 0
    assert main(["tune-nfl", "--three-way", "--mean", "21"]) == 0
    assert main(["tune-nba", "--three-way"]) == 0
    assert main(["tune-nhl", "--three-way"]) == 0
    assert [name for name, _kwargs in calls] == ["nfl", "nfl", "nba", "nhl"]
    assert calls[0][1]["three_way"] is False
    assert calls[0][1]["mean_score_per_team"] is None
    assert calls[1][1]["three_way"] is True
    assert calls[1][1]["mean_score_per_team"] == 21.0
    assert calls[2][1]["three_way"] is True
    assert calls[3][1]["three_way"] is True
    assert all("split" not in kwargs for _name, kwargs in calls)

    assert main(["tune-nfl", "--split"]) == 2
    assert main(["tune-nba", "--split"]) == 2
    assert main(["tune-nhl", "--split"]) == 2
    assert main(["tune-nba", "--three-way", "--split"]) == 2
    err = capsys.readouterr().err
    assert "--three-way" in err
    assert "--split" not in err
    assert len(calls) == 4


def test_strength_override_matches_production_and_restores():
    from dataclasses import replace
    from datetime import datetime, timezone

    from ms_win_prob.state import GameState

    source = Path(strength_module.__file__).read_bytes()
    production = hockey_model.rate_multipliers
    assert production is strength_module.rate_multipliers
    base = GameState(
        sport="nhl",
        game_id="probe",
        home="H",
        away="A",
        home_score=1,
        away_score=1,
        period=3,
        seconds_remaining_period=600,
        seconds_remaining_total=600,
        status="live",
        source="test",
        as_of=datetime(2026, 10, 17, tzinfo=timezone.utc),
        prior_home=0.5,
    )
    probes = [
        base,
        replace(base, strength="5v5", extra_attacker=False),
        replace(base, strength="5v4"),
        replace(base, strength="5v3"),
        replace(base, strength="4v5"),
        replace(base, strength="3v3"),
        replace(base, strength="6v5", extra_attacker=False),
        replace(base, strength="6v5", extra_attacker=True),
        replace(base, strength="5v6", extra_attacker=True),
        replace(base, strength="6v6", extra_attacker=True),
    ]
    for state in probes:
        assert strength_rate_multipliers(state) == strength_module.rate_multipliers(state)
    power_play = replace(base, strength="5v4")
    empty_net = replace(base, strength="6v5", extra_attacker=True)
    both_three = replace(base, strength="3v3")
    with temporary_hockey_strength(per_skater=1.1):
        assert hockey_model.rate_multipliers(power_play) == (2.1, 0.7)
        assert strength_module.rate_multipliers(power_play) == (1.75, 0.7)
    with temporary_hockey_strength(shorthanded_reduction=0.15):
        assert hockey_model.rate_multipliers(replace(base, strength="5v3")) == (2.5, 0.7)
    with temporary_hockey_strength(shorthanded_floor=0.5):
        assert hockey_model.rate_multipliers(replace(base, strength="5v3"))[1] == 0.5
    with temporary_hockey_strength(both_3s=1.6):
        assert hockey_model.rate_multipliers(both_three) == (1.6, 1.6)
        assert hockey_model.rate_multipliers(power_play) == (1.75, 0.7)
    with temporary_hockey_strength(empty_net_factor=3.0):
        home_mult, away_mult = hockey_model.rate_multipliers(empty_net)
        assert home_mult == 1.75 * 1.10
        assert away_mult == 0.7 * 3.0
    with temporary_hockey_strength(empty_net_own=2.0):
        assert hockey_model.rate_multipliers(empty_net)[0] == 1.75 * 2.0
    assert hockey_model.rate_multipliers is production
    assert strength_module.rate_multipliers is production
    assert Path(strength_module.__file__).read_bytes() == source


def test_nhl_strength_search_ranks_train_brier_and_restores_the_binding():
    source = Path(strength_module.__file__).read_bytes()
    production = strength_module.rate_multipliers
    sample = ROOT / "examples" / "nhl_edm_col.json"
    report = search_nhl_strength(
        (("per_skater", (0.4, 1.1)),),
        historical=[sample],
        root=ROOT,
        three_way=True,
    )
    assert strength_module.rate_multipliers is production
    assert hockey_model.rate_multipliers is production
    assert Path(strength_module.__file__).read_bytes() == source
    grid = report["grids"][0]
    assert grid["coefficient"] == "per_skater"
    assert grid["shape"] == "edge"
    candidates = grid["candidates"]
    briers = [row["train"]["overall"]["brier"] for row in candidates]
    assert briers == sorted(briers)
    assert briers[0] < briers[1]
    assert candidates[0]["rank"] == 1
    assert candidates[0]["value"] in (0.4, 1.1)
    assert "validation" in candidates[0]
    assert "holdout" in candidates[0]
    assert set(candidates[0]["train"]["<5 min"]) == {
        "n",
        "mean_win_prob",
        "home_win_rate",
        "brier",
        "log_loss",
    }
    assert grid["best_train_brier"]["value"] == candidates[0]["value"]
    assert grid["best_train_brier"]["train"]["n"] == candidates[0]["train"]["overall"]["n"]


def test_nhl_strength_search_is_flat_without_strength(tmp_path: Path):
    bare = {
        "sport": "nhl",
        "game_id": "01",
        "home": "H",
        "away": "A",
        "home_score": 0,
        "away_score": 0,
        "period": 1,
        "seconds_remaining_period": 1200,
        "seconds_remaining_total": 3600,
        "status": "live",
        "source": "test",
        "as_of": "2026-10-17T00:00:00Z",
        "prior_home": 0.5,
    }
    final = dict(bare, home_score=2, away_score=1, status="final", seconds_remaining_total=0)
    path = tmp_path / "01_A_at_H.json"
    path.write_text(json.dumps([bare, final]), encoding="utf-8")
    report = search_nhl_strength(
        (("per_skater", (0.4, 0.75, 1.1)), ("both_3s", (1.1, 1.6))),
        historical=[path],
        root=ROOT,
        three_way=True,
    )
    for grid in report["grids"]:
        assert grid["shape"] == "flat"
        assert grid["tied_for_best"] == len(grid["grid"])
        assert grid["train_brier_spread"] == 0
        closest = min(
            grid["grid"],
            key=lambda value: (abs(value - grid["production"]), value),
        )
        assert grid["candidates"][0]["value"] == closest


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
