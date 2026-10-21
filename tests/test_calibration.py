"""Smoke calibration. Scores compute_win_prob on saved fixtures and does not retune."""

from __future__ import annotations

import json
import math
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ms_win_prob import GameState, NFL_CONFIG, NHL_CONFIG
from ms_win_prob.compute import LIVE_WIN_PROB_CEIL, LIVE_WIN_PROB_FLOOR, compute_win_prob

from live_win_prob.calibrate import (
    BUCKETS,
    ESPN_FIXTURES,
    build_report,
    default_paths,
    format_nfl_split_report,
    format_report,
    historical_paths,
    moneyline_snapshots,
    run_calibrate,
    summarize,
    time_bucket,
)
from live_win_prob.tune import (
    historical_nfl_paths,
    report_nfl_production_split,
    split_historical_files,
)
from live_win_prob.feeds.espn_basketball import events_from_espn_basketball
from live_win_prob.__main__ import main
from live_win_prob.replay import config_for_state, load_replay

ROOT = Path(__file__).resolve().parents[1]
NFL_SAMPLE = ROOT / "examples" / "nfl_sample.json"
NHL_SAMPLE = ROOT / "examples" / "nhl_edm_col.json"
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
    assert compute_win_prob(win, win.prior_home, config_for_state(win)) == 1.0

    losses = load_replay(ROOT / "examples" / "ncaaf_cu_gt.json")
    loss = losses[-1]
    assert loss.status == "final"
    assert loss.home_score < loss.away_score
    assert compute_win_prob(loss, loss.prior_home, config_for_state(loss)) == 0.0


def test_live_snapshot_stays_inside_the_open_unit_interval():
    states = load_replay(NFL_SAMPLE)
    live = next(state for state in states if state.status == "live")
    win_prob = compute_win_prob(live, live.prior_home, config_for_state(live))
    assert 0.0 < LIVE_WIN_PROB_FLOOR < LIVE_WIN_PROB_CEIL < 1.0
    assert LIVE_WIN_PROB_FLOOR <= win_prob <= LIVE_WIN_PROB_CEIL
    assert 0.0 < win_prob < 1.0


def test_outcome_is_the_final_snapshot_score():
    states = load_replay(NFL_SAMPLE)
    assert any(state.away_score > state.home_score for state in states)
    report = build_report([NFL_SAMPLE])
    config = config_for_state(states[0])
    predicted = [compute_win_prob(state, state.prior_home, config) for state in states]
    sport = report["by_sport"][0]
    assert sport["sport"] == "nfl"
    assert sport["n"] == len(states)
    assert sport["home_win_rate"] == 1.0
    assert sport["mean_predicted_home_win_prob"] == pytest.approx(sum(predicted) / len(predicted))

    loss = build_report([ROOT / "examples" / "ncaaf_cu_gt.json"])
    assert loss["overall"]["home_win_rate"] == 0.0
    assert loss["overall"]["n"] > 1


def test_log_loss_clips_predictions_and_brier_does_not():
    clipped = summarize([(0.0, 1.0), (1.0, 0.0)])
    assert clipped["brier"] == pytest.approx(1.0)
    assert clipped["mean_predicted_home_win_prob"] == pytest.approx(0.5)
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


def test_historical_calibration_dir_is_optional(tmp_path: Path):
    smoke = default_paths(tmp_path)
    assert smoke == [tmp_path / relative for relative in ESPN_FIXTURES]
    assert historical_paths(tmp_path) == []

    base = tmp_path / "data" / "calibration"
    base.mkdir(parents=True)
    assert historical_paths(tmp_path) == []
    assert default_paths(tmp_path) == smoke

    replay = base / "nfl" / "2024" / "sample.json"
    replay.parent.mkdir(parents=True)
    replay.write_bytes((ROOT / "examples" / "nfl_sample.json").read_bytes())
    stamped = json.loads(replay.read_text(encoding="utf-8"))
    for row in stamped:
        row["prior_source"] = "moneyline"
    replay.write_bytes(json.dumps(stamped).encode("utf-8"))
    espn = base / "ncaaf" / "snippet.json"
    espn.parent.mkdir()
    espn.write_bytes(
        (ROOT / "tests" / "fixtures" / "espn_ncaaf_summary_snippet.json").read_bytes()
    )
    refused = base / "nfl" / "board.json"
    refused.write_bytes(
        (ROOT / "tests" / "fixtures" / "espn_nfl_scoreboard_snippet.json").read_bytes()
    )
    (base / "notes.txt").write_text("not a calibration file", encoding="utf-8")

    added = historical_paths(tmp_path)
    assert added == [replay, refused, espn]
    assert default_paths(tmp_path) == [*smoke, *added]

    report = build_report(added, root=tmp_path)
    games = {Path(str(game["path"])).name: game for game in report["games"]}
    assert games["sample.json"]["source"] == "replay"
    assert games["sample.json"]["sport"] == "nfl"
    assert games["snippet.json"]["source"] == "ingest-espn"
    assert games["snippet.json"]["sport"] == "ncaaf"
    skipped = {Path(str(item["path"])).name: item["reason"] for item in report["skipped"]}
    assert "board.json" in skipped
    assert skipped["board.json"]
    assert "notes.txt" not in skipped
    assert "notes.txt" not in {Path(str(game["path"])).name for game in report["games"]}


