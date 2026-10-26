"""Smoke calibration on the saved fixtures.

Replays snapshots and scores the home win probability ``compute_win_prob`` already
returns. It does not fit or edit margin_sd, possession points, or strength
multipliers. The fixture count is too small for that, and this is not a
historical backtest.

Replay lists are read as saved. ESPN objects go through the same path as
``python -m live_win_prob ingest-espn``, at scoring density. A file that path
refuses is skipped and recorded. This module does not fetch.

Optional historical files live under ``data/calibration/{sport}/``
(``nfl``, ``nhl``, ``nba``, ``ncaaf``, ``ncaah``, ``ncaab``), including
nested directories. Those files are for historical calibration only.
A missing or empty directory leaves the smoke-test inputs unchanged.

``python -m live_win_prob calibrate --nfl-split`` scores only
``data/calibration/nfl`` at the production NFL config. Train, validation,
and hold-out use the same three-way game-id split as ``tune-nfl --three-way``.
``python -m live_win_prob calibrate --split SPORT`` is that same report for
``nfl``, ``nhl``, ``nba``, ``ncaaf``, ``ncaah``, or ``ncaab``.
``--nfl-split`` remains the NFL-only form.
"""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Callable
from pathlib import Path

from ms_win_prob import compute_win_prob
from ms_win_prob.config import SportConfig
from ms_win_prob.state import GameState

from live_win_prob.feeds import states_from_ingest
from live_win_prob.replay import config_for_state, load_replay

# Natural-log loss only. Brier and the mean keep the raw probability,
# including a decided 0 or 1.
LOG_LOSS_FLOOR = 1e-6
LOG_LOSS_CEIL = 1.0 - 1e-6

NOTE = (
    "Smoke table on the fixtures we have, not a historical backtest. "
    "The fixture count is too small to retune margin_sd, possession points, "
    "or strength multipliers."
)

NFL_SPLIT_NOTE = (
    "Production NFL_CONFIG on data/calibration/nfl. "
    "Train, validation, and hold-out use the same three-way game_id split "
    "as tune-nfl --three-way. SportConfig was not modified."
)

# Same default as ``ingest-espn``. Replay files are not thinned to this density.
ESPN_DENSITY = "scoring"

BUCKETS: tuple[str, ...] = (
    "pregame",
    ">15 min",
    "5-15 min",
    "1-5 min",
    "<1 min",
    "overtime",
)

BUCKET_RULES: dict[str, str] = {
    "pregame": "status is pre",
    ">15 min": "regulation with more than 15:00 remaining",
    "5-15 min": "regulation with 5:00 through 15:00 remaining",
    "1-5 min": "regulation with 1:00 through 4:59 remaining",
    "<1 min": "regulation with under 1:00 remaining",
    "overtime": "period after regulation",
}

# Listed ESPN fixtures. examples/*.json is added beside these.
# Historical JSON, when present, is data/calibration/{sport}/ (see historical_paths).
ESPN_FIXTURES: tuple[str, ...] = (
    "tests/fixtures/espn_nfl_summary_snippet.json",
    "tests/fixtures/espn_nhl_401442762_summary.json",
    "tests/fixtures/espn_nba_401547684_summary.json",
    "tests/fixtures/espn_ncaab_401638608_summary.json",
    "tests/fixtures/espn_ncaaf_summary_snippet.json",
)

_SPORT_ORDER = ("nfl", "nhl", "nba", "ncaaf", "ncaah", "ncaab")
# College calibration directories are treated the same as the pro ones:
# moneyline-only filtering and the three-way game-id split.
_PRO_SEASON_SPORTS = _SPORT_ORDER
# espn_win_probability is the college fallback from the collector. It is
# ESPN's model at the first play, not a market close, and is scored like
# moneyline. Pro directories do not use this label.
_SEASON_PRIOR_SOURCES = frozenset({"moneyline", "espn_win_probability"})

_METRIC_HEADERS = (
    "n",
    "mean_win_prob",
    "home_win_rate",
    "brier",
    "log_loss",
)


def repo_root() -> Path:
    """Directory that contains ``examples/`` and ``src/``."""
    return Path(__file__).resolve().parents[2]


