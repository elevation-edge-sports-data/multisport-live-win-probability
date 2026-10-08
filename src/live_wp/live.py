"""Rewrite a widget replay while the follow loop polls one game.

Each printed change is passed through ``render_widget_script``, which
recomputes win probability with the pack for that sport. College sports
are rejected. This module does not serve pages and does not open a socket
of its own. The follow command owns the feed request.

``--game`` follows that id and does not read follow.json or rewrite the
slate. Without ``--game``, the command reads widget/follow.json. Before
each poll, and on each wait, it rewrites widget/slate.js for NFL, NHL,
and NBA through the slate writer. A missing file waits. A new game id
stops the current poll and replaces the replay from the new game's
history.
"""

from __future__ import annotations

import json
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
from live_wp.slate import DEFAULT_OUT as DEFAULT_SLATE, write_slate

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "widget" / "live_replay.js"
DEFAULT_FOLLOW = Path(__file__).resolve().parents[2] / "widget" / "follow.json"
_USAGE = (
    "usage: python -m live_wp live [--game ESPN_EVENT_ID] "
    "[--sport nfl|nhl|nba] [--interval 15] [--out widget/live_replay.js]"
)


@dataclass(frozen=True, slots=True)
class _Options:
    game: str | None
    interval: float
    sport: str
    out: Path


def parse_live_args(args: list[str]) -> _Options:
    """Read live flags. Without ``--game``, follow.json names the game."""
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
    selected = "nfl" if sport is None else sport
    parsed_game = None if game is None else _parse_game(game, selected)
    return _Options(
        game=parsed_game,
        interval=15.0 if interval is None else interval,
        sport=selected,
        out=DEFAULT_OUT if out is None else out,
    )


def run_live(
    args: list[str],
    *,
    fetch=None,
    sleep=None,
    follow_path: Path | None = None,
    slate_path: Path | None = None,
) -> int:
    """Poll one event and rewrite the replay script on each printed change.

    ``--game`` wins. The follow file is not read and the slate is not
    rewritten. Without it, ``follow_path`` (default widget/follow.json)
    supplies sport and game id, and ``slate_path`` (default
    widget/slate.js) is rewritten on that loop. Ctrl+C stops the poll
    and leaves the last scripts in place.
    """
    try:
        options = parse_live_args(args)
    except UsageError as exc:
        print(exc, file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 2
    pause = time.sleep if sleep is None else sleep
    selected_file = DEFAULT_FOLLOW if follow_path is None else follow_path
    selected_slate = DEFAULT_SLATE if slate_path is None else slate_path
    try:
        if options.game is None:
            return _follow_file(
                options, fetch, pause, selected_file, selected_slate
            )
        return follow_game(
            options.game,
            interval=options.interval,
            sport=options.sport,
            fetch=_getter(fetch, options.sport),
            sleep=pause,
            on_change=_remember(options.out),
        )
    except KeyboardInterrupt:
        return 0
    except (FollowError, ValueError, TypeError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1


def _follow_file(
    options: _Options, fetch, pause, path: Path, slate_path: Path
) -> int:
    """Follow the game named in ``path`` and refresh the slate on this loop.

    A missing file waits. That wait rewrites the slate, then sleeps.
    Before each game poll the slate is rewritten again. A new sport or
    game id stops the poll. The next write replaces the replay with that
    game's own history. A final game stays on disk until the file names
    a different game, and the slate keeps being rewritten on that wait.
    """

    def refresh() -> None:
        write_slate(slate_path, fetch=fetch)

    while True:
        chosen = _read_follow(path)
        if chosen is None:
            refresh()
            pause(options.interval)
            continue
        sport, game_id = chosen
        target = (sport, game_id)

        def stopped() -> bool:
            latest = _read_follow(path)
            return latest != target

        follow_game(
            game_id,
            interval=options.interval,
            sport=sport,
            fetch=_getter(fetch, sport),
            sleep=pause,
            on_change=_remember(options.out),
            stop=stopped,
            before_poll=refresh,
        )
        if _read_follow(path) != target:
            continue
        while _read_follow(path) == target:
            refresh()
            pause(options.interval)


def _remember(path: Path):
    """Append each new snapshot and replace the replay with that history."""
    history: list[GameState] = []

    def on_change(state: GameState) -> None:
        history.append(state)
        _write_replay_script(path, history)

    return on_change


def _getter(fetch, sport: str):
    """Use the injected fetch, or GET the scoreboard for this sport."""
    if fetch is not None:
        return fetch

    def getter(url: str) -> Mapping[str, Any]:
        return fetch_json(url, sport=sport)

    return getter


def _read_follow(path: Path) -> tuple[str, str] | None:
    """Sport and game id from follow.json. None when the file is not there.

    A present file that is not nfl, nhl, or nba, or that has no event id,
    raises ValueError. The caller does not fetch in that case.
    """
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("follow.json is not JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("follow.json needs sport and game_id")
    sport = payload.get("sport")
    game_id = payload.get("game_id")
    if not isinstance(sport, str) or not isinstance(game_id, str):
        raise ValueError("follow.json needs sport and game_id")
    try:
        parsed_sport = _parse_sport(sport)
        parsed_game = _parse_game(game_id, parsed_sport)
    except UsageError as exc:
        raise ValueError(str(exc)) from exc
    return parsed_sport, parsed_game


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
