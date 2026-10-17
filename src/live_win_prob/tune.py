"""Temporary parameter search for calibration.

NFL candidates copy ``SportConfig`` and discard the copy. NBA candidates
temporarily replace the possession-points binding the basketball model
reads, then restore it. This module does not edit ``score_dispersion``,
``mean_score_per_team``, possession points, strength multipliers, or any
other model source.

NFL search files are ``data/calibration/nfl/``. NBA search files are
``data/calibration/nba/``. The full calibration input list is scored only
so each candidate can also report that sport's row.

The default scores every historical file together. ``split=True`` ranks
on train and also scores a hold-out: game ids are sorted as text, and
every 5th id (positions 5, 10, 15, ...) is hold-out. ``three_way=True``
uses the same sort and repeating groups of five: positions 1, 2, 3 are
train, position 4 is validation, and position 5 is hold-out. A file
follows its game id, so snapshots from one game stay together.
"""

from __future__ import annotations

import json
import math
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from ms_win_prob.config import SportConfig
from ms_win_prob.football.config import NFL_CONFIG
from ms_win_prob.state import GameState

from live_win_prob.calibrate import (
    build_report,
    default_paths,
    historical_paths,
    repo_root,
    write_report,
)
from live_win_prob.replay import config_for_state

# A short grid around the production dispersion of 4.05. Not an exhaustive search.
NFL_DISPERSION_GRID: tuple[float, ...] = (2.5, 3.0, 3.5, 4.05, 4.5, 5.0, 6.0)

# A short grid around the production NBA possession value of 1.12.
NBA_POSSESSION_GRID: tuple[float, ...] = (0.6, 0.8, 1.0, 1.12, 1.3, 1.5, 1.8)

_LATE_REGULATION = ("1-5 min", "<1 min")
_METRIC_KEYS = ("n", "mean_win_prob", "home_win_rate", "brier", "log_loss")

# 1-based positions 5, 10, 15, ... of the sorted game-id list.
HOLDOUT_EVERY = 5
SPLIT_METHOD = (
    "Sort distinct game_ids as text. Hold out every 5th id "
    "(1-based positions 5, 10, 15, ...). "
    "Each file follows its game_id, so every snapshot from a game stays "
    "in the same set. A file with several ids is hold-out only when all of "
    "those ids are hold-out ids. Files with no readable game_id stay in train."
)
THREE_WAY_METHOD = (
    "Sort distinct game_ids as text. In each repeating group of five, "
    "1-based positions 1, 2, and 3 are train, position 4 is validation, "
    "and position 5 is hold-out. "
    "Each file follows its game_id, so every snapshot from a game stays "
    "in the same set. A file with several ids is validation or hold-out "
    "only when every id belongs to that one set. Mixed files and files "
    "with no readable game_id stay in train."
)


def nfl_config_for(
    score_dispersion: float,
    mean_score_per_team: float | None = None,
):
    """Return a chooser that copies the NFL config for one candidate.

    Other sports keep ``config_for_state``. The production ``NFL_CONFIG``
    object is not replaced.
    """
    mean = (
        NFL_CONFIG.mean_score_per_team
        if mean_score_per_team is None
        else mean_score_per_team
    )

    def config_for(state: GameState) -> SportConfig:
        config = config_for_state(state)
        if state.sport != "nfl":
            return config
        return replace(
            config,
            score_dispersion=score_dispersion,
            mean_score_per_team=mean,
        )

    return config_for


def historical_nfl_paths(root: Path | None = None) -> list[Path]:
    """JSON files under ``data/calibration/nfl/``, in historical path order."""
    root = repo_root() if root is None else root
    base = (root / "data" / "calibration" / "nfl").resolve()
    chosen: list[Path] = []
    for path in historical_paths(root):
        try:
            path.resolve().relative_to(base)
        except ValueError:
            continue
        chosen.append(path)
    return chosen