def default_paths(root: Path | None = None) -> list[Path]:
    """Smoke-test inputs, then any historical JSON under ``data/calibration/``.

    The smoke-test list is every ``examples/*.json`` replay, then the listed
    ESPN fixtures. Historical files are appended only when that directory
    contains JSON. A missing or empty directory leaves the list unchanged.
    """
    root = repo_root() if root is None else root
    examples = sorted((root / "examples").glob("*.json"))
    fixtures = [root / relative for relative in ESPN_FIXTURES]
    return [*examples, *fixtures, *historical_paths(root)]


def historical_paths(root: Path | None = None) -> list[Path]:
    """JSON files for historical calibration only.

    Expected layout, optional::

        data/calibration/{sport}/...

    ``sport`` is ``nfl``, ``nhl``, ``nba``, ``ncaaf``, ``ncaah``, or
    ``ncaab``. Nested directories under ``data/calibration/`` are included.
    JSON lists are loaded with ``load_replay`` and labeled ``replay``.
    JSON objects go through ``states_from_ingest`` at scoring density and
    are labeled ``ingest-espn`` (basketball summaries use that same ingest
    path). A missing directory, or one with no JSON files, returns nothing.
    """
    root = repo_root() if root is None else root
    base = root / "data" / "calibration"
    if not base.is_dir():
        return []
    return sorted(
        (path for path in base.rglob("*.json") if path.is_file()),
        key=lambda path: _historical_sort_key(base, path),
    )


def moneyline_snapshots(directory: Path | str) -> list[GameState]:
    """Load a calibration directory and keep moneyline snapshots.

    ``directory`` is a folder such as ``data/calibration`` or
    ``data/calibration/nfl``. Nested JSON is included, in the same order
    as ``historical_paths``. Replay lists go through ``load_replay``.
    ESPN objects go through ``states_from_ingest`` at scoring density.
    A file that path refuses is skipped. A snapshot is kept only when
    ``prior_source`` is exactly ``moneyline``. A missing ``prior_source``
    is loaded as ``default`` and left out. The files on disk are not
    changed. A missing directory, or one with no JSON, returns nothing.
    """
    base = Path(directory)
    if not base.is_dir():
        return []
    kept: list[GameState] = []
    for path in sorted(
        (path for path in base.rglob("*.json") if path.is_file()),
        key=lambda path: _historical_sort_key(base, path),
    ):
        loaded, _source, reason = _load_path(path)
        if reason is not None:
            continue
        kept.extend(state for state in loaded if state.prior_source == "moneyline")
    return kept


def pro_season_sport(path: Path, root: Path) -> str | None:
    """Season sport when ``path`` is under ``data/calibration/{sport}/``.

    ``sport`` is ``nfl``, ``nhl``, ``nba``, ``ncaaf``, ``ncaah``, or
    ``ncaab``. Examples and fixtures outside ``data/calibration`` return
    nothing.
    """
    base = (root / "data" / "calibration").resolve()
    try:
        relative = path.resolve().relative_to(base)
    except ValueError:
        return None
    sport = relative.parts[0] if relative.parts else ""
    if sport in _PRO_SEASON_SPORTS:
        return sport
    return None


