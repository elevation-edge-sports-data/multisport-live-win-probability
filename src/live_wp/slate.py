"""Write the NFL, NHL, and NBA scoreboards to widget/slate.js.

The slate command reads those three scoreboards and stops.
``--interval`` polls until Ctrl+C. The no-game live loop calls
``write_slate`` on that same loop. College sports are rejected and no
college URL is requested. This module does not serve pages and does
not open a socket of its own. The follow command owns the feed request.

Each row is one GameState from ``slate_states``, the same mapping
``slate_lines`` prints. The printed line is that slate line prefixed
with the sport.
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
    Fetch,
    FollowError,
    Sleeper,
    UsageError,
    _flag_value,
    _parse_date,
    _parse_interval,
    fetch_json,
    scoreboard_url,
    slate_lines,
    slate_states,
)

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "widget" / "slate.js"
_DEFAULT_INTERVAL = 15.0
_SPORTS = ("nfl", "nhl", "nba")
_USAGE = (
    "usage: python -m live_wp slate "
    "[--date YYYYMMDD] [--interval 15] [--out widget/slate.js]"
)


@dataclass(frozen=True, slots=True)
class _Options:
    date: str | None
    interval: float | None
    out: Path


def parse_slate_args(args: list[str]) -> _Options:
    """Read slate flags.

    ``--interval`` omitted writes once and exits. When the flag is set,
    a bare flag polls every 15 seconds. A number below 5 seconds is
    rejected with the follow interval error.
    """
    date: str | None = None
    interval: float | None = None
    out: Path | None = None
    index = 0
    tokens = list(args)
    while index < len(tokens):
        token = tokens[index]
        if token == "--date" or token.startswith("--date="):
            if date is not None:
                raise UsageError("--date was given twice")
            raw, index = _flag_value("--date", index, tokens)
            date = _parse_date(raw)
            continue
        if token == "--interval" or token.startswith("--interval="):
            if interval is not None:
                raise UsageError("--interval was given twice")
            interval, index = _interval_value(index, tokens)
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
    return _Options(
        date=date,
        interval=interval,
        out=DEFAULT_OUT if out is None else out,
    )


def run_slate(
    args: list[str],
    *,
    fetch: Fetch | None = None,
    sleep: Sleeper | None = None,
) -> int:
    """Read the three pro scoreboards and write ``window.MSWP_SLATE``.

    Ctrl+C stops a poll and leaves the last file in place. A failed
    write leaves the previous file in place.
    """
    try:
        options = parse_slate_args(args)
    except UsageError as exc:
        print(exc, file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 2
    getter = _real_fetch if fetch is None else fetch
    pause = time.sleep if sleep is None else sleep
    try:
        while True:
            _written, lines = write_slate(
                options.out, date=options.date, fetch=getter
            )
            for line in lines:
                print(line, flush=True)
            if options.interval is None:
                return 0
            pause(options.interval)
    except KeyboardInterrupt:
        return 0
    except (FollowError, ValueError, TypeError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1


def write_slate(
    path: Path,
    *,
    date: str | None = None,
    fetch: Fetch | None = None,
) -> tuple[list[GameState], list[str]]:
    """Read the NFL, NHL, and NBA scoreboards and replace ``path``.

    ``lines`` are what the slate command prints. The live loop ignores
    them. A failed replace leaves the previous file. ``fetch`` defaults
    to the pro scoreboard getter, which refuses a college URL.
    """
    getter = _real_fetch if fetch is None else fetch
    states, lines = _read_slate(date, getter)
    _write_slate(path, states)
    return states, lines


def render_slate_script(states: list[GameState]) -> str:
    """JavaScript assignment of the pro scoreboard, then a newline.

    Fields stay in the order sport, game_id, away, home, status,
    away_score, home_score, prior_home. There is no clock and no
    situation. ``prior_home`` is the moneyline already on the state,
    or 0.5 when that payload had none.
    """
    rows = [_slate_row(state) for state in states]
    body = json.dumps(rows, indent=2)
    return f"window.MSWP_SLATE = {body};\n"


def _read_slate(
    date: str | None, fetch: Fetch
) -> tuple[list[GameState], list[str]]:
    states: list[GameState] = []
    lines: list[str] = []
    for sport in _SPORTS:
        payload = fetch(scoreboard_url(date, sport=sport))
        states.extend(slate_states(payload, sport=sport))
        lines.extend(f"{sport} {line}" for line in slate_lines(payload, sport=sport))
    return states, lines


def _write_slate(path: Path, states: list[GameState]) -> None:
    """Replace ``path`` with the slate script.

    The temp file is the same rule as ``live.py``. A failed write
    removes the temp file and leaves the previous file in place.
    """
    script = render_slate_script(states)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(script, encoding="utf-8", newline="\n")
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _slate_row(state: GameState) -> dict[str, object]:
    return {
        "sport": state.sport,
        "game_id": state.game_id,
        "away": state.away,
        "home": state.home,
        "status": state.status,
        "away_score": state.away_score,
        "home_score": state.home_score,
        "prior_home": state.prior_home,
    }


def _real_fetch(url: str) -> Mapping[str, Any]:
    """GET one pro scoreboard. A college URL is refused before the opener."""
    return fetch_json(url, sport=_sport_of(url))


def _sport_of(url: str) -> str:
    for sport in _SPORTS:
        root = scoreboard_url(sport=sport)
        if url == root or url.startswith(f"{root}?"):
            return sport
    raise ValueError(
        "ESPN URL is not an nfl, nhl, or nba scoreboard. "
        "This command fetches nfl, nhl, and nba games only."
    )


def _interval_value(index: int, tokens: list[str]) -> tuple[float, int]:
    """15 seconds when ``--interval`` is bare. Otherwise the follow rules."""
    token = tokens[index]
    if token.startswith("--interval="):
        raw = token[len("--interval=") :]
        if not raw:
            raise UsageError("--interval needs a value")
        return _parse_interval(raw), index + 1
    if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
        return _DEFAULT_INTERVAL, index + 1
    return _parse_interval(tokens[index + 1]), index + 2