def search_nfl_dispersion(
    dispersions: tuple[float, ...] | list[float] = NFL_DISPERSION_GRID,
    *,
    mean_score_per_team: float | None = None,
    historical: list[Path] | None = None,
    full: list[Path] | None = None,
    root: Path | None = None,
    split: bool = False,
    three_way: bool = False,
) -> dict[str, object]:
    """Rank candidates by NFL Brier. Production config stays put.

    The default ranks the whole historical file list. ``split=True`` ranks
    the train games and also scores the hold-out. ``three_way=True`` ranks
    the train games and also scores validation and hold-out.
    """
    root = repo_root() if root is None else root
    before = _production_snapshot()
    mean = before["mean_score_per_team"] if mean_score_per_team is None else mean_score_per_team
    historical_files = historical_nfl_paths(root) if historical is None else historical
    full_files = default_paths(root) if full is None else full
    parts = _requested_split(historical_files, split=split, three_way=three_way)
    train_files, validation_files, holdout_files = _split_paths(historical_files, parts)
    candidates: list[dict[str, object]] = []
    for dispersion in dispersions:
        chooser = nfl_config_for(dispersion, mean)
        sample = chooser(_probe_state())
        if sample is NFL_CONFIG:
            raise RuntimeError("NFL override returned the production config")
        train_report = build_report(train_files, root=root, config_for=chooser)
        full_report = build_report(full_files, root=root, config_for=chooser)
        row: dict[str, object] = {
            "score_dispersion": dispersion,
            "mean_score_per_team": mean,
            "margin_sd": sample.margin_sd,
            "full_set": _nfl_slice(full_report),
        }
        if parts is None:
            row["historical"] = _nfl_slice(train_report)
        else:
            row["train"] = _nfl_slice(train_report)
            row["holdout"] = _nfl_slice(
                build_report(holdout_files, root=root, config_for=chooser)
            )
            if three_way:
                row["validation"] = _nfl_slice(
                    build_report(validation_files, root=root, config_for=chooser)
                )
        candidates.append(row)
    _require_unchanged(before)
    ranked = sorted(candidates, key=_brier_key)
    for rank, candidate in enumerate(ranked, start=1):
        candidate["rank"] = rank
    report: dict[str, object] = {
        "note": (
            "Temporary NFL score_dispersion grid. "
            "Production SportConfig values are not modified."
        ),
        "sport": "nfl",
        "ranked_by": "train overall brier" if parts is not None else "historical overall brier",
        "production": before,
        "mean_score_per_team": mean,
        "grid": list(dispersions),
        "historical_inputs": [_display(path, root) for path in historical_files],
        "full_set_inputs": [_display(path, root) for path in full_files],
        "best_overall_brier": _best(ranked, "overall"),
        "best_under_5_min_brier": _best(ranked, "<5 min"),
        "candidates": ranked,
    }
    if parts is not None:
        report["split"] = _split_record(parts, root)
    return report


def format_tuning_report(report: dict[str, object]) -> str:
    """Text table ranked by train Brier, or by the whole historical set."""
    if "split" in report:
        return _format_split_report(
            report,
            value_header="dispersion",
            value_key="score_dispersion",
            search_line=(
                "Search set: data/calibration/nfl, split by game_id. "
                "Ranked on train. full_brier is the NFL row of the full "
                "calibration input list."
            ),
        )
    lines = [
        str(report["note"]),
        "Search set: data/calibration/nfl. "
        "full_brier is the NFL row of the full calibration input list.",
        "Late regulation (<5 min) joins the 1-5 min and <1 min buckets.",
        "",
        _table(
            (
                "rank",
                "dispersion",
                "margin_sd",
                "n",
                "mean_win_prob",
                "home_win_rate",
                "brier",
                "log_loss",
                "<5 brier",
                "<5 log_loss",
                "ot_brier",
                "full_brier",
            ),
            [_candidate_line(candidate) for candidate in _candidates(report)],
        ),
    ]
    return "\n".join(lines) + "\n"