def file_has_moneyline_prior(path: Path) -> bool:
    """True when a calibration file has a snapshot labeled ``moneyline``.

    Replay lists are checked on the stored ``prior_source``. A missing
    field is not moneyline. ESPN objects use the same ingest path as
    scoring. The file is not written.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if isinstance(payload, list):
        return any(
            isinstance(row, dict) and row.get("prior_source") in _SEASON_PRIOR_SOURCES
            for row in payload
        )
    loaded, _source, reason = _load_path(path)
    return reason is None and any(
        state.prior_source in _SEASON_PRIOR_SOURCES for state in loaded
    )


def _historical_sort_key(base: Path, path: Path) -> tuple[int, str]:
    """Known sports first, in table order, then the relative path."""
    relative = path.relative_to(base).as_posix()
    sport = relative.split("/", 1)[0]
    try:
        rank = _SPORT_ORDER.index(sport)
    except ValueError:
        rank = len(_SPORT_ORDER)
    return rank, relative


def time_bucket(state: GameState, config: SportConfig) -> str:
    """Name the snapshot's calibration bucket.

    Pregame wins over the clock. Overtime wins over the clock after that.
    Regulation uses ``seconds_remaining_total``, the time left in the game.
    """
    if state.status == "pre":
        return "pregame"
    if state.period > config.regulation_periods:
        return "overtime"
    remaining = state.seconds_remaining_total
    if remaining > 15 * 60:
        return ">15 min"
    if remaining >= 5 * 60:
        return "5-15 min"
    if remaining >= 60:
        return "1-5 min"
    return "<1 min"


def home_result(state: GameState) -> float:
    """1 if this score is a home win, 0 if away won, 0.5 if the score is tied."""
    if state.home_score > state.away_score:
        return 1.0
    if state.home_score < state.away_score:
        return 0.0
    return 0.5


def summarize(pairs: list[tuple[float, float]]) -> dict[str, object]:
    """n, mean predicted home win probability, home win rate, Brier, and log loss.

    ``pairs`` are ``(predicted, outcome)``. Log loss clips each prediction
    to ``[1e-6, 1-1e-6]``. The mean and Brier use the unclipped value.
    """
    n = len(pairs)
    if n == 0:
        return {
            "n": 0,
            "mean_predicted_home_win_prob": None,
            "home_win_rate": None,
            "brier": None,
            "log_loss": None,
        }
    mean_predicted = sum(predicted for predicted, _outcome in pairs) / n
    home_win_rate = sum(outcome for _predicted, outcome in pairs) / n
    brier = sum((predicted - outcome) ** 2 for predicted, outcome in pairs) / n
    log_loss = 0.0
    for predicted, outcome in pairs:
        clipped = _clip_for_log_loss(predicted)
        log_loss += -(
            outcome * math.log(clipped) + (1.0 - outcome) * math.log(1.0 - clipped)
        )
    return {
        "n": n,
        "mean_predicted_home_win_prob": mean_predicted,
        "home_win_rate": home_win_rate,
        "brier": brier,
        "log_loss": log_loss / n,
    }


def build_report(
    paths: list[Path],
    *,
    root: Path | None = None,
    config_for: Callable[[GameState], SportConfig] | None = None,
) -> dict[str, object]:
    """Score each saved game. A refused file is listed under ``skipped``.

    ``config_for`` replaces ``config_for_state`` for this call only. The
    default still reads the production configs. A caller that passes a
    copy must not write that copy back to a config module.

    A file under ``data/calibration/{nfl,nhl,nba,ncaaf,ncaah,ncaab}``
    contributes only snapshots whose ``prior_source`` is ``moneyline`` or
    ``espn_win_probability``. Files outside those directories are scored
    as saved.
    """
    root = repo_root() if root is None else root
    chooser = config_for_state if config_for is None else config_for
    games: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    observations: list[tuple[str, str, float, float]] = []
    for path in paths:
        label = _display_path(path, root)
        loaded, source, reason = _load_path(path)
        if reason is not None:
            skipped.append({"path": label, "reason": reason})
            continue
        if pro_season_sport(path, root) is not None:
            loaded = [
                state
                for state in loaded
                if state.prior_source in _SEASON_PRIOR_SOURCES
            ]
            if not loaded:
                continue
        _score_file(label, source, loaded, games, skipped, observations, chooser)
    return _assemble(paths, root, games, skipped, observations)


def format_report(report: dict[str, object]) -> str:
    """Text table for stdout."""
    lines = [
        str(report["note"]),
        "",
        "Each snapshot is scored against its game's final snapshot "
        "(1 home win, 0 away win, 0.5 tie). "
        "An example replay and an ESPN ingest of the same game are both counted. "
        "mean_win_prob is the mean predicted home win probability. "
        "Log loss clips a prediction to [1e-6, 1-1e-6]. "
        "The mean and Brier do not.",
        "Regulation buckets are >15:00, 5:00 through 15:00, "
        "1:00 through 4:59, and under 1:00. Overtime is its own bucket.",
        "",
        "Per sport",
        *_table(
            ("sport", *_METRIC_HEADERS),
            [
                _metric_line((str(row["sport"]),), row)
                for row in _report_rows(report, "by_sport")
            ]
            + [_metric_line(("all",), report["overall"])],
        ),
        "",
        "Per time bucket",
        *_table(
            ("bucket", *_METRIC_HEADERS),
            [
                _metric_line((str(row["bucket"]),), row)
                for row in _report_rows(report, "by_bucket")
            ],
        ),
        "",
        "Per sport and time bucket",
        *_table(
            ("sport", "bucket", *_METRIC_HEADERS),
            [
                _metric_line((str(row["sport"]), str(row["bucket"])), row)
                for row in _report_rows(report, "by_sport_and_bucket")
            ],
        ),
        "",
        "Skipped",
    ]
    skipped = report["skipped"]
    if not skipped:
        lines.append("(none)")
    else:
        lines.extend(
            _table(
                ("path", "reason"),
                [
                    [str(item["path"]), str(item["reason"])]
                    for item in _report_rows(report, "skipped")
                ],
            )
        )
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, object], dest: Path) -> None:
    """Write the JSON report with LF newlines."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2) + "\n"
    dest.write_text(text, encoding="utf-8", newline="\n")


