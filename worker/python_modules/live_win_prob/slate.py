"""Write scoreboards to slate.js.

With no ``--sport``, the slate command reads the NFL, NHL, and NBA
scoreboards and stops. ``--sport`` writes one sport, including ncaaf,
ncaah, and ncaab. ``--interval`` polls until Ctrl+C. The no-game live
loop calls ``write_slate`` on that same loop and still refreshes the
three pro scoreboards. ``slate_rows`` reads one sport and does not
write a file. The local page server uses it for GET /slate. This
module does not open a socket of its own. The follow command owns the
feed request.

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

from ms_win_prob import GameState

from live_win_prob.follow import (
    Fetch,
    FollowError,
    Sleeper,
    UsageError,
    _FEED_SPORTS,
    _flag_value,
    _parse_date,
    _parse_feed_sport,
    _parse_interval,
    fetch_json,
    scoreboard_url,
    slate_lines,
    slate_states,
)

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "slate.js"
_DEFAULT_INTERVAL = 15.0
_SPORTS = ("nfl", "nhl", "nba")
_USAGE = (
    "usage: python -m live_win_prob slate "
    "[--date YYYYMMDD] [--interval 15] [--out slate.js] "
    "[--sport nfl|nhl|nba|ncaaf|ncaah|ncaab]"
)


@dataclass(frozen=True, slots=True)
class _Options:
    date: str | None
    interval: float | None
    out: Path
    sport: str | None


def parse_slate_args(args: list[str]) -> _Options:
    """Read slate flags.

    ``--interval`` omitted writes once and exits. When the flag is set,
    a bare flag polls every 15 seconds. A number below 5 seconds is
    rejected with the follow interval error.
    """
    date: str | None = None
    interval: float | None = None
    out: Path | None = None
    sport: str | None = None
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
        if token == "--sport" or token.startswith("--sport="):
            if sport is not None:
                raise UsageError("--sport was given twice")
            raw, index = _flag_value("--sport", index, tokens)
            sport = _parse_feed_sport(raw)
            continue
        raise UsageError(f"unrecognized argument: {token}")
    return _Options(
        date=date,
        interval=interval,
        out=DEFAULT_OUT if out is None else out,
        sport=sport,
    )


def run_slate(
    args: list[str],
    *,
    fetch: Fetch | None = None,
    sleep: Sleeper | None = None,
) -> int:
    """Read the requested scoreboards and write ``window.MS_WIN_PROB_SLATE``.

    With no ``--sport`` that is NFL, NHL, and NBA. ``--sport`` names one
    league, including a college sport. Ctrl+C stops a poll and leaves the
    last file in place. A failed write leaves the previous file in place.
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
                options.out, date=options.date, fetch=getter, sport=options.sport
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
    sport: str | None = None,
) -> tuple[list[GameState], list[str]]:
    """Read the requested scoreboards and replace ``path``.

    ``sport`` omitted reads NFL, NHL, and NBA. A sport, including a
    college sport, reads that scoreboard only. ``lines`` are what the
    slate command prints. The live loop ignores them and does not pass
    ``sport``. A failed replace leaves the previous file. ``fetch``
    defaults to the scoreboard getter.
    """
    getter = _real_fetch if fetch is None else fetch
    sports = _SPORTS if sport is None else (sport,)
    states, lines = _read_slate(date, getter, sports)
    _write_slate(path, states)
    return states, lines


def slate_rows(
    *,
    date: str | None = None,
    sport: str,
    fetch: Fetch | None = None,
) -> list[dict[str, object]]:
    """Read one scoreboard and return the page rows.

    ``sport`` is nfl, nhl, nba, ncaaf, ncaah, or ncaab. ``date`` is
    YYYYMMDD when the caller names a day. The dicts use the same fields
    as ``render_slate_script``. This does not write a file. ``fetch``
    defaults to the scoreboard getter.
    """
    if sport not in _FEED_SPORTS:
        raise ValueError("sport must be nfl, nhl, nba, ncaaf, ncaah, or ncaab")
    getter = _real_fetch if fetch is None else fetch
    states, _lines = _read_slate(date, getter, (sport,))
    return [_slate_row(state) for state in states]


def render_slate_script(states: list[GameState]) -> str:
    """JavaScript assignment of the scoreboard rows, then a newline.

    Fields stay in the order sport, game_id, away, home, status,
    away_score, home_score, prior_home. There is no clock and no
    situation. ``prior_home`` is the moneyline already on the state,
    or 0.5 when that payload had none.
    """
    rows = [_slate_row(state) for state in states]
    body = json.dumps(rows, indent=2)
    return f"window.MS_WIN_PROB_SLATE = {body};\n"


def _read_slate(
    date: str | None, fetch: Fetch, sports: tuple[str, ...]
) -> tuple[list[GameState], list[str]]:
    states: list[GameState] = []
    lines: list[str] = []
    for sport in sports:
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
    """GET one followed scoreboard. An unknown URL is refused first."""
    return fetch_json(url, sport=_sport_of(url))


def _sport_of(url: str) -> str:
    for sport in _FEED_SPORTS:
        root = scoreboard_url(sport=sport)
        if url == root or url.startswith(f"{root}?"):
            return sport
    raise ValueError(
        "ESPN URL is not a followed scoreboard. "
        "This command fetches nfl, nhl, nba, ncaaf, ncaah, and ncaab games only."
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