def run_tune_nfl(argv: list[str]) -> int:
    """Print the NFL dispersion grid and write ``artifacts/tuning_nfl_dispersion.json``.

    Optional ``--mean`` overrides ``mean_score_per_team`` for this run only.
    Returns 0 when the historical NFL set scored at least one snapshot.
    """
    mean, split, three_way, error = _parse_nfl_args(argv)
    if error is not None:
        print(error, file=sys.stderr)
        return 2
    root = repo_root()
    if not historical_nfl_paths(root):
        print("no JSON files under data/calibration/nfl")
        return 1
    report = search_nfl_dispersion(
        mean_score_per_team=mean, root=root, split=split, three_way=three_way
    )
    print(format_tuning_report(report), end="")
    write_report(report, root / "artifacts" / "tuning_nfl_dispersion.json")
    overall = _ranking_block(_candidates(report)[0])["overall"]
    return 0 if isinstance(overall, dict) and overall["n"] else 1


def historical_nba_paths(root: Path | None = None) -> list[Path]:
    """JSON files under ``data/calibration/nba/``, in historical path order."""
    root = repo_root() if root is None else root
    base = (root / "data" / "calibration" / "nba").resolve()
    chosen: list[Path] = []
    for path in historical_paths(root):
        try:
            path.resolve().relative_to(base)
        except ValueError:
            continue
        chosen.append(path)
    return chosen


@contextmanager
def temporary_nba_possession_points(points: float):
    """Point the basketball model at ``points`` for the duration of the block.

    Restores the previous binding on the way out. ``NBA_POSSESSION_POINTS``
    in ``basketball/config.py`` is not assigned.
    """
    import ms_win_prob.basketball.config as basketball_config
    import ms_win_prob.basketball.model as basketball_model

    config_value = basketball_config.NBA_POSSESSION_POINTS
    previous = basketball_model.NBA_POSSESSION_POINTS
    basketball_model.NBA_POSSESSION_POINTS = points
    try:
        yield
    finally:
        basketball_model.NBA_POSSESSION_POINTS = previous
        if basketball_config.NBA_POSSESSION_POINTS != config_value:
            raise RuntimeError("NBA_POSSESSION_POINTS in basketball config changed")


def search_nba_possession(
    points: tuple[float, ...] | list[float] = NBA_POSSESSION_GRID,
    *,
    historical: list[Path] | None = None,
    full: list[Path] | None = None,
    root: Path | None = None,
    split: bool = False,
    three_way: bool = False,
) -> dict[str, object]:
    """Rank NBA possession values by Brier. Production value stays put.

    The default ranks the whole historical file list. ``split=True`` ranks
    the train games and also scores the hold-out. ``three_way=True`` ranks
    the train games and also scores validation and hold-out.
    """
    import ms_win_prob.basketball.config as basketball_config
    import ms_win_prob.basketball.model as basketball_model

    root = repo_root() if root is None else root
    production = basketball_config.NBA_POSSESSION_POINTS
    model_before = basketball_model.NBA_POSSESSION_POINTS
    historical_files = historical_nba_paths(root) if historical is None else historical
    full_files = default_paths(root) if full is None else full
    parts = _requested_split(historical_files, split=split, three_way=three_way)
    train_files, validation_files, holdout_files = _split_paths(historical_files, parts)
    candidates: list[dict[str, object]] = []
    for value in points:
        with temporary_nba_possession_points(value):
            train_report = build_report(train_files, root=root)
            full_report = build_report(full_files, root=root)
            row: dict[str, object] = {
                "possession_points": value,
                "full_set": _sport_slice(full_report, "nba"),
            }
            if parts is None:
                row["historical"] = _sport_slice(train_report, "nba")
            else:
                row["train"] = _sport_slice(train_report, "nba")
                row["holdout"] = _sport_slice(build_report(holdout_files, root=root))
                if three_way:
                    row["validation"] = _sport_slice(
                        build_report(validation_files, root=root)
                    )
        candidates.append(row)
    if basketball_config.NBA_POSSESSION_POINTS != production:
        raise RuntimeError("NBA_POSSESSION_POINTS in basketball config changed")
    if basketball_model.NBA_POSSESSION_POINTS != model_before:
        raise RuntimeError("basketball model possession points were not restored")
    ranked = sorted(candidates, key=_possession_brier_key)
    for rank, candidate in enumerate(ranked, start=1):
        candidate["rank"] = rank
    report: dict[str, object] = {
        "note": (
            "Temporary NBA possession-points grid. "
            "Production NBA_POSSESSION_POINTS is not modified."
        ),
        "sport": "nba",
        "ranked_by": "train overall brier" if parts is not None else "historical overall brier",
        "production_possession_points": production,
        "grid": list(points),
        "historical_inputs": [_display(path, root) for path in historical_files],
        "full_set_inputs": [_display(path, root) for path in full_files],
        "best_overall_brier": _best_possession(ranked, "overall"),
        "best_under_5_min_brier": _best_possession(ranked, "<5 min"),
        "candidates": ranked,
    }
    if parts is not None:
        report["split"] = _split_record(parts, root)
    return report