def split_section(report: dict[str, object]) -> dict[str, object]:
    """One scored path list: overall metrics, time buckets, games, and skips.

    Metric keys match ``summarize``: ``n``, ``mean_predicted_home_win_prob``,
    ``home_win_rate``, ``brier``, and ``log_loss``.
    """
    return {
        "inputs": report["inputs"],
        "games": report["games"],
        "skipped": report["skipped"],
        "overall": report["overall"],
        "by_bucket": [
            {
                "bucket": row["bucket"],
                "n": row["n"],
                "mean_predicted_home_win_prob": row["mean_predicted_home_win_prob"],
                "home_win_rate": row["home_win_rate"],
                "brier": row["brier"],
                "log_loss": row["log_loss"],
            }
            for row in _report_rows(report, "by_bucket")
        ],
    }


def format_nfl_split_report(report: dict[str, object]) -> str:
    """Text table for the production NFL train, validation, and hold-out report."""
    production = report["production"]
    split = report["split"]
    if not isinstance(production, dict) or not isinstance(split, dict):
        raise TypeError("production and split must be objects")
    train_ids = split["train_game_ids"]
    validation_ids = split["validation_game_ids"]
    holdout_ids = split["holdout_game_ids"]
    lines = [
        str(report["note"]),
        "",
        (
            f"score_dispersion {production['score_dispersion']}  "
            f"mean_score_per_team {production['mean_score_per_team']}  "
            f"margin_sd {production['margin_sd']}"
        ),
        str(split["method"]),
        (
            f"Train games: {len(train_ids) if isinstance(train_ids, list) else 0}. "
            f"Validation games: {len(validation_ids) if isinstance(validation_ids, list) else 0}. "
            f"Hold-out games: {len(holdout_ids) if isinstance(holdout_ids, list) else 0}."
        ),
        "",
    ]
    for key, title in (
        ("overall", "Overall"),
        ("train", "Train"),
        ("validation", "Validation"),
        ("holdout", "Hold-out"),
    ):
        section = report[key]
        if not isinstance(section, dict):
            raise TypeError(f"{key} must be an object")
        lines.append(title)
        lines.extend(
            _table(
                ("slice", *_METRIC_HEADERS),
                [_metric_line((title,), section["overall"])],
            )
        )
        lines.append("")
        lines.append(f"{title} by time bucket")
        lines.extend(
            _table(
                ("bucket", *_METRIC_HEADERS),
                [
                    _metric_line((str(row["bucket"]),), row)
                    for row in _report_rows(section, "by_bucket")
                ],
            )
        )
        skipped = section["skipped"]
        if isinstance(skipped, list) and skipped:
            lines.append("")
            lines.append(f"{title} skipped")
            lines.extend(
                _table(
                    ("path", "reason"),
                    [
                        [str(item["path"]), str(item["reason"])]
                        for item in skipped
                        if isinstance(item, dict)
                    ],
                )
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_calibrate(argv: list[str]) -> int:
    """Print the table and write ``artifacts/calibration.json``.

    With no paths, score ``examples/*.json`` and the listed ESPN fixtures.
    ``--nfl-split`` scores ``data/calibration/nfl`` at the production NFL
    config and writes ``artifacts/nfl_baseline_calibration.json`` instead.
    ``--split SPORT`` writes ``artifacts/{sport}_baseline_calibration.json``.
    Returns 0 when at least one snapshot was scored.
    """
    root = repo_root()
    if argv and argv[0] == "--nfl-split":
        if argv != ["--nfl-split"]:
            print(
                "usage: python -m live_win_prob calibrate "
                "[--nfl-split] [replay-or-espn.json ...]",
                file=sys.stderr,
            )
            return 2
        from live_win_prob.tune import report_nfl_production_split

        report = report_nfl_production_split(root)
        print(format_nfl_split_report(report), end="")
        write_report(report, root / "artifacts" / "nfl_baseline_calibration.json")
        section = report["overall"]
        overall = section["overall"] if isinstance(section, dict) else None
        return 0 if isinstance(overall, dict) and overall["n"] else 1
    if argv and argv[0] == "--split":
        if len(argv) != 2 or argv[1] not in _SPORT_ORDER:
            print(
                "usage: python -m live_win_prob calibrate "
                "--split nfl|nhl|nba|ncaaf|ncaah|ncaab",
                file=sys.stderr,
            )
            return 2
        sport = argv[1]
        if sport == "nfl":
            from live_win_prob.tune import report_nfl_production_split

            report = report_nfl_production_split(root)
            dest_name = "nfl_baseline_calibration.json"
        else:
            from live_win_prob.tune import report_production_split

            report = report_production_split(sport, root)
            dest_name = f"{sport}_baseline_calibration.json"
        print(format_nfl_split_report(report), end="")
        write_report(report, root / "artifacts" / dest_name)
        section = report["overall"]
        overall = section["overall"] if isinstance(section, dict) else None
        return 0 if isinstance(overall, dict) and overall["n"] else 1
    paths = [Path(arg) for arg in argv] if argv else default_paths(root)
    report = build_report(paths, root=root)
    print(format_report(report), end="")
    write_report(report, root / "artifacts" / "calibration.json")
    overall = report["overall"]
    return 0 if isinstance(overall, dict) and overall["n"] else 1


def _clip_for_log_loss(predicted: float) -> float:
    if predicted < LOG_LOSS_FLOOR:
        return LOG_LOSS_FLOOR
    if predicted > LOG_LOSS_CEIL:
        return LOG_LOSS_CEIL
    return predicted


def _load_path(path: Path) -> tuple[list[GameState], str, str | None]:
    """Return snapshots, a source label, and a skip reason when refused."""
    if not path.is_file():
        return [], "", "file not found"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [], "", str(exc)
    if isinstance(payload, list):
        try:
            return load_replay(path), "replay", None
        except (TypeError, ValueError) as exc:
            return [], "", str(exc)
    if isinstance(payload, dict):
        try:
            states = list(states_from_ingest(payload, density=ESPN_DENSITY))
        except (TypeError, ValueError) as exc:
            return [], "", str(exc)
        if not states:
            return [], "", "adapter returned no snapshots"
        return states, "ingest-espn", None
    return [], "", "file is not a replay list or an ESPN object"


def _score_file(
    label: str,
    source: str,
    states: list[GameState],
    games: list[dict[str, object]],
    skipped: list[dict[str, str]],
    observations: list[tuple[str, str, float, float]],
    config_for: Callable[[GameState], SportConfig],
) -> None:
    grouped: dict[str, list[GameState]] = {}
    order: list[str] = []
    for state in states:
        if state.game_id not in grouped:
            order.append(state.game_id)
            grouped[state.game_id] = []
        grouped[state.game_id].append(state)
    for game_id in order:
        group = grouped[game_id]
        # Neutral-site games are excluded from all calibration.
        to_score = [state for state in group if not state.neutral]
        if not to_score:
            continue
        finals = [state for state in group if state.status == "final"]
        if not finals:
            skipped.append(
                {"path": label, "reason": f"game {game_id} has no final snapshot"}
            )
            continue
        final = finals[-1]
        if any(state.sport != final.sport for state in group):
            skipped.append({"path": label, "reason": f"game {game_id} mixes sports"})
            continue
        outcome = home_result(final)
        scored: list[tuple[str, float]] = []
        try:
            for state in to_score:
                config = config_for(state)
                predicted = compute_win_prob(state, state.prior_home, config)
                scored.append((time_bucket(state, config), predicted))
        except (TypeError, ValueError, NotImplementedError) as exc:
            skipped.append({"path": label, "reason": f"game {game_id}: {exc}"})
            continue
        games.append(
            {
                "path": label,
                "source": source,
                "sport": final.sport,
                "game_id": game_id,
                "home": final.home,
                "away": final.away,
                "final_home_score": final.home_score,
                "final_away_score": final.away_score,
                "home_result": outcome,
                "n": len(scored),
            }
        )
        for bucket, predicted in scored:
            observations.append((final.sport, bucket, predicted, outcome))


def _assemble(
    paths: list[Path],
    root: Path,
    games: list[dict[str, object]],
    skipped: list[dict[str, str]],
    observations: list[tuple[str, str, float, float]],
) -> dict[str, object]:
    sports = _sports_in(observations)
    by_sport = [
        {"sport": sport, "bucket": "all", **_pairs(observations, sport=sport)}
        for sport in sports
    ]
    by_bucket = [
        {"sport": "all", "bucket": bucket, **_pairs(observations, bucket=bucket)}
        for bucket in BUCKETS
    ]
    by_sport_and_bucket = [
        {
            "sport": sport,
            "bucket": bucket,
            **_pairs(observations, sport=sport, bucket=bucket),
        }
        for sport in sports
        for bucket in BUCKETS
    ]
    return {
        "note": NOTE,
        "espn_density": ESPN_DENSITY,
        "buckets": [{"name": name, "rule": BUCKET_RULES[name]} for name in BUCKETS],
        "inputs": [_display_path(path, root) for path in paths],
        "games": games,
        "skipped": skipped,
        "by_sport": by_sport,
        "by_bucket": by_bucket,
        "by_sport_and_bucket": by_sport_and_bucket,
        "overall": _pairs(observations),
    }


def _pairs(
    observations: list[tuple[str, str, float, float]],
    *,
    sport: str | None = None,
    bucket: str | None = None,
) -> dict[str, object]:
    selected = [
        (predicted, outcome)
        for item_sport, item_bucket, predicted, outcome in observations
        if (sport is None or item_sport == sport)
        and (bucket is None or item_bucket == bucket)
    ]
    return summarize(selected)


def _sports_in(observations: list[tuple[str, str, float, float]]) -> list[str]:
    found = {sport for sport, _bucket, _predicted, _outcome in observations}
    known = [sport for sport in _SPORT_ORDER if sport in found]
    extra = sorted(found.difference(_SPORT_ORDER))
    return known + extra


def _display_path(path: Path, root: Path) -> str:
    absolute = path if path.is_absolute() else Path.cwd() / path
    try:
        return absolute.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return absolute.resolve().as_posix()


def _report_rows(report: dict[str, object], key: str) -> list[dict[str, object]]:
    rows = report[key]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise TypeError(f"{key} must be a list of objects")
    return rows


def _metric_line(labels: tuple[str, ...], summary: object) -> list[str]:
    if not isinstance(summary, dict):
        raise TypeError("metric row must be an object")
    return [
        *labels,
        _cell(summary["n"]),
        _cell(summary["mean_predicted_home_win_prob"]),
        _cell(summary["home_win_rate"]),
        _cell(summary["brier"]),
        _cell(summary["log_loss"]),
    ]


def _cell(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, int):
        return str(value)
    return f"{value:.6f}"


def _table(headers: tuple[str, ...], rows: list[list[str]]) -> list[str]:
    text_columns = len(headers) - len(_METRIC_HEADERS)
    if text_columns < 0:
        text_columns = len(headers)
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def render(cells: list[str] | tuple[str, ...]) -> str:
        parts: list[str] = []
        for index, cell in enumerate(cells):
            if index < text_columns:
                parts.append(cell.ljust(widths[index]))
            else:
                parts.append(cell.rjust(widths[index]))
        return "  ".join(parts).rstrip()

    lines = [render(list(headers)), render(["-" * width for width in widths])]
    lines.extend(render(row) for row in rows)
    return lines
