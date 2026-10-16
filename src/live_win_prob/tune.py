"""Temporary NFL score_dispersion search.

Scores ``compute_win_prob`` through ``build_report`` with a copied
``SportConfig``. The copy is discarded. This module does not edit
``score_dispersion``, ``mean_score_per_team``, possession points, strength
multipliers, or any other model source.

The search set is ``data/calibration/nfl/``. The full calibration input
list is scored only so each candidate can also report that NFL row.
"""

from __future__ import annotations

import math
import sys
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

_LATE_REGULATION = ("1-5 min", "<1 min")
_METRIC_KEYS = ("n", "mean_win_prob", "home_win_rate", "brier", "log_loss")


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
) -> dict[str, object]:
    """Rank candidates by historical NFL Brier. Production config stays put."""
    root = repo_root() if root is None else root
    before = _production_snapshot()
    mean = before["mean_score_per_team"] if mean_score_per_team is None else mean_score_per_team
    historical_files = historical_nfl_paths(root) if historical is None else historical
    full_files = default_paths(root) if full is None else full
    candidates: list[dict[str, object]] = []
    for dispersion in dispersions:
        chooser = nfl_config_for(dispersion, mean)
        sample = chooser(_probe_state())
        if sample is NFL_CONFIG:
            raise RuntimeError("NFL override returned the production config")
        historical_report = build_report(
            historical_files, root=root, config_for=chooser
        )
        full_report = build_report(full_files, root=root, config_for=chooser)
        candidates.append(
            {
                "score_dispersion": dispersion,
                "mean_score_per_team": mean,
                "margin_sd": sample.margin_sd,
                "historical": _nfl_slice(historical_report),
                "full_set": _nfl_slice(full_report),
            }
        )
    _require_unchanged(before)
    ranked = sorted(candidates, key=_brier_key)
    for rank, candidate in enumerate(ranked, start=1):
        candidate["rank"] = rank
    return {
        "note": (
            "Temporary NFL score_dispersion grid. "
            "Production SportConfig values are not modified."
        ),
        "sport": "nfl",
        "ranked_by": "historical overall brier",
        "production": before,
        "mean_score_per_team": mean,
        "grid": list(dispersions),
        "historical_inputs": [_display(path, root) for path in historical_files],
        "full_set_inputs": [_display(path, root) for path in full_files],
        "best_overall_brier": _best(ranked, "overall"),
        "best_under_5_min_brier": _best(ranked, "<5 min"),
        "candidates": ranked,
    }


def format_tuning_report(report: dict[str, object]) -> str:
    """Text table ranked by historical overall Brier."""
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
    mean, error = _parse_mean(argv)
    if error is not None:
        print(error, file=sys.stderr)
        return 2
    root = repo_root()
    if not historical_nfl_paths(root):
        print("no JSON files under data/calibration/nfl")
        return 1
    report = search_nfl_dispersion(mean_score_per_team=mean, root=root)
    print(format_tuning_report(report), end="")
    write_report(report, root / "artifacts" / "tuning_nfl_dispersion.json")
    overall = _candidates(report)[0]["historical"]["overall"]
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
    overall = _metrics(_find_row(report, "by_sport", sport="nfl"))
    under_5 = _combine(
        [
            _metrics(_find_row(report, "by_sport_and_bucket", sport="nfl", bucket=bucket))
            for bucket in _LATE_REGULATION
        ]
    )
    overtime = _metrics(
        _find_row(report, "by_sport_and_bucket", sport="nfl", bucket="overtime")
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
    historical = candidate["historical"]
    if not isinstance(historical, dict):
        return (math.inf, float(candidate["score_dispersion"]))
    overall = historical["overall"]
    brier = overall["brier"] if isinstance(overall, dict) else None
    dispersion = float(candidate["score_dispersion"])
    if not isinstance(brier, (int, float)):
        return (math.inf, dispersion)
    return (float(brier), dispersion)


def _best(ranked: list[dict[str, object]], section: str) -> dict[str, object] | None:
    scored = []
    for candidate in ranked:
        historical = candidate["historical"]
        if not isinstance(historical, dict):
            continue
        metrics = historical[section]
        if not isinstance(metrics, dict) or not isinstance(metrics.get("brier"), (int, float)):
            continue
        scored.append((float(metrics["brier"]), float(candidate["score_dispersion"]), candidate))
    if not scored:
        return None
    _brier, _dispersion, winner = min(scored)
    metrics = winner["historical"][section]
    return {
        "score_dispersion": winner["score_dispersion"],
        "mean_score_per_team": winner["mean_score_per_team"],
        "margin_sd": winner["margin_sd"],
        **metrics,
    }


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


def _parse_mean(argv: list[str]) -> tuple[float | None, str | None]:
    if not argv:
        return None, None
    if len(argv) == 2 and argv[0] == "--mean":
        try:
            mean = float(argv[1])
        except ValueError:
            return None, "mean_score_per_team must be a number"
        if mean <= 0:
            return None, "mean_score_per_team must be > 0"
        return mean, None
    return None, "usage: python -m live_win_prob tune-nfl [--mean MEAN_SCORE_PER_TEAM]"