def format_nba_possession_report(report: dict[str, object]) -> str:
    """Text table ranked by train Brier, or by the whole historical set."""
    if "split" in report:
        return _format_split_report(
            report,
            value_header="possession",
            value_key="possession_points",
            search_line=(
                "Search set: data/calibration/nba, split by game_id. "
                "Ranked on train. full_brier is the NBA row of the full "
                "calibration input list."
            ),
        )
    lines = [
        str(report["note"]),
        "Search set: data/calibration/nba. "
        "full_brier is the NBA row of the full calibration input list.",
        "Late regulation (<5 min) joins the 1-5 min and <1 min buckets.",
        "",
        _table(
            (
                "rank",
                "possession",
                "n",
                "home_win_rate",
                "brier",
                "log_loss",
                "<5 brier",
                "full_brier",
            ),
            [_nba_candidate_line(candidate) for candidate in _candidates(report)],
        ),
    ]
    return "\n".join(lines) + "\n"


def run_tune_nba(argv: list[str]) -> int:
    """Print the NBA possession grid and write ``artifacts/tuning_nba_possession.json``.

    Returns 0 when the historical NBA set scored at least one snapshot.
    """
    if argv == []:
        split, three_way = False, False
    elif argv == ["--split"]:
        split, three_way = True, False
    elif argv == ["--three-way"]:
        split, three_way = False, True
    else:
        print(
            "usage: python -m live_win_prob tune-nba [--split | --three-way]",
            file=sys.stderr,
        )
        return 2
    root = repo_root()
    if not historical_nba_paths(root):
        print("no JSON files under data/calibration/nba")
        return 1
    report = search_nba_possession(root=root, split=split, three_way=three_way)
    print(format_nba_possession_report(report), end="")
    write_report(report, root / "artifacts" / "tuning_nba_possession.json")
    overall = _ranking_block(_candidates(report)[0])["overall"]
    return 0 if isinstance(overall, dict) and overall["n"] else 1


def _production_snapshot() -> dict[str, float]:
    return {
        "score_dispersion": NFL_CONFIG.score_dispersion,
        "mean_score_per_team": NFL_CONFIG.mean_score_per_team,
        "margin_sd": NFL_CONFIG.margin_sd,
    }


def _require_unchanged(before: dict[str, float]) -> None:
    after = _production_snapshot()
    if after != before:
        raise RuntimeError("NFL_CONFIG changed during the dispersion search")


def _probe_state() -> GameState:
    """A stand-in NFL state used only to read the copied config."""
    return GameState(
        sport="nfl",
        game_id="tune-probe",
        home="H",
        away="A",
        home_score=0,
        away_score=0,
        period=1,
        seconds_remaining_period=15 * 60,
        seconds_remaining_total=60 * 60,
        status="pre",
        source="tune",
        as_of=datetime(2026, 10, 16, tzinfo=timezone.utc),
        prior_home=0.5,
    )


