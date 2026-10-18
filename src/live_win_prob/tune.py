"""Temporary parameter search for calibration.

NFL candidates copy ``SportConfig`` and discard the copy. NBA candidates
temporarily replace the possession-points binding the basketball model
reads, then restore it. NHL candidates temporarily replace the
``rate_multipliers`` binding the hockey model reads, then restore it.
This module does not edit ``score_dispersion``, ``mean_score_per_team``,
possession points, strength multipliers, or any other model source.

NFL search files are ``data/calibration/nfl/``. NBA search files are
``data/calibration/nba/``. NHL search files are ``data/calibration/nhl/``.
The full calibration input list is scored only for NFL and NBA, so each
of those candidates can also report that sport's row. NHL scoring stays
on the historical NHL files.

The default scores every historical file together. ``three_way=True``
ranks on train and also scores validation and hold-out. Game ids are
sorted as text. In each repeating group of five, positions 1, 2, and 3
are train, position 4 is validation, and position 5 is hold-out. A file
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
from ms_win_prob.hockey.strength import parse_strength
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

# A short grid around the production NBA possession value of 1.30.
NBA_POSSESSION_GRID: tuple[float, ...] = (0.8, 1.0, 1.12, 1.2, 1.3, 1.4, 1.5, 1.8)

# Literals inside ``rate_multipliers``. The search reads them. It does not
# assign them back onto ``strength.py``.
NHL_PER_SKATER = 0.75
NHL_SHORTHANDED_REDUCTION = 0.30
NHL_SHORTHANDED_FLOOR = 0.35
NHL_BOTH_3S = 1.35
NHL_EMPTY_NET_OWN = 1.10
NHL_EMPTY_NET_FACTOR = 4.20

# One coefficient at a time. The other production literals stay put.
NHL_STRENGTH_GRIDS: tuple[tuple[str, tuple[float, ...]], ...] = (
    ("per_skater", (0.4, 0.6, 0.75, 0.9, 1.1)),
    ("both_3s", (1.1, 1.35, 1.6)),
    ("empty_net_factor", (3.0, 4.2, 5.5)),
)

_STRENGTH_TIE = 1e-12

_LATE_REGULATION = ("1-5 min", "<1 min")
_METRIC_KEYS = ("n", "mean_win_prob", "home_win_rate", "brier", "log_loss")

# Repeating groups of five on the sorted game-id list:
# 1-based positions 1-3 are train, 4 is validation, and 5 is hold-out.
HOLDOUT_EVERY = 5
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
    three_way: bool = False,
) -> dict[str, object]:
    """Rank candidates by NFL Brier. Production config stays put.

    The default ranks the whole historical file list. ``three_way=True`` ranks
    the train games and also scores validation and hold-out.
    """
    root = repo_root() if root is None else root
    before = _production_snapshot()
    mean = before["mean_score_per_team"] if mean_score_per_team is None else mean_score_per_team
    historical_files = historical_nfl_paths(root) if historical is None else historical
    full_files = default_paths(root) if full is None else full
    parts = _requested_split(historical_files, three_way=three_way)
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
            row["validation"] = _nfl_slice(
                build_report(validation_files, root=root, config_for=chooser)
            )
            row["holdout"] = _nfl_slice(
                build_report(holdout_files, root=root, config_for=chooser)
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
    mean, three_way, error = _parse_nfl_args(argv)
    if error is not None:
        print(error, file=sys.stderr)
        return 2
    root = repo_root()
    if not historical_nfl_paths(root):
        print("no JSON files under data/calibration/nfl")
        return 1
    report = search_nfl_dispersion(
        mean_score_per_team=mean, root=root, three_way=three_way
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
    three_way: bool = False,
) -> dict[str, object]:
    """Rank NBA possession values by Brier. Production value stays put.

    The default ranks the whole historical file list. ``three_way=True`` ranks
    the train games and also scores validation and hold-out.
    """
    import ms_win_prob.basketball.config as basketball_config
    import ms_win_prob.basketball.model as basketball_model

    root = repo_root() if root is None else root
    production = basketball_config.NBA_POSSESSION_POINTS
    model_before = basketball_model.NBA_POSSESSION_POINTS
    historical_files = historical_nba_paths(root) if historical is None else historical
    full_files = default_paths(root) if full is None else full
    parts = _requested_split(historical_files, three_way=three_way)
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
                row["validation"] = _sport_slice(
                    build_report(validation_files, root=root), "nba"
                )
                row["holdout"] = _sport_slice(
                    build_report(holdout_files, root=root), "nba"
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
        three_way = False
    elif argv == ["--three-way"]:
        three_way = True
    else:
        print(
            "usage: python -m live_win_prob tune-nba [--three-way]",
            file=sys.stderr,
        )
        return 2
    root = repo_root()
    if not historical_nba_paths(root):
        print("no JSON files under data/calibration/nba")
        return 1
    report = search_nba_possession(root=root, three_way=three_way)
    print(format_nba_possession_report(report), end="")
    write_report(report, root / "artifacts" / "tuning_nba_possession.json")
    overall = _ranking_block(_candidates(report)[0])["overall"]
    return 0 if isinstance(overall, dict) and overall["n"] else 1


def historical_nhl_paths(root: Path | None = None) -> list[Path]:
    """JSON files under ``data/calibration/nhl/``, in historical path order."""
    root = repo_root() if root is None else root
    base = (root / "data" / "calibration" / "nhl").resolve()
    chosen: list[Path] = []
    for path in historical_paths(root):
        try:
            path.resolve().relative_to(base)
        except ValueError:
            continue
        chosen.append(path)
    return chosen


def nhl_strength_settings(
    *,
    per_skater: float = NHL_PER_SKATER,
    shorthanded_reduction: float = NHL_SHORTHANDED_REDUCTION,
    shorthanded_floor: float = NHL_SHORTHANDED_FLOOR,
    both_3s: float = NHL_BOTH_3S,
    empty_net_own: float = NHL_EMPTY_NET_OWN,
    empty_net_factor: float = NHL_EMPTY_NET_FACTOR,
) -> dict[str, float]:
    """Coefficients for one temporary strength evaluation."""
    return {
        "per_skater": per_skater,
        "shorthanded_reduction": shorthanded_reduction,
        "shorthanded_floor": shorthanded_floor,
        "both_3s": both_3s,
        "empty_net_own": empty_net_own,
        "empty_net_factor": empty_net_factor,
    }


def strength_rate_multipliers(
    state: GameState,
    *,
    per_skater: float = NHL_PER_SKATER,
    shorthanded_reduction: float = NHL_SHORTHANDED_REDUCTION,
    shorthanded_floor: float = NHL_SHORTHANDED_FLOOR,
    both_3s: float = NHL_BOTH_3S,
    empty_net_own: float = NHL_EMPTY_NET_OWN,
    empty_net_factor: float = NHL_EMPTY_NET_FACTOR,
) -> tuple[float, float]:
    """Same manpower rules as ``strength.rate_multipliers``, with overrides.

    Production defaults match the literals in ``strength.py``. A caller
    that passes those defaults must agree with that function on the probe
    states. This function does not write the module.
    """
    home_skaters, away_skaters = parse_strength(state.strength)
    diff = home_skaters - away_skaters
    home_mult = 1.0
    away_mult = 1.0
    if home_skaters <= 3 and away_skaters <= 3 and diff == 0:
        home_mult = both_3s
        away_mult = both_3s
    elif diff > 0:
        home_mult = 1.0 + per_skater * diff
        away_mult = max(shorthanded_floor, 1.0 - shorthanded_reduction * diff)
    elif diff < 0:
        step = -diff
        away_mult = 1.0 + per_skater * step
        home_mult = max(shorthanded_floor, 1.0 - shorthanded_reduction * step)
    if state.extra_attacker and (home_skaters == 6 or away_skaters == 6):
        if home_skaters > away_skaters:
            home_mult *= empty_net_own
            away_mult *= empty_net_factor
        elif away_skaters > home_skaters:
            away_mult *= empty_net_own
            home_mult *= empty_net_factor
    return home_mult, away_mult


@contextmanager
def temporary_hockey_strength(
    *,
    per_skater: float = NHL_PER_SKATER,
    shorthanded_reduction: float = NHL_SHORTHANDED_REDUCTION,
    shorthanded_floor: float = NHL_SHORTHANDED_FLOOR,
    both_3s: float = NHL_BOTH_3S,
    empty_net_own: float = NHL_EMPTY_NET_OWN,
    empty_net_factor: float = NHL_EMPTY_NET_FACTOR,
):
    """Point the hockey model at one strength setting, then restore it.

    ``strength.rate_multipliers`` and ``strength.py`` stay as they were.
    The model module's binding is the one ``hockey_win_probability`` calls.
    """
    import ms_win_prob.hockey.model as hockey_model
    import ms_win_prob.hockey.strength as strength_module

    previous = hockey_model.rate_multipliers
    strength_fn = strength_module.rate_multipliers
    source = Path(strength_module.__file__).read_bytes()
    settings = nhl_strength_settings(
        per_skater=per_skater,
        shorthanded_reduction=shorthanded_reduction,
        shorthanded_floor=shorthanded_floor,
        both_3s=both_3s,
        empty_net_own=empty_net_own,
        empty_net_factor=empty_net_factor,
    )

    def patched(state: GameState) -> tuple[float, float]:
        return strength_rate_multipliers(state, **settings)

    hockey_model.rate_multipliers = patched
    try:
        yield
    finally:
        hockey_model.rate_multipliers = previous
        if strength_module.rate_multipliers is not strength_fn:
            raise RuntimeError("strength.rate_multipliers was replaced")
        if Path(strength_module.__file__).read_bytes() != source:
            raise RuntimeError("strength.py changed during the strength override")


def search_nhl_strength(
    grids: tuple[tuple[str, tuple[float, ...]], ...] | list[tuple[str, tuple[float, ...]]]
    | None = None,
    *,
    historical: list[Path] | None = None,
    root: Path | None = None,
    three_way: bool = False,
) -> dict[str, object]:
    """Rank one-at-a-time strength grids by NHL Brier.

    The default ranks the whole historical file list. ``three_way=True`` ranks
    the train games and also scores validation and hold-out. Only files
    under ``data/calibration/nhl/`` are scored unless ``historical`` is passed.
    """
    root = repo_root() if root is None else root
    before = _hockey_source_snapshot()
    _require_strength_formula_matches_production()
    chosen = NHL_STRENGTH_GRIDS if grids is None else tuple(grids)
    _require_strength_grids(chosen)
    historical_files = historical_nhl_paths(root) if historical is None else historical
    parts = _requested_split(historical_files, three_way=three_way)
    production = nhl_strength_settings()
    coverage = _strength_coverage(historical_files)
    grid_reports: list[dict[str, object]] = []
    for name, values in chosen:
        grid_reports.append(
            _search_one_strength(
                name,
                values,
                historical_files=historical_files,
                parts=parts,
                root=root,
                production=production,
            )
        )
    _require_hockey_sources_unchanged(before)
    report: dict[str, object] = {
        "note": (
            "Temporary one-at-a-time NHL strength grids. "
            "The hockey model reads a replacement for rate_multipliers "
            "during scoring, then the production function is restored. "
            "strength.py, SportConfig, and the other model constants are "
            "not modified. Scored files are data/calibration/nhl only."
        ),
        "sport": "nhl",
        "ranked_by": "train overall brier" if parts is not None else "historical overall brier",
        "tie_break": "closest to the production value, then the smaller value",
        "production": production,
        "scored_files": "data/calibration/nhl",
        "strength_coverage": coverage,
        "historical_inputs": [_display(path, root) for path in historical_files],
        "grids": grid_reports,
    }
    if parts is not None:
        report["split"] = _split_record(parts, root)
    return report


def format_nhl_strength_report(report: dict[str, object]) -> str:
    """Text tables, one coefficient at a time, best train Brier first."""
    lines = [
        str(report["note"]),
        "Search set: data/calibration/nhl. "
        "Each grid moves one coefficient and holds the others at production.",
        "Ranked on train Brier. Ties break toward the production value.",
    ]
    if "split" in report:
        split = report["split"]
        if not isinstance(split, dict):
            raise TypeError("split must be an object")
        lines.append(str(split["method"]))
        lines.append(_split_count_line(split))
    lines.append("Late regulation (<5 min) joins the 1-5 min and <1 min buckets.")
    lines.append(_coverage_line(report["strength_coverage"]))
    lines.append("")
    grids = report["grids"]
    if not isinstance(grids, list):
        raise TypeError("grids must be a list")
    for grid in grids:
        if not isinstance(grid, dict):
            raise TypeError("each grid must be an object")
        lines.extend(_format_strength_grid(grid))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_tune_nhl(argv: list[str]) -> int:
    """Print the NHL strength grids and write ``artifacts/tuning_nhl_strength.json``.

    Returns 0 when the ranked train or historical set scored at least one snapshot.
    """
    if argv == []:
        three_way = False
    elif argv == ["--three-way"]:
        three_way = True
    else:
        print(
            "usage: python -m live_win_prob tune-nhl [--three-way]",
            file=sys.stderr,
        )
        return 2
    root = repo_root()
    if not historical_nhl_paths(root):
        print("no JSON files under data/calibration/nhl")
        return 1
    report = search_nhl_strength(root=root, three_way=three_way)
    print(format_nhl_strength_report(report), end="")
    write_report(report, root / "artifacts" / "tuning_nhl_strength.json")
    grids = report["grids"]
    if not isinstance(grids, list) or not grids or not isinstance(grids[0], dict):
        return 1
    candidates = grids[0]["candidates"]
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        return 1
    overall = _ranking_block(candidates[0])["overall"]
    return 0 if isinstance(overall, dict) and overall["n"] else 1


def _search_one_strength(
    name: str,
    values: tuple[float, ...] | list[float],
    *,
    historical_files: list[Path],
    parts: dict[str, object] | None,
    root: Path,
    production: dict[str, float],
) -> dict[str, object]:
    train_files, validation_files, holdout_files = _split_paths(historical_files, parts)
    candidates: list[dict[str, object]] = []
    for value in values:
        settings = dict(production)
        settings[name] = float(value)
        with temporary_hockey_strength(**settings):
            row: dict[str, object] = {
                "coefficient": name,
                "value": float(value),
                **settings,
            }
            if parts is None:
                row["historical"] = _sport_slice(
                    build_report(train_files, root=root), "nhl"
                )
            else:
                row["train"] = _sport_slice(build_report(train_files, root=root), "nhl")
                row["validation"] = _sport_slice(
                    build_report(validation_files, root=root), "nhl"
                )
                row["holdout"] = _sport_slice(
                    build_report(holdout_files, root=root), "nhl"
                )
        candidates.append(row)
    ranked = sorted(
        candidates,
        key=lambda candidate: _strength_brier_key(candidate, production[name]),
    )
    for rank, candidate in enumerate(ranked, start=1):
        candidate["rank"] = rank
    by_value = {float(candidate["value"]): candidate for candidate in candidates}
    ordered = [by_value[float(value)] for value in values]
    ordered_briers = [_overall_brier(candidate) for candidate in ordered]
    shape = _grid_shape([float(value) for value in values], ordered_briers)
    best = ranked[0]
    best_brier = _overall_brier(best)
    tied = sum(
        1
        for candidate in ranked
        if _briers_tie(_overall_brier(candidate), best_brier)
    )
    return {
        "coefficient": name,
        "production": production[name],
        "grid": [float(value) for value in values],
        "held_at_production": {
            key: held for key, held in production.items() if key != name
        },
        "shape": shape,
        "tied_for_best": tied,
        "train_brier_spread": _brier_spread(ordered_briers),
        "best_train_brier": _strength_reading(best, shape, tied),
        "candidates": ranked,
    }


def _strength_brier_key(
    candidate: dict[str, object], production: float
) -> tuple[float, float, float]:
    value = float(candidate["value"])
    brier = _overall_brier(candidate)
    if not isinstance(brier, (int, float)):
        return (math.inf, abs(value - production), value)
    return (float(brier), abs(value - production), value)


def _overall_brier(candidate: dict[str, object]) -> float | None:
    block = _ranking_block(candidate)
    overall = block["overall"]
    if not isinstance(overall, dict):
        return None
    brier = overall.get("brier")
    if isinstance(brier, bool) or not isinstance(brier, (int, float)):
        return None
    return float(brier)


def _briers_tie(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return abs(left - right) <= _STRENGTH_TIE


def _brier_spread(briers: list[float | None]) -> float | None:
    numeric = [brier for brier in briers if isinstance(brier, (int, float))]
    if len(numeric) != len(briers) or not numeric:
        return None
    return max(numeric) - min(numeric)


def _grid_shape(values: list[float], briers: list[float | None]) -> str:
    """Name whether the best train Brier is interior, an edge, or flat."""
    if not values or any(brier is None for brier in briers):
        return "unavailable"
    numeric = [float(brier) for brier in briers if isinstance(brier, (int, float))]
    best = min(numeric)
    if max(numeric) - best <= _STRENGTH_TIE:
        return "flat"
    winners = [
        value
        for value, brier in zip(values, numeric)
        if abs(brier - best) <= _STRENGTH_TIE
    ]
    endpoints = {values[0], values[-1]}
    if all(value in endpoints for value in winners):
        return "edge"
    if len(winners) == 1:
        return "interior_minimum"
    return "plateau"


def _strength_reading(
    best: dict[str, object], shape: str, tied: int
) -> dict[str, object]:
    reading: dict[str, object] = {
        "value": best["value"],
        "shape": shape,
        "tied_for_best": tied,
    }
    for key in ("historical", "train", "validation", "holdout"):
        if key not in best:
            continue
        block = best[key]
        if not isinstance(block, dict):
            continue
        overall = block["overall"]
        late = block["<5 min"]
        if not isinstance(overall, dict) or not isinstance(late, dict):
            continue
        reading[key] = {
            "n": overall["n"],
            "brier": overall["brier"],
            "log_loss": overall["log_loss"],
            "<5 min brier": late["brier"],
        }
    return reading


def _require_strength_grids(
    grids: tuple[tuple[str, tuple[float, ...]], ...],
) -> None:
    allowed = set(nhl_strength_settings())
    if not grids:
        raise ValueError("strength search needs at least one grid")
    for name, values in grids:
        if name not in allowed:
            raise ValueError(f"unknown strength coefficient {name!r}")
        if not values:
            raise ValueError(f"{name} grid is empty")


def _require_strength_formula_matches_production() -> None:
    import ms_win_prob.hockey.strength as strength_module

    for state in _strength_probe_states():
        got = strength_rate_multipliers(state)
        expected = strength_module.rate_multipliers(state)
        if got != expected:
            raise RuntimeError(
                "strength override formula drifted from strength.py for "
                f"strength={state.strength!r} extra_attacker={state.extra_attacker}: "
                f"{got} != {expected}"
            )


def _strength_probe_states() -> list[GameState]:
    """States that exercise each branch of ``rate_multipliers``."""
    base = {
        "sport": "nhl",
        "game_id": "strength-probe",
        "home": "H",
        "away": "A",
        "home_score": 1,
        "away_score": 1,
        "period": 3,
        "seconds_remaining_period": 600,
        "seconds_remaining_total": 600,
        "status": "live",
        "source": "tune",
        "as_of": datetime(2026, 10, 17, tzinfo=timezone.utc),
        "prior_home": 0.5,
    }
    cases = (
        (None, None),
        ("", None),
        ("5v5", False),
        ("5v4", False),
        ("5v3", False),
        ("4v5", False),
        ("3v5", False),
        ("3v3", False),
        ("4v4", False),
        ("6v5", False),
        ("6v5", True),
        ("5v6", True),
        ("6v4", True),
        ("4v6", True),
        ("6v6", True),
        ("3v4", False),
        ("4v3", True),
    )
    return [
        GameState(**base, strength=strength, extra_attacker=extra)
        for strength, extra in cases
    ]


def _hockey_source_snapshot() -> dict[str, object]:
    import ms_win_prob.hockey.config as hockey_config
    import ms_win_prob.hockey.model as hockey_model
    import ms_win_prob.hockey.strength as strength_module

    return {
        "rate_multipliers": strength_module.rate_multipliers,
        "model_rate_multipliers": hockey_model.rate_multipliers,
        "source": Path(strength_module.__file__).read_bytes(),
        "config_source": Path(hockey_config.__file__).read_bytes(),
        "model_source": Path(hockey_model.__file__).read_bytes(),
        "NHL_CONFIG": hockey_config.NHL_CONFIG,
        "NHL_REGULAR_CONFIG": hockey_config.NHL_REGULAR_CONFIG,
        "NCAAH_CONFIG": hockey_config.NCAAH_CONFIG,
        "mean": hockey_config.NHL_CONFIG.mean_score_per_team,
        "dispersion": hockey_config.NHL_CONFIG.score_dispersion,
        "margin_sd": hockey_config.NHL_CONFIG.margin_sd,
    }


def _require_hockey_sources_unchanged(before: dict[str, object]) -> None:
    after = _hockey_source_snapshot()
    if after != before:
        raise RuntimeError("hockey strength source changed during the search")


def _strength_coverage(paths: list[Path]) -> dict[str, object]:
    """Count strength and empty-net fields on the files about to be scored."""
    snapshots = 0
    missing_strength = 0
    missing_extra = 0
    extra_true = 0
    labels: dict[str, int] = {}
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        rows = payload if isinstance(payload, list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            snapshots += 1
            strength = row.get("strength")
            if strength in (None, ""):
                missing_strength += 1
                label = "<missing>"
            else:
                label = str(strength)
            labels[label] = labels.get(label, 0) + 1
            extra = row.get("extra_attacker")
            if extra is None:
                missing_extra += 1
            elif extra is True:
                extra_true += 1
    return {
        "snapshots": snapshots,
        "strength_missing": missing_strength,
        "extra_attacker_missing": missing_extra,
        "extra_attacker_true": extra_true,
        "strength_counts": labels,
    }


def _coverage_line(coverage: object) -> str:
    if not isinstance(coverage, dict):
        return "Strength coverage: unavailable."
    return (
        "Strength coverage: "
        f"{coverage['snapshots']} snapshots, "
        f"{coverage['strength_missing']} missing strength, "
        f"{coverage['extra_attacker_missing']} missing extra_attacker, "
        f"{coverage['extra_attacker_true']} empty-net snapshots."
    )


def _split_count_line(split: dict[str, object]) -> str:
    train_ids = split["train_game_ids"]
    validation_ids = split["validation_game_ids"]
    holdout_ids = split["holdout_game_ids"]
    train_n = len(train_ids) if isinstance(train_ids, list) else 0
    validation_n = len(validation_ids) if isinstance(validation_ids, list) else 0
    holdout_n = len(holdout_ids) if isinstance(holdout_ids, list) else 0
    return (
        f"Train games: {train_n}. Validation games: {validation_n}. "
        f"Hold-out games: {holdout_n}."
    )


def _format_strength_grid(grid: dict[str, object]) -> list[str]:
    name = str(grid["coefficient"])
    if "train" in _grid_candidates(grid)[0]:
        headers = (
            "rank",
            name,
            "train_n",
            "train_brier",
            "train_log_loss",
            "train_<5_brier",
            "validation_n",
            "validation_brier",
            "validation_log_loss",
            "validation_<5_brier",
            "holdout_n",
            "holdout_brier",
            "holdout_log_loss",
            "holdout_<5_brier",
        )
        rows = [
            _nhl_three_way_line(candidate) for candidate in _grid_candidates(grid)
        ]
    else:
        headers = (
            "rank",
            name,
            "n",
            "brier",
            "log_loss",
            "<5_brier",
        )
        rows = [_nhl_historical_line(candidate) for candidate in _grid_candidates(grid)]
    return [
        f"Coefficient: {name}. Production value: {_num(grid['production'])}.",
        _table(headers, rows),
        _shape_sentence(grid),
    ]


def _grid_candidates(grid: dict[str, object]) -> list[dict[str, object]]:
    rows = grid["candidates"]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise TypeError("candidates must be a list of objects")
    return rows


def _metric_cells(block: object) -> list[str]:
    if not isinstance(block, dict):
        raise TypeError("metric block must be an object")
    overall = block["overall"]
    late = block["<5 min"]
    if not isinstance(overall, dict) or not isinstance(late, dict):
        raise TypeError("overall and <5 min must be objects")
    return [
        _num(overall["n"]),
        _num(overall["brier"]),
        _num(overall["log_loss"]),
        _num(late["brier"]),
    ]


def _nhl_three_way_line(candidate: dict[str, object]) -> list[str]:
    return [
        str(candidate["rank"]),
        _num(candidate["value"]),
        *_metric_cells(candidate["train"]),
        *_metric_cells(candidate["validation"]),
        *_metric_cells(candidate["holdout"]),
    ]


def _nhl_historical_line(candidate: dict[str, object]) -> list[str]:
    return [
        str(candidate["rank"]),
        _num(candidate["value"]),
        *_metric_cells(candidate["historical"]),
    ]


def _shape_sentence(grid: dict[str, object]) -> str:
    reading = grid["best_train_brier"]
    if not isinstance(reading, dict):
        raise TypeError("best_train_brier must be an object")
    shape = str(grid["shape"])
    value = _num(reading["value"])
    tied = grid["tied_for_best"]
    where = _reading_performance(reading)
    if shape == "flat":
        kind = (
            f"Lowest train Brier is {value}, shared by {tied} grid points. "
            "The grid is flat, so this is neither an interior minimum nor an edge value."
        )
    elif shape == "interior_minimum":
        kind = (
            f"Lowest train Brier is {value}, an interior minimum. "
            "It is strictly inside the grid and lower than the other grid points."
        )
    elif shape == "edge":
        kind = (
            f"Lowest train Brier is {value}, an edge value. "
            "It sits at an end of the grid."
        )
    elif shape == "plateau":
        kind = (
            f"Lowest train Brier is {value}, shared by {tied} grid points "
            "including an interior value. Not a unique interior minimum."
        )
    else:
        kind = f"Lowest train Brier is {value}. Shape: {shape}."
    return kind + " " + where


def _reading_performance(reading: dict[str, object]) -> str:
    pieces = []
    for key, label in (
        ("train", "Train"),
        ("validation", "Validation"),
        ("holdout", "Hold-out"),
        ("historical", "Historical"),
    ):
        block = reading.get(key)
        if not isinstance(block, dict):
            continue
        pieces.append(
            f"{label}: n={_num(block['n'])}, brier={_num(block['brier'])}, "
            f"log_loss={_num(block['log_loss'])}, "
            f"<5 min brier={_num(block['<5 min brier'])}."
        )
    return " ".join(pieces)


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
    paths: list[Path], *, three_way: bool = True
) -> dict[str, object]:
    """Split historical files into train, validation, and hold-out.

    Game ids are sorted as text. In each repeating group of five,
    1-based positions 1, 2, and 3 are train, position 4 is validation,
    and position 5 is hold-out. Snapshots are not split apart from their game.
    """
    if not three_way:
        raise ValueError("only the three-way split is supported")
    grouped = [(path, _game_ids_in_file(path)) for path in paths]
    distinct = sorted({game_id for _path, ids in grouped for game_id in ids})
    holdout_ids = {
        game_id
        for index, game_id in enumerate(distinct)
        if (index + 1) % HOLDOUT_EVERY == 0
    }
    validation_ids = {
        game_id
        for index, game_id in enumerate(distinct)
        if (index + 1) % HOLDOUT_EVERY == 4
    }
    train_paths: list[Path] = []
    validation_paths: list[Path] = []
    holdout_paths: list[Path] = []
    for path, ids in grouped:
        if ids and all(game_id in holdout_ids for game_id in ids):
            holdout_paths.append(path)
        elif ids and all(game_id in validation_ids for game_id in ids):
            validation_paths.append(path)
        else:
            train_paths.append(path)
    return {
        "method": THREE_WAY_METHOD,
        "holdout_every": HOLDOUT_EVERY,
        "train_game_ids": [
            game_id
            for game_id in distinct
            if game_id not in holdout_ids and game_id not in validation_ids
        ],
        "validation_game_ids": [
            game_id for game_id in distinct if game_id in validation_ids
        ],
        "holdout_game_ids": [game_id for game_id in distinct if game_id in holdout_ids],
        "train_paths": train_paths,
        "validation_paths": validation_paths,
        "holdout_paths": holdout_paths,
    }


def _requested_split(
    paths: list[Path], *, three_way: bool
) -> dict[str, object] | None:
    if not three_way:
        return None
    return split_historical_files(paths, three_way=True)


def _split_paths(
    historical_files: list[Path], parts: dict[str, object] | None
) -> tuple[list[Path], list[Path], list[Path]]:
    if parts is None:
        return historical_files, [], []
    return (
        _path_list(parts["train_paths"]),
        _path_list(parts["validation_paths"]),
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
    return {
        "active": True,
        "method": parts["method"],
        "holdout_every": parts["holdout_every"],
        "train_game_ids": parts["train_game_ids"],
        "validation_game_ids": parts["validation_game_ids"],
        "holdout_game_ids": parts["holdout_game_ids"],
        "train_inputs": [_display(path, root) for path in _path_list(parts["train_paths"])],
        "validation_inputs": [
            _display(path, root) for path in _path_list(parts["validation_paths"])
        ],
        "holdout_inputs": [_display(path, root) for path in _path_list(parts["holdout_paths"])],
    }


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
    validation_ids = split["validation_game_ids"]
    holdout_ids = split["holdout_game_ids"]
    train_n = len(train_ids) if isinstance(train_ids, list) else 0
    validation_n = len(validation_ids) if isinstance(validation_ids, list) else 0
    holdout_n = len(holdout_ids) if isinstance(holdout_ids, list) else 0
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
                for candidate in _candidates(report)
            ],
        ),
    ]
    return "\n".join(lines) + "\n"


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


def _parse_nfl_args(argv: list[str]) -> tuple[float | None, bool, str | None]:
    """Parse ``tune-nfl`` flags. No flags leaves the unsplit grid."""
    mean: float | None = None
    three_way = False
    index = 0
    usage = (
        "usage: python -m live_win_prob tune-nfl "
        "[--three-way] [--mean MEAN_SCORE_PER_TEAM]"
    )
    while index < len(argv):
        arg = argv[index]
        if arg == "--three-way":
            three_way = True
            index += 1
            continue
        if arg == "--mean" and index + 1 < len(argv):
            try:
                mean = float(argv[index + 1])
            except ValueError:
                return None, False, "mean_score_per_team must be a number"
            if mean <= 0:
                return None, False, "mean_score_per_team must be > 0"
            index += 2
            continue
        return None, False, usage
    return mean, three_way, None
