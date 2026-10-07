"""Rewrite a widget replay while the follow loop polls one game.

Each printed change is passed through ``render_widget_script``, which
recomputes win probability with the pack for that sport. College sports
are rejected. This module does not serve pages and does not open a socket
of its own. The follow command owns the feed request.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mswp import GameState

from live_wp.follow import (
    FollowError,
    UsageError,
    _flag_value,
    _parse_game,
    _parse_interval,
    _parse_sport,
    fetch_json,
    follow_game,
)
from live_wp.replay import render_widget_script

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "widget" / "live_replay.js"
_USAGE = (
    "usage: python -m live_wp live --game ESPN_EVENT_ID "
    "[--sport nfl|nhl|nba] [--interval 15] [--out widget/live_replay.js]"
)


@dataclass(frozen=True, slots=True)
class _Options:
    game: str
    interval: float
    sport: str
    out: Path


def parse_live_args(args: list[str]) -> _Options:
    """Read live flags. ``--game`` is required. The interval minimum is 5."""
    game: str | None = None
    interval: float | None = None
    sport: str | None = None
    out: Path | None = None
    index = 0
    tokens = list(args)
    while index < len(tokens):
        token = tokens[index]
        if token == "--game" or token.startswith("--game="):
            if game is not None:
                raise UsageError("--game was given twice")
            game, index = _flag_value("--game", index, tokens)
            continue
        if token == "--interval" or token.startswith("--interval="):
            if interval is not None:
                raise UsageError("--interval was given twice")
            raw, index = _flag_value("--interval", index, tokens)
            interval = _parse_interval(raw)
            continue
        if token == "--sport" or token.startswith("--sport="):
            if sport is not None:
                raise UsageError("--sport was given twice")
            raw, index = _flag_value("--sport", index, tokens)
            sport = _parse_sport(raw)
            continue
        if token == "--out" or token.startswith("--out="):
            if out is not None:
                raise UsageError("--out was given twice")
            raw, index = _flag_value("--out", index, tokens)
            if not raw.strip():
                raise UsageError("--out needs a value")
            out = Path(raw)
            continue
        raise UsageError(f"unrecognized argument: {token}")
    if game is None:
        raise UsageError("--game is required")
    selected = "nfl" if sport is None else sport
    return _Options(
        game=_parse_game(game, selected),
        interval=15.0 if interval is None else interval,
        sport=selected,
        out=DEFAULT_OUT if out is None else out,
    )


def run_live(
    args: list[str],
    *,
    fetch=None,
    sleep=None,
) -> int:
    """Poll one event and rewrite the replay script on each printed change.

    Ctrl+C stops the poll and leaves the last script in place.
    """
    try:
        options = parse_live_args(args)
    except UsageError as exc:
        print(exc, file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 2
    history: list[GameState] = []

    def on_change(state: GameState) -> None:
        history.append(state)
        _write_replay_script(options.out, history)

    if fetch is None:
        selected = options.sport

        def getter(url: str) -> Mapping[str, Any]:
            return fetch_json(url, sport=selected)

    else:
        getter = fetch
    try:
        return follow_game(
            options.game,
            interval=options.interval,
            sport=options.sport,
            fetch=getter,
            sleep=time.sleep if sleep is None else sleep,
            on_change=on_change,
        )
    except KeyboardInterrupt:
        return 0
    except (FollowError, ValueError, TypeError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1


def _write_replay_script(path: Path, states: list[GameState]) -> None:
    """Replace ``path`` with the live replay script.

    The sport binding (``window.NFL_REPLAY`` and the others) stays. The same
    array is also assigned to ``window.MSWP_LIVE``, with sport, away, and
    home on each frame. A failed write leaves the previous file in place.
    """
    script = render_widget_script(states, live=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(script, encoding="utf-8", newline="\n")
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