def _nfl_slice(report: dict[str, object]) -> dict[str, object]:
    return _sport_slice(report, "nfl")


def _sport_slice(report: dict[str, object], sport: str) -> dict[str, object]:
    overall = _metrics(_find_row(report, "by_sport", sport=sport))
    under_5 = _combine(
        [
            _metrics(_find_row(report, "by_sport_and_bucket", sport=sport, bucket=bucket))
            for bucket in _LATE_REGULATION
        ]
    )
    overtime = _metrics(
        _find_row(report, "by_sport_and_bucket", sport=sport, bucket="overtime")
    )
    return {
        "overall": overall,
        "<5 min": under_5,
        "overtime": overtime,
        "skipped": report["skipped"],
    }


def _find_row(
    report: dict[str, object],
    key: str,
    *,
    sport: str,
    bucket: str | None = None,
) -> dict[str, object] | None:
    rows = report[key]
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict) or row.get("sport") != sport:
            continue
        if bucket is None or row.get("bucket") == bucket:
            return row
    return None


def _metrics(row: dict[str, object] | None) -> dict[str, object]:
    if row is None or not row.get("n"):
        return {
            "n": 0,
            "mean_win_prob": None,
            "home_win_rate": None,
            "brier": None,
            "log_loss": None,
        }
    return {
        "n": row["n"],
        "mean_win_prob": row["mean_predicted_home_win_prob"],
        "home_win_rate": row["home_win_rate"],
        "brier": row["brier"],
        "log_loss": row["log_loss"],
    }


def _combine(rows: list[dict[str, object]]) -> dict[str, object]:
    present = [row for row in rows if row["n"]]
    if not present:
        return _metrics(None)
    n = sum(int(row["n"]) for row in present)

    def average(key: str) -> float:
        return sum(float(row[key]) * int(row["n"]) for row in present) / n

    return {
        "n": n,
        "mean_win_prob": average("mean_win_prob"),
        "home_win_rate": average("home_win_rate"),
        "brier": average("brier"),
        "log_loss": average("log_loss"),
    }


def _brier_key(candidate: dict[str, object]) -> tuple[float, float]:
    block = _ranking_block(candidate)
    dispersion = float(candidate["score_dispersion"])
    if not isinstance(block, dict):
        return (math.inf, dispersion)
    overall = block["overall"]
    brier = overall["brier"] if isinstance(overall, dict) else None
    if not isinstance(brier, (int, float)):
        return (math.inf, dispersion)
    return (float(brier), dispersion)


def _best(ranked: list[dict[str, object]], section: str) -> dict[str, object] | None:
    scored = []
    for candidate in ranked:
        block = _ranking_block(candidate)
        if not isinstance(block, dict):
            continue
        metrics = block[section]
        if not isinstance(metrics, dict) or not isinstance(metrics.get("brier"), (int, float)):
            continue
        scored.append((float(metrics["brier"]), float(candidate["score_dispersion"]), candidate))
    if not scored:
        return None
    _brier, _dispersion, winner = min(scored)
    metrics = _ranking_block(winner)[section]
    return {
        "score_dispersion": winner["score_dispersion"],
        "mean_score_per_team": winner["mean_score_per_team"],
        "margin_sd": winner["margin_sd"],
        **metrics,
    }


def _possession_brier_key(candidate: dict[str, object]) -> tuple[float, float]:
    block = _ranking_block(candidate)
    points = float(candidate["possession_points"])
    if not isinstance(block, dict):
        return (math.inf, points)
    overall = block["overall"]
    brier = overall["brier"] if isinstance(overall, dict) else None
    if not isinstance(brier, (int, float)):
        return (math.inf, points)
    return (float(brier), points)


