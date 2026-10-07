"""Smoke calibration. Scores compute_wp on saved fixtures and does not retune."""

from __future__ import annotations

import json
import math
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mswp import GameState, NFL_CONFIG, NHL_CONFIG
from mswp.compute import LIVE_WP_CEIL, LIVE_WP_FLOOR, compute_wp

from live_wp.calibrate import (
    BUCKETS,
    build_report,
    default_paths,
    format_report,
    summarize,
    time_bucket,
)
from live_wp.feeds.espn_basketball import events_from_espn_basketball
from live_wp.__main__ import main
from live_wp.replay import config_for_state, load_replay

ROOT = Path(__file__).resolve().parents[1]
NFL_SAMPLE = ROOT / "examples" / "nfl_sample.json"
NHL_SAMPLE = ROOT / "examples" / "nhl_col_min_g5.json"
AS_OF = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)


def _nfl(**overrides) -> GameState:
    fields = dict(
        sport="nfl",
        game_id="bucket",
        home="Home",
        away="Away",
        home_score=0,
        away_score=0,
        period=1,
        seconds_remaining_period=15 * 60,
        seconds_remaining_total=60 * 60,
        status="live",
        source="test",
        as_of=AS_OF,
        prior_home=0.5,
    )
    fields.update(overrides)
    return GameState(**fields)


def test_decided_final_with_a_leader_is_zero_or_one():
    wins = load_replay(NFL_SAMPLE)
    win = wins[-1]
    assert win.status == "final"
    assert win.home_score > win.away_score
    assert compute_wp(win, win.prior_home, config_for_state(win)) == 1.0

    losses = load_replay(ROOT / "examples" / "ncaaf_cu_gt.json")
    loss = losses[-1]
    assert loss.status == "final"
    assert loss.home_score < loss.away_score
    assert compute_wp(loss, loss.prior_home, config_for_state(loss)) == 0.0


def test_live_snapshot_stays_inside_the_open_unit_interval():
    states = load_replay(NFL_SAMPLE)
    live = next(state for state in states if state.status == "live")
    wp = compute_wp(live, live.prior_home, config_for_state(live))
    assert 0.0 < LIVE_WP_FLOOR < LIVE_WP_CEIL < 1.0
    assert LIVE_WP_FLOOR <= wp <= LIVE_WP_CEIL
    assert 0.0 < wp < 1.0


def test_outcome_is_the_final_snapshot_score():
    states = load_replay(NFL_SAMPLE)
    assert any(state.away_score > state.home_score for state in states)
    report = build_report([NFL_SAMPLE])
    config = config_for_state(states[0])
    predicted = [compute_wp(state, state.prior_home, config) for state in states]
    sport = report["by_sport"][0]
    assert sport["sport"] == "nfl"
    assert sport["n"] == len(states)
    assert sport["home_win_rate"] == 1.0
    assert sport["mean_predicted_home_wp"] == pytest.approx(sum(predicted) / len(predicted))

    loss = build_report([ROOT / "examples" / "ncaaf_cu_gt.json"])
    assert loss["overall"]["home_win_rate"] == 0.0
    assert loss["overall"]["n"] > 1


def test_log_loss_clips_predictions_and_brier_does_not():
    clipped = summarize([(0.0, 1.0), (1.0, 0.0)])
    assert clipped["brier"] == pytest.approx(1.0)
    assert clipped["mean_predicted_home_wp"] == pytest.approx(0.5)
    assert clipped["log_loss"] == pytest.approx(-math.log(1e-6))

    raw = summarize([(0.25, 1.0)])
    assert raw["brier"] == pytest.approx((0.25 - 1.0) ** 2)
    assert raw["log_loss"] == pytest.approx(-math.log(0.25))


def test_time_buckets_split_regulation_and_overtime():
    assert time_bucket(_nfl(status="pre"), NFL_CONFIG) == "pregame"
    assert time_bucket(_nfl(seconds_remaining_total=15 * 60 + 1), NFL_CONFIG) == ">15 min"
    assert time_bucket(
        _nfl(period=4, seconds_remaining_period=15 * 60, seconds_remaining_total=15 * 60),
        NFL_CONFIG,
    ) == "5-15 min"
    assert time_bucket(
        _nfl(period=4, seconds_remaining_period=5 * 60, seconds_remaining_total=5 * 60),
        NFL_CONFIG,
    ) == "5-15 min"
    assert time_bucket(
        _nfl(period=4, seconds_remaining_period=5 * 60 - 1, seconds_remaining_total=5 * 60 - 1),
        NFL_CONFIG,
    ) == "1-5 min"
    assert time_bucket(
        _nfl(period=4, seconds_remaining_period=60, seconds_remaining_total=60),
        NFL_CONFIG,
    ) == "1-5 min"
    assert time_bucket(
        _nfl(period=4, seconds_remaining_period=59, seconds_remaining_total=59),
        NFL_CONFIG,
    ) == "<1 min"
    assert time_bucket(
        _nfl(
            status="final",
            period=4,
            seconds_remaining_period=0,
            seconds_remaining_total=0,
            home_score=1,
        ),
        NFL_CONFIG,
    ) == "<1 min"
    overtime = _nfl(
        sport="nhl",
        period=4,
        seconds_remaining_period=20 * 60,
        seconds_remaining_total=20 * 60,
    )
    assert time_bucket(overtime, NHL_CONFIG) == "overtime"
    assert list(BUCKETS) == [
        "pregame",
        ">15 min",
        "5-15 min",
        "1-5 min",
        "<1 min",
        "overtime",
    ]


