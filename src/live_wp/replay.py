"""Load a JSON replay of GameState snapshots and format lines for the CLI.

Optional football fields (down, distance, yard line, possession, timeouts)
are not read. The win-probability model does not use them.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping

from mswp import DEFAULT_PRIOR_HOME, GameState, NFL_CONFIG, compute_wp

_REQUIRED = (
    "sport",
    "game_id",
    "home",
    "away",
    "home_score",
    "away_score",
    "period",
    "seconds_remaining_period",
    "seconds_remaining_total",
    "status",
    "source",
    "as_of",
)


def load_replay(path: Path | str) -> list[GameState]:
    """Read a JSON list of snapshots, in file order."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("replay file must be a non-empty JSON list")
    return [game_state_from_row(row) for row in payload]


def _as_int(row: Mapping[str, object], name: str) -> int:
    value = row[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    return value


def game_state_from_row(row: Mapping[str, object]) -> GameState:
    """Map one feed row to a GameState. Football detail fields are ignored."""
    if not isinstance(row, Mapping):
        raise TypeError("replay row must be a JSON object")
    missing = [name for name in _REQUIRED if name not in row]
    if missing:
        raise ValueError(f"replay row missing {', '.join(missing)}")
    as_of = row["as_of"]
    if not isinstance(as_of, str):
        raise TypeError("as_of must be an ISO-8601 string")
    prior = row["prior_home"] if "prior_home" in row else DEFAULT_PRIOR_HOME
    return GameState(
        sport=str(row["sport"]),
        game_id=str(row["game_id"]),
        home=str(row["home"]),
        away=str(row["away"]),
        home_score=_as_int(row, "home_score"),
        away_score=_as_int(row, "away_score"),
        period=_as_int(row, "period"),
        seconds_remaining_period=_as_int(row, "seconds_remaining_period"),
        seconds_remaining_total=_as_int(row, "seconds_remaining_total"),
        status=str(row["status"]),  # type: ignore[arg-type]
        source=str(row["source"]),
        as_of=datetime.fromisoformat(as_of.replace("Z", "+00:00")),
        prior_home=float(prior),  # type: ignore[arg-type]
    )


def format_clock(state: GameState) -> str:
    """Period clock label. A final snapshot is labeled FINAL."""
    if state.status == "final":
        return "FINAL"
    minutes, seconds = divmod(state.seconds_remaining_period, 60)
    if state.period <= 4:
        label = f"Q{state.period}"
    else:
        label = f"OT{state.period - 4}"
    return f"{label} {minutes}:{seconds:02d}"


def format_line(state: GameState, wp: float) -> str:
    """One CLI line: time, score, home win probability."""
    score = f"{state.home} {state.home_score}, {state.away} {state.away_score}"
    return f"{format_clock(state)} | {score} | {wp:.3f}"


def elapsed_game_seconds(state: GameState) -> int:
    """Seconds from kickoff, read from the game clock on the snapshot."""
    if state.period <= NFL_CONFIG.regulation_periods:
        remaining = min(state.seconds_remaining_total, NFL_CONFIG.regulation_seconds)
        return NFL_CONFIG.regulation_seconds - remaining
    remaining_ot = min(state.seconds_remaining_total, NFL_CONFIG.ot_period_seconds)
    return NFL_CONFIG.regulation_seconds + (
        NFL_CONFIG.ot_period_seconds - remaining_ot
    )


def render_widget_script(states: list[GameState]) -> str:
    """JavaScript assignment of the replay, including precomputed home WP.

    The page displays ``wp``. It does not carry a second football model.
    """
    frames = []
    for state in states:
        wp = compute_wp(state, state.prior_home, NFL_CONFIG)
        frames.append(
            {
                "clock": format_clock(state),
                "wp": wp,
                "home": state.home,
                "away": state.away,
                "home_score": state.home_score,
                "away_score": state.away_score,
                "status": state.status,
                "period": state.period,
                "seconds_remaining_period": state.seconds_remaining_period,
                "seconds_remaining_total": state.seconds_remaining_total,
                "prior_home": state.prior_home,
                "game_id": state.game_id,
                "elapsed_seconds": elapsed_game_seconds(state),
            }
        )
    body = json.dumps(frames, indent=2)
    return (
        "// Precomputed by compute_wp from examples/nfl_sample.json.\n"
        "// The widget displays these values and does not run a second model.\n"
        f"window.NFL_REPLAY = {body};\n"
    )