def _best_possession(ranked: list[dict[str, object]], section: str) -> dict[str, object] | None:
    scored = []
    for candidate in ranked:
        block = _ranking_block(candidate)
        if not isinstance(block, dict):
            continue
        metrics = block[section]
        if not isinstance(metrics, dict) or not isinstance(metrics.get("brier"), (int, float)):
            continue
        scored.append((float(metrics["brier"]), float(candidate["possession_points"]), candidate))
    if not scored:
        return None
    _brier, _points, winner = min(scored)
    metrics = _ranking_block(winner)[section]
    return {"possession_points": winner["possession_points"], **metrics}


def _ranking_block(candidate: dict[str, object]) -> dict[str, object]:
    """Train metrics when a split is active, otherwise the whole historical set."""
    block = candidate["train"] if "train" in candidate else candidate["historical"]
    if not isinstance(block, dict):
        raise TypeError("ranking metrics must be an object")
    return block


def _nba_candidate_line(candidate: dict[str, object]) -> list[str]:
    historical = candidate["historical"]
    full = candidate["full_set"]
    if not isinstance(historical, dict) or not isinstance(full, dict):
        raise TypeError("candidate slices must be objects")
    overall = historical["overall"]
    late = historical["<5 min"]
    full_overall = full["overall"]
    return [
        str(candidate["rank"]),
        _num(candidate["possession_points"]),
        _num(overall["n"]),
        _num(overall["home_win_rate"]),
        _num(overall["brier"]),
        _num(overall["log_loss"]),
        _num(late["brier"]),
        _num(full_overall["brier"]),
    ]


def _candidates(report: dict[str, object]) -> list[dict[str, object]]:
    rows = report["candidates"]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise TypeError("candidates must be a list of objects")
    return rows


def _candidate_line(candidate: dict[str, object]) -> list[str]:
    historical = candidate["historical"]
    full = candidate["full_set"]
    if not isinstance(historical, dict) or not isinstance(full, dict):
        raise TypeError("candidate slices must be objects")
    overall = historical["overall"]
    late = historical["<5 min"]
    overtime = historical["overtime"]
    full_overall = full["overall"]
    return [
        str(candidate["rank"]),
        _num(candidate["score_dispersion"]),
        _num(candidate["margin_sd"]),
        _num(overall["n"]),
        _num(overall["mean_win_prob"]),
        _num(overall["home_win_rate"]),
        _num(overall["brier"]),
        _num(overall["log_loss"]),
        _num(late["brier"]),
        _num(late["log_loss"]),
        _num(overtime["brier"]),
        _num(full_overall["brier"]),
    ]


def _num(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, int):
        return str(value)
    return f"{value:.6f}"