def _prior_row(
    game_id: str,
    *,
    prior_source: str | None,
    prior_home: float = 0.62,
) -> dict[str, object]:
    row: dict[str, object] = {
        "sport": "nfl",
        "game_id": game_id,
        "home": "H",
        "away": "A",
        "home_score": 0,
        "away_score": 0,
        "period": 1,
        "seconds_remaining_period": 900,
        "seconds_remaining_total": 3600,
        "status": "pre",
        "prior_home": prior_home,
        "source": "test",
        "as_of": "2025-09-07T17:00:00Z",
    }
    if prior_source is not None:
        row["prior_source"] = prior_source
    return row


def test_moneyline_snapshots_keep_only_an_exact_moneyline_prior(tmp_path: Path):
    base = tmp_path / "data" / "calibration"
    files = {
        base / "nba" / "000_money.json": [_prior_row("nba-ml", prior_source="moneyline")],
        base / "nfl" / "aaa_elo.json": [_prior_row("nfl-elo", prior_source="elo")],
        base / "nfl" / "mid_default.json": [_prior_row("nfl-default", prior_source=None)],
        base / "nfl" / "mid_mixed.json": [
            _prior_row("nfl-mixed", prior_source="elo", prior_home=0.41),
            _prior_row("nfl-mixed", prior_source="moneyline", prior_home=0.73),
        ],
        base / "nfl" / "zzz_money.json": [
            _prior_row("nfl-ml", prior_source="moneyline", prior_home=0.81),
            _prior_row("nfl-ml", prior_source="moneyline", prior_home=0.81),
        ],
        base / "nfl" / "empty.json": [],
        base / "nhl" / "half.json": [
            _prior_row("nhl-half", prior_source="moneyline", prior_home=0.5)
        ],
        base / "ncaaf" / "case.json": [_prior_row("case", prior_source="Moneyline")],
    }
    before: dict[Path, bytes] = {}
    for path, payload in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(payload).encode("utf-8"))
        before[path] = path.read_bytes()
    (base / "nfl" / "notes.txt").write_bytes(b"leave me")

    assert moneyline_snapshots(tmp_path / "missing") == []
    loaded = moneyline_snapshots(base)
    assert [(state.game_id, state.prior_home) for state in loaded] == [
        ("nfl-mixed", 0.73),
        ("nfl-ml", 0.81),
        ("nfl-ml", 0.81),
        ("nhl-half", 0.5),
        ("nba-ml", 0.62),
    ]
    assert {state.prior_source for state in loaded} == {"moneyline"}
    nfl_only = moneyline_snapshots(base / "nfl")
    assert [state.game_id for state in nfl_only] == ["nfl-mixed", "nfl-ml", "nfl-ml"]
    for path, payload in before.items():
        assert path.read_bytes() == payload
    assert (base / "nfl" / "notes.txt").read_bytes() == b"leave me"


def test_default_sources_score_the_listed_espn_fixtures():
    paths = default_paths()
    names = [path.name for path in paths]
    assert "nfl_sample.json" in names
    assert "nhl_edm_col.json" in names
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
    assert "nhl_edm_col.json" in scored
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
    source = (ROOT / "src" / "live_win_prob" / "calibrate.py").read_text(encoding="utf-8")
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
            "live_win_prob",
            "calibrate",
            "examples/nfl_sample.json",
            "examples/nhl_edm_col.json",
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
        "nhl_edm_col.json",
    ]
    assert report["skipped"] == []
    assert {game["sport"] for game in report["games"]} == {"nfl", "nhl"}


def _mini_nfl(
    game_id: str,
    *,
    home_wins: bool,
    prior_source: str | None = "moneyline",
    sport: str = "nfl",
) -> list[dict[str, object]]:
    final_home = 7 if home_wins else 0
    final_away = 0 if home_wins else 7
    shared: dict[str, object] = {
        "sport": sport,
        "game_id": game_id,
        "home": "H",
        "away": "A",
        "source": "test",
        "as_of": "2025-09-07T17:00:00Z",
        "prior_home": 0.5,
    }
    if prior_source is not None:
        shared["prior_source"] = prior_source
    return [
        {
            **shared,
            "home_score": 0,
            "away_score": 0,
            "period": 1,
            "seconds_remaining_period": 15 * 60,
            "seconds_remaining_total": 60 * 60,
            "status": "pre",
        },
        {
            **shared,
            "home_score": final_home,
            "away_score": final_away,
            "period": 4,
            "seconds_remaining_period": 0,
            "seconds_remaining_total": 0,
            "status": "final",
        },
    ]


