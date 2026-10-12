"""Poll an unofficial ESPN site API and print replay lines.

Network stays in this module. The mappers accept dicts and do not fetch.
The page does not call this. ``--sport nfl`` is the default. ``nhl`` and
``ncaah`` use the hockey feed. ``nba`` and ``ncaab`` use the basketball
feed. ``ncaaf`` uses the college-football feed. The same payload checks
used for the pro leagues refuse a body from a different league.
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

from mswp import GameState, compute_wp

from live_wp.feeds.espn import (
    espn_scoreboard_event_to_state,
    home_moneyline_prior,
    require_ncaaf_payload,
    require_ncaah_payload,
    require_nfl_payload,
    require_nhl_payload,
    states_from_espn,
)
from live_wp.feeds.espn_basketball import (
    events_from_espn_basketball,
    require_nba_payload,
    require_ncaab_payload,
    scoreboard_event_to_state,
)
from live_wp.replay import config_for_state, format_line

_ROOTS = {
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/",
    "nhl": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/",
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/",
    "ncaaf": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/",
    "ncaah": "https://site.api.espn.com/apis/site/v2/sports/hockey/mens-college-hockey/",
    "ncaab": (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/"
        "mens-college-basketball/"
    ),
}
_NFL_ROOT = _ROOTS["nfl"]
_PRO_SPORTS = ("nfl", "nhl", "nba")
_FEED_SPORTS = ("nfl", "nhl", "nba", "ncaaf", "ncaah", "ncaab")
_COLLEGE_SPORTS = {
    "ncaaf": "college football (ncaaf)",
    "ncaah": "college hockey (ncaah)",
    "ncaab": "college basketball (ncaab)",
}
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
    sport: str


def scoreboard_url(date: str | None = None, *, sport: str = "nfl") -> str:
    """Scoreboard for one followed sport.

    ``date`` is YYYYMMDD when the caller names a day. The default sport
    is nfl, which keeps the original NFL scoreboard URL.
    """
    base = _root(sport) + "scoreboard"
    if date is None:
        return base
    return base + "?" + urlencode({"dates": date})


def summary_url(event_id: str, *, sport: str = "nfl") -> str:
    """Game summary for one event id. The default sport is nfl."""
    return _root(sport) + "summary?" + urlencode({"event": event_id})


def _root(sport: str) -> str:
    try:
        return _ROOTS[sport]
    except KeyError:
        raise ValueError(
            "ESPN sport is not a followed league. "
            "This command fetches nfl, nhl, nba, ncaaf, ncaah, and ncaab games only."
        ) from None


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


def fetch_json(
    url: str,
    *,
    opener: Callable[..., Any] | None = None,
    sport: str = "nfl",
) -> Any:
    """GET one ESPN URL with the standard library and decode a JSON object.

    ``opener`` replaces ``urllib.request.urlopen`` in tests. ``sport``
    defaults to nfl. A URL for a different league is rejected before the
    opener is called.
    """
    reject_follow_url(url, sport)
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
        reject_follow_url(str(final_url), sport)
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


def reject_follow_url(url: str, sport: str = "nfl") -> None:
    """Refuse a URL that is not the scoreboard or summary for ``sport``.

    The nfl path keeps the original college-football refusal. Each other
    sport refuses the other five league paths in that same style, then
    requires its own site root.
    """
    if sport == "nfl":
        reject_non_nfl_url(url)
        return
    if sport in _PRO_SPORTS:
        _reject_pro_feed_url(url, sport)
        return
    _reject_college_feed_url(url, sport)


def _reject_pro_feed_url(url: str, sport: str) -> None:
    """NHL and NBA keep the original refusal of every college path."""
    lowered = url.lower()
    if "college-football" in lowered or "ncaaf" in lowered:
        raise ValueError(
            "ESPN URL is college football (ncaaf), not NFL. "
            "This command fetches NFL games only."
        )
    if (
        "college-hockey" in lowered
        or "mens-college-hockey" in lowered
        or "ncaah" in lowered
    ):
        raise ValueError(
            "ESPN URL is college hockey (ncaah), not NHL. "
            "This command fetches NHL games only."
        )
    if (
        "mens-college-basketball" in lowered
        or "college-basketball" in lowered
        or "ncaab" in lowered
    ):
        raise ValueError(
            "ESPN URL is college basketball (ncaab), not NBA. "
            "This command fetches NBA games only."
        )
    root = _root(sport)
    label = sport.upper()
    if not lowered.startswith(root):
        raise ValueError(
            f"ESPN URL is not an {label} scoreboard or summary. "
            f"This command fetches {label} games only."
        )


def _reject_college_feed_url(url: str, sport: str) -> None:
    """Require the college root and refuse every other league path."""
    lowered = url.lower()
    own = _COLLEGE_SPORTS[sport]
    for other, marks, label in _COLLEGE_URL_MARKS:
        if other == sport:
            continue
        if any(mark in lowered for mark in marks):
            raise ValueError(
                f"ESPN URL is {label}, not {own}. "
                f"This command fetches {own} games only."
            )
    for marks, label in _PRO_URL_MARKS:
        if any(mark in lowered for mark in marks):
            raise ValueError(
                f"ESPN URL is {label}, not {own}. "
                f"This command fetches {own} games only."
            )
    root = _root(sport)
    pretty = sport.upper()
    if not lowered.startswith(root):
        raise ValueError(
            f"ESPN URL is not an {pretty} scoreboard or summary. "
            f"This command fetches {pretty} games only."
        )


_COLLEGE_URL_MARKS = (
    ("ncaaf", ("college-football", "ncaaf"), "college football (ncaaf)"),
    (
        "ncaah",
        ("mens-college-hockey", "college-hockey", "ncaah"),
        "college hockey (ncaah)",
    ),
    (
        "ncaab",
        ("mens-college-basketball", "college-basketball", "ncaab"),
        "college basketball (ncaab)",
    ),
)
_PRO_URL_MARKS = (
    (("/football/nfl/", "/nfl/"), "NFL"),
    (("/hockey/nhl/", "/nhl/"), "NHL"),
    (("/basketball/nba/", "/nba/"), "NBA"),
)


def slate_states(payload: Mapping[str, Any], *, sport: str = "nfl") -> list[GameState]:
    """Map a scoreboard once. Nothing is returned until every event maps.

    Each event is checked again. A college game on a pro board is refused.
    ``slate_lines`` is these rows passed through ``format_slate_line``.
    """
    _require_sport_payload(payload, sport)
    states: list[GameState] = []
    for event in _events(payload):
        _require_sport_payload(event, sport)
        states.append(_slate_state(event, sport))
    return states


def slate_lines(payload: Mapping[str, Any], *, sport: str = "nfl") -> list[str]:
    """Map a scoreboard once. Nothing is printed until every event maps.

    Each event is checked again. A college game on a pro board is refused.
    """
    return [format_slate_line(state) for state in slate_states(payload, sport=sport)]


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
            "[--date YYYYMMDD] [--game ESPN_EVENT_ID] [--interval 15] "
            "[--sport nfl|nhl|nba|ncaaf|ncaah|ncaab]",
            file=sys.stderr,
        )
        return 2
    if fetch is None:
        selected = options.sport

        def getter(url: str) -> Mapping[str, Any]:
            return fetch_json(url, sport=selected)

    else:
        getter = fetch
    try:
        if options.game is None:
            return _print_slate(options.date, getter, options.sport)
        return follow_game(
            options.game,
            date=options.date,
            interval=options.interval,
            sport=options.sport,
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
        if token == "--game" or token.startswith("--game="):
            if game is not None:
                raise UsageError("--game was given twice")
            raw, index = _flag_value("--game", index, tokens)
            game = raw
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
            sport = _parse_feed_sport(raw)
            continue
        raise UsageError(f"unrecognized argument: {token}")
    selected = "nfl" if sport is None else sport
    parsed_game = None if game is None else _parse_game(game, selected)
    return _Options(
        date=date,
        game=parsed_game,
        interval=15.0 if interval is None else interval,
        sport=selected,
    )


def follow_game(
    game_id: str,
    *,
    date: str | None = None,
    interval: float = 15,
    sport: str = "nfl",
    fetch: Fetch,
    sleep: Sleeper,
    on_change: Callable[[GameState], None] | None = None,
    stop: Callable[[], bool] | None = None,
    before_poll: Callable[[], None] | None = None,
) -> int:
    """Poll one event until it is final.

    The scoreboard is preferred. A missing id falls back to that event's
    summary. A line is printed only when the clock, score, period, status,
    or situation changes. ``prior_home`` stays on the first moneyline seen.
    ``sport`` defaults to nfl. ``on_change`` runs after each printed line
    with that snapshot. When ``stop`` returns true, the loop returns 0
    before the next fetch. ``before_poll``, when set, runs after that
    check and before the fetch. The page does not call this loop.
    """
    if interval < 5:
        raise ValueError("interval must be at least 5 seconds")
    frozen: float | None = None
    previous: GameState | None = None
    while True:
        if stop is not None and stop():
            return 0
        if before_poll is not None:
            before_poll()
        payload = _load_game(game_id, date, fetch, sport)
        state, frozen = _with_frozen_prior(payload, frozen, sport)
        if _changed(previous, state):
            wp = compute_wp(state, state.prior_home, config_for_state(state))
            print(format_line(state, wp), flush=True)
            if on_change is not None:
                on_change(state)
            previous = state
        if state.status == "final":
            return 0
        sleep(interval)


def _print_slate(date: str | None, fetch: Fetch, sport: str) -> int:
    payload = fetch(scoreboard_url(date, sport=sport))
    for line in slate_lines(payload, sport=sport):
        print(line, flush=True)
    return 0


def _load_game(
    game_id: str, date: str | None, fetch: Fetch, sport: str
) -> Mapping[str, Any]:
    board = fetch(scoreboard_url(date, sport=sport))
    _require_sport_payload(board, sport)
    if isinstance(board.get("events"), list):
        for event in _events(board):
            if _same_id(event, game_id):
                _require_sport_payload(event, sport)
                return event
    elif _matches_game(board, game_id):
        return board
    summary = fetch(summary_url(game_id, sport=sport))
    _require_sport_payload(summary, sport)
    return summary


def _with_frozen_prior(
    payload: Mapping[str, Any], frozen: float | None, sport: str
) -> tuple[GameState, float | None]:
    """Keep the first home moneyline. Later prices do not move it.

    Payloads with no moneyline leave the frozen value unset and the snapshot
    uses 0.5 until one appears.
    """
    implied = home_moneyline_prior(payload)
    if frozen is None and implied is not None:
        frozen = implied
    state = _current_state(payload, frozen, sport)
    if frozen is not None and state.prior_home != frozen:
        state = replace(state, prior_home=frozen)
    return state, frozen


def _current_state(
    payload: Mapping[str, Any], prior: float | None, sport: str
) -> GameState:
    """Latest snapshot. A summary keeps its trailing status row.

    College football and college hockey use the football and hockey
    mappers. College basketball uses the basketball mapper, as the NBA does.
    """
    _require_sport_payload(payload, sport)
    if sport in {"nba", "ncaab"}:
        states = _basketball_states(payload, prior)
    else:
        states = states_from_espn(payload, prior_home=prior, density="all")
    if not states:
        raise ValueError("ESPN payload did not produce a snapshot")
    return states[-1]


def _basketball_states(
    payload: Mapping[str, Any], prior: float | None
) -> list[GameState]:
    if isinstance(payload.get("header"), Mapping) and isinstance(payload.get("plays"), list):
        return events_from_espn_basketball(payload, prior_home=prior, density="all")
    if isinstance(payload.get("competitions"), list):
        return [scoreboard_event_to_state(payload, prior_home=prior)]
    raise ValueError("ESPN payload did not produce a snapshot")


def replay_states(
    game_id: str,
    *,
    sport: str,
    date: str | None = None,
    fetch: Fetch | None = None,
) -> list[GameState]:
    """Snapshots to chart for one slate game.

    A game that has not started, or a body with no snapshots, returns an
    empty list. That is not a failure. A live or final summary returns its
    scoring snapshots, including the opening row. When that summary has
    none, a live or final scoreboard row is the one snapshot. ``fetch``
    reads the scoreboard and, unless that row is still pre, the summary.
    """
    getter = _feed_fetch(sport) if fetch is None else fetch
    board_state = _board_snapshot(game_id, date, getter, sport)
    if board_state is not None and board_state.status == "pre":
        return []
    summary_states = _summary_snapshots(game_id, getter, sport)
    if summary_states and any(state.status != "pre" for state in summary_states):
        return summary_states
    if board_state is not None and board_state.status != "pre":
        return [board_state]
    return []


def _feed_fetch(sport: str) -> Fetch:
    """GET helper for one sport. The caller has already checked the sport."""

    def getter(url: str) -> Mapping[str, Any]:
        return fetch_json(url, sport=sport)

    return getter


def _board_snapshot(
    game_id: str, date: str | None, fetch: Fetch, sport: str
) -> GameState | None:
    """The scoreboard row for this id, or None when it is missing or unusable."""
    try:
        board = fetch(scoreboard_url(date, sport=sport))
        _require_sport_payload(board, sport)
    except (FollowError, ValueError, TypeError, OSError):
        return None
    if not isinstance(board, Mapping) or not isinstance(board.get("events"), list):
        return None
    for event in board["events"]:
        if not isinstance(event, Mapping) or not _same_id(event, game_id):
            continue
        try:
            return _current_state(event, home_moneyline_prior(event), sport)
        except (ValueError, TypeError):
            return None
    return None


def _summary_snapshots(game_id: str, fetch: Fetch, sport: str) -> list[GameState]:
    """Scoring snapshots from the summary. Empty when the body has none."""
    try:
        summary = fetch(summary_url(game_id, sport=sport))
        return _chart_states(summary, sport)
    except (FollowError, ValueError, TypeError, OSError):
        return []


def _chart_states(payload: Mapping[str, Any], sport: str) -> list[GameState]:
    """Scoring snapshots for a summary or one scoreboard event.

    The opening row stays. ``prior_home`` is the first moneyline on the
    body, frozen the same way the follow loop freezes it.
    """
    if not isinstance(payload, Mapping):
        return []
    _require_sport_payload(payload, sport)
    prior = home_moneyline_prior(payload)
    if sport in {"nba", "ncaab"}:
        states = _basketball_chart_states(payload, prior)
    else:
        states = states_from_espn(payload, prior_home=prior, density="scoring")
    if prior is None:
        return states
    return [
        state if state.prior_home == prior else replace(state, prior_home=prior)
        for state in states
    ]


def _basketball_chart_states(
    payload: Mapping[str, Any], prior: float | None
) -> list[GameState]:
    plays = payload.get("plays")
    if isinstance(payload.get("header"), Mapping) and isinstance(plays, list) and plays:
        return events_from_espn_basketball(payload, prior_home=prior, density="scoring")
    if isinstance(payload.get("competitions"), list):
        return [scoreboard_event_to_state(payload, prior_home=prior)]
    return []


def _slate_state(event: Mapping[str, Any], sport: str) -> GameState:
    if sport in {"nba", "ncaab"}:
        return scoreboard_event_to_state(event)
    return espn_scoreboard_event_to_state(event)


def _require_sport_payload(payload: Mapping[str, Any], sport: str) -> None:
    if sport == "nhl":
        require_nhl_payload(payload)
        return
    if sport == "ncaah":
        require_ncaah_payload(payload)
        return
    if sport == "nba":
        require_nba_payload(payload)
        return
    if sport == "ncaab":
        require_ncaab_payload(payload)
        return
    if sport == "ncaaf":
        require_ncaaf_payload(payload)
        return
    require_nfl_payload(payload)


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


def _matches_game(payload: Mapping[str, Any], game_id: str) -> bool:
    """True when a summary object, not a scoreboard list, is this event."""
    if _same_id(payload, game_id):
        return True
    header = payload.get("header")
    if isinstance(header, Mapping) and _same_id(header, game_id):
        return True
    for competition in _competitions(payload):
        if _same_id(competition, game_id):
            return True
    return False


def _competitions(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = payload.get("competitions")
    if not isinstance(raw, list):
        header = payload.get("header")
        raw = header.get("competitions") if isinstance(header, Mapping) else None
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


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


def _parse_feed_sport(text: str) -> str:
    """Sport for follow and slate. College sports are included."""
    lowered = text.strip().lower()
    if lowered not in _FEED_SPORTS:
        raise UsageError("sport must be nfl, nhl, nba, ncaaf, ncaah, or ncaab")
    return lowered


def _parse_sport(text: str) -> str:
    """Sport for the live command. College sports stay a usage error there."""
    lowered = text.strip().lower()
    if lowered in _COLLEGE_SPORTS:
        label = _COLLEGE_SPORTS[lowered]
        raise UsageError(
            f"ESPN sport is {label}, not a followed league. "
            "This command fetches nfl, nhl, and nba games only."
        )
    if lowered not in _PRO_SPORTS:
        raise UsageError("sport must be nfl, nhl, or nba")
    return lowered


def _parse_game(text: str, sport: str) -> str:
    lowered = text.lower()
    if sport != "ncaaf" and ("college-football" in lowered or "ncaaf" in lowered):
        raise UsageError(
            "ESPN URL is college football (ncaaf), not NFL. "
            "This command fetches NFL games only."
        )
    if sport != "ncaah" and (
        "college-hockey" in lowered
        or "mens-college-hockey" in lowered
        or "ncaah" in lowered
    ):
        raise UsageError(
            "ESPN URL is college hockey (ncaah), not NHL. "
            "This command fetches NHL games only."
        )
    if sport != "ncaab" and (
        "mens-college-basketball" in lowered
        or "college-basketball" in lowered
        or "ncaab" in lowered
    ):
        raise UsageError(
            "ESPN URL is college basketball (ncaab), not NBA. "
            "This command fetches NBA games only."
        )
    if not text.isdigit():
        if sport == "nfl":
            raise UsageError("game must be an ESPN NFL event id")
        raise UsageError("game must be an ESPN event id")
    return text


def _parse_interval(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise UsageError("interval must be a number of seconds") from None
    if value != value or value == float("inf") or value < 5:
        raise UsageError("interval must be at least 5 seconds")
    return value