def test_refused_espn_file_is_skipped_and_recorded():
    refused = ROOT / "tests" / "fixtures" / "espn_nfl_scoreboard_snippet.json"
    report = build_report([NFL_SAMPLE, refused])
    assert [Path(item["path"]).name for item in report["skipped"]] == [
        "espn_nfl_scoreboard_snippet.json"
    ]
    assert report["skipped"][0]["reason"]
    assert [game["path"] for game in report["games"]] == ["examples/nfl_sample.json"]


def test_default_sources_score_the_listed_espn_fixtures():
    paths = default_paths()
    names = [path.name for path in paths]
    assert "nfl_sample.json" in names
    assert "nhl_col_min_g5.json" in names
    espn = {
        "espn_nfl_summary_snippet.json",
        "espn_nhl_401442762_summary.json",
        "espn_nba_401547684_summary.json",
        "espn_ncaab_401638608_summary.json",
        "espn_ncaaf_summary_snippet.json",
    }
    assert espn.issubset(names)
    report = build_report(paths)
    scored = {Path(game["path"]).name for game in report["games"]}
    skipped = {Path(item["path"]).name: item["reason"] for item in report["skipped"]}
    assert "espn_nfl_summary_snippet.json" in scored
    assert "espn_nhl_401442762_summary.json" in scored
    assert "espn_ncaaf_summary_snippet.json" in scored
    assert "espn_nba_401547684_summary.json" in scored
    assert "espn_ncaab_401638608_summary.json" in scored
    assert "espn_nba_401547684_summary.json" not in skipped
    assert "espn_ncaab_401638608_summary.json" not in skipped
    sports_by_file = {
        Path(game["path"]).name: game["sport"] for game in report["games"]
    }
    assert sports_by_file["espn_nba_401547684_summary.json"] == "nba"
    assert sports_by_file["espn_ncaab_401638608_summary.json"] == "ncaab"
    assert "nfl_sample.json" in scored
    assert "nhl_col_min_g5.json" in scored
    sports = {row["sport"] for row in report["by_sport"]}
    assert {"nfl", "nhl", "nba", "ncaaf", "ncaah", "ncaab"}.issubset(sports)
    assert [row["bucket"] for row in report["by_bucket"]] == list(BUCKETS)


def test_calibrate_does_not_skip_nba_or_ncaab_fixtures():
    nba = ROOT / "tests" / "fixtures" / "espn_nba_401547684_summary.json"
    ncaab = ROOT / "tests" / "fixtures" / "espn_ncaab_401638608_summary.json"
    report = build_report([nba, ncaab])
    skipped = [item["path"] for item in report["skipped"]]
    assert "tests/fixtures/espn_nba_401547684_summary.json" not in skipped
    assert "tests/fixtures/espn_ncaab_401638608_summary.json" not in skipped
    text = format_report(report)
    skipped_text = text.split("Skipped\n", 1)[1]
    assert "espn_nba_401547684_summary.json" not in skipped_text
    assert "espn_ncaab_401638608_summary.json" not in skipped_text
    assert "not a historical backtest" in text
    assert (
        "too small to retune margin_sd, possession points, or strength multipliers"
        in text
    )

    expected: dict[str, tuple[str, int]] = {}
    for path, sport in ((nba, "nba"), (ncaab, "ncaab")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        states = events_from_espn_basketball(payload, density="scoring")
        assert {state.sport for state in states} == {sport}
        expected[path.name] = (sport, len(states))

    games = {Path(game["path"]).name: game for game in report["games"]}
    assert set(games) == set(expected)
    for name, (sport, count) in expected.items():
        assert games[name]["sport"] == sport
        assert games[name]["n"] == count
        assert games[name]["source"] == "ingest-espn"
    counted = {row["sport"]: row["n"] for row in report["by_sport"]}
    assert counted["nba"] == expected["espn_nba_401547684_summary.json"][1]
    assert counted["ncaab"] == expected["espn_ncaab_401638608_summary.json"][1]


def test_calibrate_command_runs_on_sample_replays_without_network(monkeypatch):
    source = (ROOT / "src" / "live_wp" / "calibrate.py").read_text(encoding="utf-8")
    assert "urllib" not in source
    assert "urlopen" not in source

    def blocked(*_args, **_kwargs):
        raise AssertionError("calibration tried to use the network")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    code = main(
        [
            "calibrate",
            str(NFL_SAMPLE),
            str(NHL_SAMPLE),
        ]
    )
    assert code == 0
    monkeypatch.undo()

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "live_wp",
            "calibrate",
            "examples/nfl_sample.json",
            "examples/nhl_col_min_g5.json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "not a historical backtest" in completed.stdout
    assert "margin_sd" in completed.stdout
    report = json.loads(
        (ROOT / "artifacts" / "calibration.json").read_text(encoding="utf-8")
    )
    note = report["note"]
    assert "not a historical backtest" in note
    assert (
        "too small to retune margin_sd, possession points, or strength multipliers"
        in note
    )
    assert [Path(path).name for path in report["inputs"]] == [
        "nfl_sample.json",
        "nhl_col_min_g5.json",
    ]
    assert report["skipped"] == []
    assert {game["sport"] for game in report["games"]} == {"nfl", "nhl"}


def test_readme_documents_the_command_and_the_limit():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "python -m live_wp calibrate" in readme
    assert "not a historical backtest" in readme
    assert (
        "too small to retune margin_sd, possession points, or strength multipliers"
        in readme
    )
    assert "artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
