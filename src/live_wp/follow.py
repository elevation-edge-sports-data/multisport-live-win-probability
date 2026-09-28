"""Poll the unofficial ESPN NFL site API and print replay lines.

Network stays in this module. The mapper accepts dicts and does not fetch.
The widget does not call this.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from mswp import NFL_CONFIG as nfl_config
from mswp import GameState, compute_wp

from live_wp.feeds.espn import (
    espn_scoreboard_event_to_state,
    home_moneyline_prior,
    require_nfl_payload,
    states_from_espn,
)
from live_wp.replay import format_line

_NFL_ROOT = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
_TIMEOUT_SECONDS = 20

Fetch = Callable[[str], Mapping[str, Any]]
Sleeper = Callable[[float], None]


class UsageError(Exception):
    """The follow command line itself is wrong."""


class FollowError(Exception):
    """A fetch or ESPN body could not be used."""


@dataclass(frozen=True, slots=True)
class _Options:
    date: str | None
    game: str | None
    interval: float


def scoreboard_url(date: str | None = None) -> str:
    """NFL scoreboard. ``date`` is YYYYMMDD when the caller names a day."""
    base = _NFL_ROOT + "scoreboard"
    if date is None:
        return base
    return base + "?" + urlencode({"dates": date})


def summary_url(event_id: str) -> str:
    """NFL game summary for one event id."""
    return _NFL_ROOT + "summary?" + urlencode({"event": event_id})


def reject_non_nfl_url(url: str) -> None:
    """Refuse college football and anything that is not the NFL site path."""
    lowered = url.lower()
    if "college-football" in lowered or "ncaaf" in lowered:
        raise ValueError(
            "ESPN URL is college football (ncaaf), not NFL. "
            "This command fetches NFL games only."
        )
    if not lowered.startswith(_NFL_ROOT):
        raise ValueError(
            "ESPN URL is not an NFL scoreboard or summary. "
            "This command fetches NFL games only."
        )


def fetch_json(url: str, *, opener: Callable[..., Any] | None = None) -> Any:
    """GET one NFL URL with the standard library and decode a JSON object.

    ``opener`` replaces ``urllib.request.urlopen`` in tests. College-football
    URLs are rejected before the opener is called.
    """
    reject_non_nfl_url(url)
    open_url = urllib.request.urlopen if opener is None else opener
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "multisport-live-win-probability/0.1",
        },
    )
    try:
        response = open_url(request, timeout=_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        raise FollowError(f"ESPN request failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise FollowError(f"ESPN request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise FollowError("ESPN request timed out") from exc
    except OSError as exc:
        raise FollowError(f"ESPN request failed: {exc}") from exc
    try:
        final_url = response.geturl() if hasattr(response, "geturl") else url
        reject_non_nfl_url(str(final_url))
        raw = response.read()
    finally:
        close = getattr(response, "close", None)
        if close is not None:
            close()
    if isinstance(raw, str):
        text = raw
    else:
        text = raw.decode("utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FollowError("ESPN response was not JSON") from exc
    if not isinstance(payload, dict):
        raise FollowError("ESPN response was not a JSON object")
    return payload


def format_slate_line(state: GameState) -> str:
    """One slate row: event id, away @ home, status, away-home score."""
    return (
        f"{state.game_id} {state.away} @ {state.home} "
        f"{state.status} {state.away_score}-{state.home_score}"
    )


def slate_lines(payload: Mapping[str, Any]) -> list[str]:
    """Map a scoreboard once. Nothing is printed until every event maps.

    Each event is checked again. A college game on an NFL board is refused.
    """
    require_nfl_payload(payload)
    lines: list[str] = []
    for event in _events(payload):
        require_nfl_payload(event)
        lines.append(format_slate_line(espn_scoreboard_event_to_state(event)))
    return lines


def run_follow(
    args: list[str],
    *,
    fetch: Fetch | None = None,
    sleep: Sleeper | None = None,
) -> int:
    """Run ``follow``. Missing ``--game`` lists the slate and exits."""
    try:
        options = parse_follow_args(args)
    except UsageError as exc:
        print(exc, file=sys.stderr)
        print(
            "usage: python -m live_wp follow "
            "[--date YYYYMMDD] [--game ESPN_EVENT_ID] [--interval 15]",
            file=sys.stderr,
        )
        return 2
    getter = fetch_json if fetch is None else fetch
    try:
        if options.game is None:
            return _print_slate(options.date, getter)
        return follow_game(
            options.game,
            date=options.date,
            interval=options.interval,
            fetch=getter,
            sleep=time.sleep if sleep is None else sleep,
        )
    except KeyboardInterrupt:
        return 0
    except (FollowError, ValueError, TypeError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1


def parse_follow_args(args: list[str]) -> _Options:
    """Read follow flags. The interval default is 15 seconds, minimum 5."""
    date: str | None = None
    game: str | None = None
    interval: float | None = None
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
        if token == "--game" or token.startswith("--game="):
            if game is not None:
                raise UsageError("--game was given twice")
            raw, index = _flag_value("--game", index, tokens)
            game = _parse_game(raw)
            continue
        if token == "--interval" or token.startswith("--interval="):
            if interval is not None:
                raise UsageError("--interval was given twice")
            raw, index = _flag_value("--interval", index, tokens)
            interval = _parse_interval(raw)
            continue
        raise UsageError(f"unrecognized argument: {token}")
    return _Options(date=date, game=game, interval=15.0 if interval is None else interval)


def follow_game(
    game_id: str,
    *,
    date: str | None = None,
    interval: float = 15,
    fetch: Fetch,
    sleep: Sleeper,
) -> int:
    """Poll one NFL event until it is final.

    The scoreboard is preferred. A missing id falls back to that event's
    summary. A line is printed only when the clock, score, period, status,
    or situation changes. ``prior_home`` stays on the first moneyline seen.
    """
    if interval < 5:
        raise ValueError("interval must be at least 5 seconds")
    frozen: float | None = None
    previous: GameState | None = None
    while True:
        payload = _load_game(game_id, date, fetch)
        state, frozen = _with_frozen_prior(payload, frozen)
        if _changed(previous, state):
            wp = compute_wp(state, state.prior_home, nfl_config)
            print(format_line(state, wp), flush=True)
            previous = state
        if state.status == "final":
            return 0
        sleep(interval)


def _print_slate(date: str | None, fetch: Fetch) -> int:
    payload = fetch(scoreboard_url(date))
    for line in slate_lines(payload):
        print(line, flush=True)
    return 0


def _load_game(game_id: str, date: str | None, fetch: Fetch) -> Mapping[str, Any]:
    board = fetch(scoreboard_url(date))
    require_nfl_payload(board)
    for event in _events(board):
        if _same_id(event, game_id):
            require_nfl_payload(event)
            return event
    summary = fetch(summary_url(game_id))
    require_nfl_payload(summary)
    return summary


def _with_frozen_prior(
    payload: Mapping[str, Any], frozen: float | None
) -> tuple[GameState, float | None]:
    """Keep the first home moneyline. Later prices do not move it.

    Payloads with no moneyline leave the frozen value unset and the snapshot
    uses 0.5 until one appears.
    """
    implied = home_moneyline_prior(payload)
    if frozen is None and implied is not None:
        frozen = implied
    state = _current_state(payload, frozen)
    if frozen is not None and state.prior_home != frozen:
        state = replace(state, prior_home=frozen)
    return state, frozen


def _current_state(payload: Mapping[str, Any], prior: float | None) -> GameState:
    """Latest NFL snapshot. A summary keeps its trailing status row.

    College football can be ingested, but this command does not follow it.
    """
    require_nfl_payload(payload)
    states = states_from_espn(payload, prior_home=prior, density="all")
    if not states:
        raise ValueError("ESPN payload did not produce a snapshot")
    return states[-1]


def _changed(previous: GameState | None, state: GameState) -> bool:
    if previous is None:
        return True
    return _mark(previous) != _mark(state)


def _mark(state: GameState) -> tuple[object, ...]:
    timeouts = None
    if state.timeouts is not None:
        timeouts = (int(state.timeouts["home"]), int(state.timeouts["away"]))
    return (
        state.seconds_remaining_period,
        state.home_score,
        state.away_score,
        state.period,
        state.status,
        state.possession,
        state.down,
        state.distance,
        state.yardline,
        timeouts,
    )


def _events(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = payload.get("events")
    if not isinstance(raw, list):
        raise ValueError("ESPN scoreboard is missing an events list")
    events: list[Mapping[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("ESPN scoreboard event must be an object")
        events.append(item)
    return events


def _same_id(event: Mapping[str, Any], game_id: str) -> bool:
    raw = event.get("id")
    if raw is None:
        return False
    return str(raw).strip() == game_id


def _flag_value(flag: str, index: int, tokens: list[str]) -> tuple[str, int]:
    token = tokens[index]
    prefix = flag + "="
    if token.startswith(prefix):
        value = token[len(prefix) :]
        if not value:
            raise UsageError(f"{flag} needs a value")
        return value, index + 1
    if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
        raise UsageError(f"{flag} needs a value")
    return tokens[index + 1], index + 2


def _parse_date(text: str) -> str:
    if len(text) != 8 or not text.isdigit():
        raise UsageError("date must be YYYYMMDD")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError:
        raise UsageError("date must be YYYYMMDD") from None
    return text


def _parse_game(text: str) -> str:
    lowered = text.lower()
    if "college-football" in lowered or "ncaaf" in lowered:
        raise UsageError(
            "ESPN URL is college football (ncaaf), not NFL. "
            "This command fetches NFL games only."
        )
    if not text.isdigit():
        raise UsageError("game must be an ESPN NFL event id")
    return text


def _parse_interval(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise UsageError("interval must be a number of seconds") from None
    if value != value or value == float("inf") or value < 5:
        raise UsageError("interval must be at least 5 seconds")
    return value