def _table(headers: tuple[str, ...], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def render(cells: tuple[str, ...] | list[str]) -> str:
        return "  ".join(cell.rjust(widths[index]) for index, cell in enumerate(cells)).rstrip()

    lines = [render(headers), render("-" * width for width in widths)]
    lines.extend(render(row) for row in rows)
    return "\n".join(lines)


def _display(path: Path, root: Path) -> str:
    absolute = path if path.is_absolute() else Path.cwd() / path
    try:
        return absolute.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return absolute.resolve().as_posix()


def split_historical_files(
    paths: list[Path], *, three_way: bool = False
) -> dict[str, object]:
    """Split historical files by game_id.

    The default is two-way. Game ids are sorted as text, and every 5th id
    (1-based positions 5, 10, 15, ...) is hold-out. The rest are train.

    ``three_way=True`` uses the same sorted list in repeating groups of
    five: positions 1, 2, and 3 are train, position 4 is validation, and
    position 5 is hold-out. Snapshots are not split apart from their game.
    """
    grouped = [(path, _game_ids_in_file(path)) for path in paths]
    distinct = sorted({game_id for _path, ids in grouped for game_id in ids})
    holdout_ids = {
        game_id
        for index, game_id in enumerate(distinct)
        if (index + 1) % HOLDOUT_EVERY == 0
    }
    validation_ids = (
        {
            game_id
            for index, game_id in enumerate(distinct)
            if (index + 1) % HOLDOUT_EVERY == 4
        }
        if three_way
        else set()
    )
    train_paths: list[Path] = []
    validation_paths: list[Path] = []
    holdout_paths: list[Path] = []
    for path, ids in grouped:
        if ids and all(game_id in holdout_ids for game_id in ids):
            holdout_paths.append(path)
        elif three_way and ids and all(game_id in validation_ids for game_id in ids):
            validation_paths.append(path)
        else:
            train_paths.append(path)
    record: dict[str, object] = {
        "method": THREE_WAY_METHOD if three_way else SPLIT_METHOD,
        "holdout_every": HOLDOUT_EVERY,
        "train_game_ids": [
            game_id
            for game_id in distinct
            if game_id not in holdout_ids and game_id not in validation_ids
        ],
        "holdout_game_ids": [game_id for game_id in distinct if game_id in holdout_ids],
        "train_paths": train_paths,
        "holdout_paths": holdout_paths,
    }
    if three_way:
        record["validation_game_ids"] = [
            game_id for game_id in distinct if game_id in validation_ids
        ]
        record["validation_paths"] = validation_paths
    return record


def _requested_split(
    paths: list[Path], *, split: bool, three_way: bool
) -> dict[str, object] | None:
    if split and three_way:
        raise ValueError("choose split or three_way, not both")
    if not split and not three_way:
        return None
    return split_historical_files(paths, three_way=three_way)


def _split_paths(
    historical_files: list[Path], parts: dict[str, object] | None
) -> tuple[list[Path], list[Path], list[Path]]:
    if parts is None:
        return historical_files, [], []
    validation = parts["validation_paths"] if "validation_paths" in parts else []
    return (
        _path_list(parts["train_paths"]),
        _path_list(validation),
        _path_list(parts["holdout_paths"]),
    )


def _game_ids_in_file(path: Path) -> list[str]:
    """Game ids in file order. Empty when the file cannot be read."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    found: list[str] = []

    def add(value: object) -> None:
        if isinstance(value, str) and value and value not in found:
            found.append(value)

    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict):
                add(row.get("game_id"))
        return found
    if isinstance(payload, dict):
        header = payload.get("header")
        if isinstance(header, dict):
            add(header.get("id"))
        add(payload.get("game_id"))
        add(payload.get("id"))
    return found


def _path_list(value: object) -> list[Path]:
    if not isinstance(value, list) or any(not isinstance(path, Path) for path in value):
        raise TypeError("split paths must be a list of paths")
    return value


def _split_record(parts: dict[str, object], root: Path) -> dict[str, object]:
    record: dict[str, object] = {
        "active": True,
        "method": parts["method"],
        "holdout_every": parts["holdout_every"],
        "train_game_ids": parts["train_game_ids"],
        "holdout_game_ids": parts["holdout_game_ids"],
        "train_inputs": [_display(path, root) for path in _path_list(parts["train_paths"])],
        "holdout_inputs": [_display(path, root) for path in _path_list(parts["holdout_paths"])],
    }
    if "validation_game_ids" in parts:
        record["validation_game_ids"] = parts["validation_game_ids"]
        record["validation_inputs"] = [
            _display(path, root) for path in _path_list(parts["validation_paths"])
        ]
    return record


def _format_split_report(
    report: dict[str, object],
    *,
    value_header: str,
    value_key: str,
    search_line: str,
) -> str:
    split = report["split"]
    if not isinstance(split, dict):
        raise TypeError("split must be an object")
    train_ids = split["train_game_ids"]
    holdout_ids = split["holdout_game_ids"]
    validation_ids = split.get("validation_game_ids")
    train_n = len(train_ids) if isinstance(train_ids, list) else 0
    holdout_n = len(holdout_ids) if isinstance(holdout_ids, list) else 0
    three_way = isinstance(validation_ids, list)
    validation_n = len(validation_ids) if three_way else 0
    counts = f"Train games: {train_n}. Hold-out games: {holdout_n}."
    if three_way:
        counts = (
            f"Train games: {train_n}. Validation games: {validation_n}. "
            f"Hold-out games: {holdout_n}."
        )
    headers = (
        "rank",
        value_header,
        "train_n",
        "train_brier",
        "train_log_loss",
        "validation_n",
        "validation_brier",
        "validation_log_loss",
        "holdout_n",
        "holdout_brier",
        "holdout_log_loss",
    ) if three_way else (
        "rank",
        value_header,
        "train_n",
        "train_brier",
        "train_log_loss",
        "holdout_n",
        "holdout_brier",
        "holdout_log_loss",
        "holdout_<5_brier",
    )
    lines = [
        str(report["note"]),
        search_line,
        str(split["method"]),
        counts,
        "Late regulation (<5 min) joins the 1-5 min and <1 min buckets.",
        "",
        _table(
            headers,
            [
                _three_way_candidate_line(candidate, value_key)
                if three_way
                else _split_candidate_line(candidate, value_key)
                for candidate in _candidates(report)
            ],
        ),
    ]
    return "\n".join(lines) + "\n"


def _split_candidate_line(candidate: dict[str, object], value_key: str) -> list[str]:
    train = candidate["train"]
    holdout = candidate["holdout"]
    if not isinstance(train, dict) or not isinstance(holdout, dict):
        raise TypeError("train and holdout must be objects")
    train_overall = train["overall"]
    holdout_overall = holdout["overall"]
    holdout_late = holdout["<5 min"]
    return [
        str(candidate["rank"]),
        _num(candidate[value_key]),
        _num(train_overall["n"]),
        _num(train_overall["brier"]),
        _num(train_overall["log_loss"]),
        _num(holdout_overall["n"]),
        _num(holdout_overall["brier"]),
        _num(holdout_overall["log_loss"]),
        _num(holdout_late["brier"]),
    ]


def _three_way_candidate_line(candidate: dict[str, object], value_key: str) -> list[str]:
    train = candidate["train"]
    validation = candidate["validation"]
    holdout = candidate["holdout"]
    if not isinstance(train, dict) or not isinstance(validation, dict) or not isinstance(holdout, dict):
        raise TypeError("train, validation, and holdout must be objects")
    return [
        str(candidate["rank"]),
        _num(candidate[value_key]),
        _num(train["overall"]["n"]),
        _num(train["overall"]["brier"]),
        _num(train["overall"]["log_loss"]),
        _num(validation["overall"]["n"]),
        _num(validation["overall"]["brier"]),
        _num(validation["overall"]["log_loss"]),
        _num(holdout["overall"]["n"]),
        _num(holdout["overall"]["brier"]),
        _num(holdout["overall"]["log_loss"]),
    ]


def _parse_nfl_args(argv: list[str]) -> tuple[float | None, bool, bool, str | None]:
    """Parse ``tune-nfl`` flags. No flags leaves the unsplit grid."""
    mean: float | None = None
    split = False
    three_way = False
    index = 0
    usage = (
        "usage: python -m live_win_prob tune-nfl "
        "[--split | --three-way] [--mean MEAN_SCORE_PER_TEAM]"
    )
    while index < len(argv):
        arg = argv[index]
        if arg == "--split":
            split = True
            index += 1
            continue
        if arg == "--three-way":
            three_way = True
            index += 1
            continue
        if arg == "--mean" and index + 1 < len(argv):
            try:
                mean = float(argv[index + 1])
            except ValueError:
                return None, False, False, "mean_score_per_team must be a number"
            if mean <= 0:
                return None, False, False, "mean_score_per_team must be > 0"
            index += 2
            continue
        return None, False, False, usage
    if split and three_way:
        return None, False, False, usage
    return mean, split, three_way, None