def test_nfl_production_split_matches_tune_and_keeps_config(tmp_path: Path):
    directory = tmp_path / "data" / "calibration" / "nfl"
    directory.mkdir(parents=True)
    for game_id, home_wins in (
        ("05", False),
        ("01", True),
        ("04", True),
        ("02", False),
        ("03", True),
    ):
        path = directory / f"{game_id}_A_at_H.json"
        payload = _mini_nfl(game_id, home_wins=home_wins)
        if game_id == "01":
            payload.append(
                {
                    **payload[0],
                    "prior_source": "elo",
                    "prior_home": 0.2,
                    "status": "live",
                    "seconds_remaining_total": 1000,
                }
            )
        path.write_bytes(json.dumps(payload).encode("utf-8"))
    elo_only = directory / "00_elo.json"
    elo_only.write_bytes(
        json.dumps(_mini_nfl("00", home_wins=True, prior_source="elo")).encode("utf-8")
    )
    unlabeled = directory / "99_plain.json"
    unlabeled.write_bytes(
        json.dumps(_mini_nfl("99", home_wins=True, prior_source=None)).encode("utf-8")
    )
    college = tmp_path / "data" / "calibration" / "ncaaf" / "college.json"
    college.parent.mkdir(parents=True)
    college.write_bytes(
        json.dumps(
            _mini_nfl("college", home_wins=True, prior_source=None, sport="ncaaf")
        ).encode("utf-8")
    )
    saved = {path: path.read_bytes() for path in directory.glob("*.json")}
    saved[college] = college.read_bytes()
    before = (
        NFL_CONFIG.score_dispersion,
        NFL_CONFIG.mean_score_per_team,
        NFL_CONFIG.margin_sd,
    )
    report = report_nfl_production_split(tmp_path)
    for path, payload in saved.items():
        assert path.read_bytes() == payload
    assert (
        NFL_CONFIG.score_dispersion,
        NFL_CONFIG.mean_score_per_team,
        NFL_CONFIG.margin_sd,
    ) == before
    assert report["production"] == {
        "score_dispersion": before[0],
        "mean_score_per_team": before[1],
        "margin_sd": before[2],
    }
    chosen = historical_nfl_paths(tmp_path)
    assert {path.name for path in chosen} == {
        "01_A_at_H.json",
        "02_A_at_H.json",
        "03_A_at_H.json",
        "04_A_at_H.json",
        "05_A_at_H.json",
    }
    expected = split_historical_files(chosen, three_way=True)
    split = report["split"]
    assert split["train_game_ids"] == expected["train_game_ids"] == ["01", "02", "03"]
    assert split["validation_game_ids"] == expected["validation_game_ids"] == ["04"]
    assert split["holdout_game_ids"] == expected["holdout_game_ids"] == ["05"]
    college_report = build_report([college, elo_only], root=tmp_path)
    assert college_report["games"] == []
    assert college_report["skipped"] == []
    assert report["overall"]["overall"]["n"] == 10
    assert report["train"]["overall"]["n"] == 6
    assert report["validation"]["overall"]["n"] == 2
    assert report["holdout"]["overall"]["n"] == 2
    assert report["train"]["overall"]["home_win_rate"] == pytest.approx(2 / 3)
    assert report["validation"]["overall"]["home_win_rate"] == 1.0
    assert report["holdout"]["overall"]["home_win_rate"] == 0.0
    buckets = [row["bucket"] for row in report["overall"]["by_bucket"]]
    assert buckets == list(BUCKETS)
    text = format_nfl_split_report(report)
    assert "Train games: 3" in text
    assert "Validation games: 1" in text
    assert "Hold-out games: 1" in text
    assert "SportConfig was not modified" in text


def test_calibrate_nfl_split_flag_rejects_extra_paths(capsys):
    assert run_calibrate(["--nfl-split", "examples/nfl_sample.json"]) == 2
    assert "--nfl-split" in capsys.readouterr().err


def test_readme_documents_the_command_and_the_limit():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "python -m live_win_prob calibrate" in readme
    assert "not a historical backtest" in readme
    assert (
        "too small to retune margin_sd, possession points, or strength multipliers"
        in readme
    )
    assert "artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
