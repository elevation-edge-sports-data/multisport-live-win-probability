"""Map a saved ESPN NFL payload to GameState snapshots.

The caller loads the JSON. This module does not fetch. It accepts a
scoreboard event object or a game summary object from the unofficial ESPN
site API. College football and any other league are refused.

A home American moneyline, when present, is converted once into
``prior_home`` and reused on every snapshot. ESPN's own win-probability
field is never copied onto a snapshot and is never returned as the
win probability.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from mswp import DEFAULT_PRIOR_HOME, NFL_CONFIG, GameState

# League ids on ESPN football uids: NFL is l:28, college football is l:23.
_NFL_LEAGUE_ID = "28"
_CFB_LEAGUE_ID = "23"
_UID_LEAGUE = re.compile(r"(?:^|~)l:(\d+)(?:~|$)")
_AT_SPOT = re.compile(r"\bat\s+([A-Za-z][A-Za-z0-9.]{1,11})\s+(\d{1,2})\b", re.I)
_TEAM_SPOT = re.compile(r"\b([A-Za-z][A-Za-z0-9.]{1,11})\s+(\d{1,2})\b")
_MIDFIELD = re.compile(r"\b(?:MIDFIELD|MID|50)\b", re.I)
_OUR_STATUS = {"pre": "pre", "in": "live", "post": "final"}


@dataclass(frozen=True, slots=True)
class _Side:
    id: str
    name: str
    abbreviation: str | None


def espn_scoreboard_event_to_state(
    event: Mapping[str, Any],
    *,
    prior_home: float | None = None,
) -> GameState:
    """One snapshot for a scoreboard event.

    ``prior_home`` is used only when the event has no home moneyline.
    Otherwise the moneyline is converted once.
    """
    if not isinstance(event, Mapping):
        raise TypeError("ESPN scoreboard event must be an object")
    _require_nfl(event)
    if not isinstance(event.get("competitions"), list):
        raise ValueError("ESPN scoreboard event is missing competitions")
    competition = _competition(event)
    home, away, home_score, away_score = _competitors(competition)
    espn_state, period, display = _status_parts(_status_block(competition, event))
    if period is None:
        period = NFL_CONFIG.regulation_periods if espn_state == "post" else 1
    if display is None:
        display = "0:00" if espn_state == "post" else _seconds_to_display(
            _period_length(period)
        )
    period_seconds = _parse_clock(display)
    situation = competition.get("situation")
    spot = situation if isinstance(situation, Mapping) else None
    possessing = spot.get("possession") if spot is not None else None
    return _build(
        game_id=_event_id(event, competition),
        home=home,
        away=away,
        home_score=home_score,
        away_score=away_score,
        period=period,
        period_seconds=period_seconds,
        status=_OUR_STATUS[espn_state],
        prior=_resolve_prior(event, prior_home),
        as_of=_event_as_of(event, competition),
        spot=spot,
        possessing_id=possessing,
    )


DENSITIES = ("scoring", "situation", "all")


def espn_summary_to_states(
    summary: Mapping[str, Any],
    *,
    prior_home: float | None = None,
    density: str = "scoring",
) -> list[GameState]:
    """Snapshots for one game summary.

    ``density="scoring"`` (the default) keeps kickoff, the start of each
    quarter, every scoring change, the two-minute warning when a pair of
    plays straddles it, overtime scores, and the final.

    ``density="situation"`` keeps every play that has possession, down,
    distance, and yard line, plus kickoff, quarter starts, and the final.

    ``density="all"`` keeps every play on ``drives.previous`` and any
    top-level ``plays`` list, plus kickoff and the final.
    """
    if not isinstance(summary, Mapping):
        raise TypeError("ESPN summary must be an object")
    if density not in DENSITIES:
        raise ValueError("density must be scoring, situation, or all")
    _require_nfl(summary)
    header = summary.get("header")
    if not isinstance(header, Mapping):
        raise ValueError("ESPN summary is missing a header")
    competition = _competition(summary)
    return _summary_states(summary, header, competition, prior_home, density)


def states_from_espn(
    payload: Mapping[str, Any],
    *,
    prior_home: float | None = None,
    density: str = "scoring",
) -> list[GameState]:
    """Detect a scoreboard event versus a summary and map it."""
    if density not in DENSITIES:
        raise ValueError("density must be scoring, situation, or all")
    if not isinstance(payload, Mapping):
        raise TypeError("ESPN payload must be an object")
    header = payload.get("header")
    if isinstance(header, Mapping) and any(
        key in payload for key in ("drives", "scoringPlays", "boxscore", "plays")
    ):
        return espn_summary_to_states(payload, prior_home=prior_home, density=density)
    if isinstance(payload.get("competitions"), list) and "header" not in payload:
        return [espn_scoreboard_event_to_state(payload, prior_home=prior_home)]
    if isinstance(payload.get("events"), list):
        raise ValueError(
            "ESPN payload is a scoreboard list. "
            "Pass one event object or one game summary."
        )
    raise ValueError(
        "ESPN payload must be one NFL scoreboard event or one NFL game summary."
    )


def _require_nfl(payload: Mapping[str, Any]) -> None:
    """Refuse anything that is not a confirmed NFL payload."""
    college = False
    nfl = False
    other: list[str] = []

    for league in _league_objects(payload):
        slug = str(league.get("slug") or "").strip().lower()
        abbreviation = str(league.get("abbreviation") or "").strip().upper()
        name = str(league.get("name") or "").strip().lower()
        league_id = str(league.get("id") or "").strip()
        if (
            slug in {"college-football", "ncaaf", "cfb"}
            or abbreviation in {"NCAAF", "CFB"}
            or league_id == _CFB_LEAGUE_ID
            or "college football" in name
            or "ncaa" in name
        ):
            college = True
        elif (
            slug == "nfl"
            or abbreviation == "NFL"
            or league_id == _NFL_LEAGUE_ID
            or name == "national football league"
        ):
            nfl = True
        elif slug or abbreviation or league_id:
            other.append(slug or abbreviation.lower() or league_id)

    for uid in _identity_uids(payload):
        for league_id in _UID_LEAGUE.findall(uid):
            if league_id == _CFB_LEAGUE_ID:
                college = True
            elif league_id == _NFL_LEAGUE_ID:
                nfl = True
            else:
                other.append(f"l:{league_id}")

    for href in _identity_hrefs(payload):
        lowered = href.lower()
        if "/college-football/" in lowered or "/ncaaf/" in lowered:
            college = True
        elif "/nfl/" in lowered:
            nfl = True

    if college:
        raise ValueError(
            "ESPN payload is college football (cfb), not NFL. "
            "This adapter maps NFL games only."
        )
    if other and not nfl:
        raise ValueError(f"ESPN payload is {other[0]}, not NFL.")
    if other and nfl:
        raise ValueError(
            f"ESPN payload mixes NFL with {other[0]}. Refusing to map it as nfl."
        )
    if not nfl:
        raise ValueError(
            "ESPN payload is not NFL. The league could not be confirmed as nfl."
        )


def _league_objects(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    found: list[Mapping[str, Any]] = []
    header = payload.get("header")
    if isinstance(header, Mapping) and isinstance(header.get("league"), Mapping):
        found.append(header["league"])
    if isinstance(payload.get("league"), Mapping):
        found.append(payload["league"])
    leagues = payload.get("leagues")
    if isinstance(leagues, list):
        found.extend(item for item in leagues if isinstance(item, Mapping))
    return found


def _identity_uids(payload: Mapping[str, Any]) -> list[str]:
    """Uids that identify the game, not news links buried in the payload."""
    uids: list[str] = []

    def add(obj: object) -> None:
        if isinstance(obj, Mapping) and isinstance(obj.get("uid"), str):
            uids.append(obj["uid"])

    add(payload)
    header = payload.get("header")
    if isinstance(header, Mapping):
        add(header)
        add(header.get("league"))
    for competition in _competitions(payload):
        add(competition)
        competitors = competition.get("competitors")
        if not isinstance(competitors, list):
            continue
        for side in competitors:
            if not isinstance(side, Mapping):
                continue
            add(side)
            add(side.get("team"))
    return uids


def _identity_hrefs(payload: Mapping[str, Any]) -> list[str]:
    hrefs: list[str] = []

    def add_links(obj: object) -> None:
        if not isinstance(obj, Mapping) or not isinstance(obj.get("links"), list):
            return
        for link in obj["links"]:
            if isinstance(link, Mapping) and isinstance(link.get("href"), str):
                hrefs.append(link["href"])

    add_links(payload)
    add_links(payload.get("header"))
    for competition in _competitions(payload):
        add_links(competition)
    return hrefs


def _competitions(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = payload.get("competitions")
    if not isinstance(raw, list):
        header = payload.get("header")
        raw = header.get("competitions") if isinstance(header, Mapping) else None
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _competition(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    competitions = _competitions(payload)
    if not competitions:
        raise ValueError("ESPN payload is missing a competition")
    return competitions[0]


def _summary_states(
    summary: Mapping[str, Any],
    header: Mapping[str, Any],
    competition: Mapping[str, Any],
    prior_home: float | None,
    density: str,
) -> list[GameState]:
    home, away, final_home, final_away = _competitors(competition)
    espn_state, status_period, status_display = _status_parts(
        _status_block(competition, header)
    )
    prior = _resolve_prior(summary, prior_home)
    game_id = _event_id(header, competition)
    game_date = _game_date(header, competition)
    states: list[GameState] = []
    previous_as_of: datetime | None = None

    def emit(
        *,
        period: int,
        period_seconds: int,
        home_score: int,
        away_score: int,
        status: str,
        when: datetime,
        spot: Mapping[str, Any] | None = None,
        possessing_id: object | None = None,
        synthetic: bool = False,
    ) -> None:
        nonlocal previous_as_of
        if synthetic:
            # Quarter starts and the final whistle have no play of their own.
            stamped = (
                when
                if previous_as_of is None
                else previous_as_of + timedelta(seconds=1)
            )
        else:
            stamped = when
            if previous_as_of is not None and stamped <= previous_as_of:
                stamped = previous_as_of + timedelta(seconds=1)
        state = _build(
            game_id=game_id,
            home=home,
            away=away,
            home_score=home_score,
            away_score=away_score,
            period=period,
            period_seconds=period_seconds,
            status=status,
            prior=prior,
            as_of=stamped,
            spot=spot,
            possessing_id=possessing_id,
        )
        # situation density drops only an identical clock, score, and situation.
        # all density keeps every play.
        if density != "all" and states and _same_moment(
            states[-1], state, situation=density == "situation"
        ):
            return
        previous_as_of = stamped
        states.append(state)

    # Q1 kickoff is the pre snapshot. Later periods get their own start.
    emit(
        period=1,
        period_seconds=NFL_CONFIG.period_seconds,
        home_score=0,
        away_score=0,
        status="pre",
        when=game_date,
    )

    last_home, last_away = 0, 0
    started = {1}
    two_minute_done: set[int] = set()
    last_clock: dict[int, int] = {}
    plays = _listed_plays(summary) if density == "all" else _plays(summary)

    for play in plays:
        period = _play_period(play)
        if period is None:
            continue
        clock = _play_clock_seconds(play)
        when = _parse_time(play.get("wallclock") or play.get("modified")) or game_date
        spot = _play_spot(play)
        possessing = _play_possession_id(spot)
        entered_home, entered_away = last_home, last_away
        scores = _play_scores(play)
        if scores is None:
            scores = (entered_home, entered_away)

        if density in {"scoring", "situation"}:
            for quarter in range(max(started) + 1, period + 1):
                started.add(quarter)
                emit(
                    period=quarter,
                    period_seconds=_period_length(quarter),
                    home_score=entered_home,
                    away_score=entered_away,
                    status="live",
                    when=when,
                    synthetic=True,
                )
        else:
            started.add(period)

        if density == "scoring" and _has_two_minute(period) and period not in two_minute_done:
            previous_clock = last_clock.get(period)
            crosses = previous_clock is not None and previous_clock > 120 >= clock
            lands = clock == 120 and (previous_clock is None or previous_clock > 120)
            if crosses or lands:
                emit(
                    period=period,
                    period_seconds=120,
                    home_score=entered_home,
                    away_score=entered_away,
                    status="live",
                    when=when,
                    spot=spot if lands else None,
                    possessing_id=possessing if lands else None,
                )
                two_minute_done.add(period)

        reported = _play_scores(play)
        keep_play = density == "all" or (
            density == "situation"
            and _situation_complete(spot, possessing, home, away)
        )
        score_changed = reported is not None and reported != (entered_home, entered_away)
        if keep_play or (density == "scoring" and score_changed):
            emit(
                period=period,
                period_seconds=clock,
                home_score=scores[0],
                away_score=scores[1],
                status="live",
                when=when,
                spot=spot if keep_play or score_changed else None,
                possessing_id=possessing if keep_play or score_changed else None,
            )
        if reported is not None:
            last_home, last_away = reported
        last_clock[period] = clock

    if espn_state == "post":
        # A finished summary often omits period and displayClock.
        final_period = status_period or (
            max(started) if started else NFL_CONFIG.regulation_periods
        )
        final_clock = 0 if status_display is None else _parse_clock(status_display)
        emit(
            period=final_period,
            period_seconds=final_clock,
            home_score=final_home,
            away_score=final_away,
            status="final",
            when=game_date,
            synthetic=True,
        )
    elif espn_state == "in":
        if status_period is None or status_display is None:
            raise ValueError("ESPN live status is missing a period clock")
        now_clock = _parse_clock(status_display)
        situation = competition.get("situation")
        spot = situation if isinstance(situation, Mapping) else None
        possessing = spot.get("possession") if spot is not None else None
        emit(
            period=status_period,
            period_seconds=now_clock,
            home_score=final_home,
            away_score=final_away,
            status="live",
            when=_event_as_of(header, competition),
            spot=spot,
            possessing_id=possessing,
        )
    return states


def _same_moment(left: GameState, right: GameState, *, situation: bool) -> bool:
    same_clock_score = (
        left.period == right.period
        and left.seconds_remaining_period == right.seconds_remaining_period
        and left.home_score == right.home_score
        and left.away_score == right.away_score
        and left.status == right.status
    )
    if not situation:
        return same_clock_score
    return same_clock_score and (
        left.possession == right.possession
        and left.down == right.down
        and left.distance == right.distance
        and left.yardline == right.yardline
    )


def _situation_complete(
    spot: Mapping[str, Any] | None,
    possessing_id: object | None,
    home: _Side,
    away: _Side,
) -> bool:
    fields = _football_fields(spot, possessing_id, home, away)
    return all(name in fields for name in ("possession", "down", "distance", "yardline"))


def _listed_plays(summary: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Every play on drives.previous, plus a top-level plays list."""
    ordered: list[Mapping[str, Any]] = []
    seen: set[str] = set()

    def add(play: object) -> None:
        if not isinstance(play, Mapping):
            return
        play_id = play.get("id")
        if play_id is not None:
            key = str(play_id)
            if key in seen:
                return
            seen.add(key)
        ordered.append(play)

    drives = summary.get("drives")
    if isinstance(drives, Mapping) and isinstance(drives.get("previous"), list):
        for drive in drives["previous"]:
            if isinstance(drive, Mapping) and isinstance(drive.get("plays"), list):
                for play in drive["plays"]:
                    add(play)
    if isinstance(summary.get("plays"), list):
        for play in summary["plays"]:
            add(play)
    ordered.sort(key=_play_sort_key)
    return ordered


def _plays(summary: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    ordered: list[Mapping[str, Any]] = []
    seen: set[str] = set()

    def add(play: object) -> None:
        if not isinstance(play, Mapping):
            return
        play_id = play.get("id")
        if play_id is not None:
            key = str(play_id)
            if key in seen:
                return
            seen.add(key)
        ordered.append(play)

    drives = summary.get("drives")
    if isinstance(drives, Mapping):
        previous = drives.get("previous")
        if isinstance(previous, list):
            for drive in previous:
                if isinstance(drive, Mapping) and isinstance(drive.get("plays"), list):
                    for play in drive["plays"]:
                        add(play)
        current = drives.get("current")
        if isinstance(current, Mapping) and isinstance(current.get("plays"), list):
            for play in current["plays"]:
                add(play)
    # Some summaries list every play on the drives. Others use a top-level list.
    if isinstance(summary.get("plays"), list):
        for play in summary["plays"]:
            add(play)
    scoring = summary.get("scoringPlays")
    if isinstance(scoring, list):
        for play in scoring:
            add(play)
    ordered.sort(key=_play_sort_key)
    return ordered


def _play_sort_key(play: Mapping[str, Any]) -> tuple[int, int, int]:
    period = _play_period(play) or 0
    clock = _play_clock_seconds(play)
    raw = play.get("sequenceNumber")
    try:
        sequence = int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        sequence = 0
    return (period, -clock, sequence)


def _play_period(play: Mapping[str, Any]) -> int | None:
    period = play.get("period")
    number = period.get("number") if isinstance(period, Mapping) else period
    parsed = _whole_number(number)
    if parsed is None or parsed < 1:
        return None
    return parsed


def _play_clock_seconds(play: Mapping[str, Any]) -> int:
    clock = play.get("clock")
    if isinstance(clock, Mapping):
        display = clock.get("displayValue")
        if isinstance(display, str) and display.strip():
            return _parse_clock(display)
        value = _whole_number(clock.get("value"))
        if value is not None and value >= 0:
            return value
    if isinstance(clock, str) and clock.strip():
        return _parse_clock(clock)
    return 0


def _play_scores(play: Mapping[str, Any]) -> tuple[int, int] | None:
    if "homeScore" not in play or "awayScore" not in play:
        return None
    return _score(play.get("homeScore")), _score(play.get("awayScore"))


def _play_spot(play: Mapping[str, Any]) -> Mapping[str, Any] | None:
    start = play.get("start") if isinstance(play.get("start"), Mapping) else None
    if start is None and not _has_timeout_pair(play):
        return None
    if start is None:
        return play
    if _timeouts(start) is None and _has_timeout_pair(play):
        merged = dict(start)
        merged["homeTimeouts"] = play.get("homeTimeouts")
        merged["awayTimeouts"] = play.get("awayTimeouts")
        return merged
    return start


def _play_possession_id(spot: Mapping[str, Any] | None) -> object | None:
    """Possession comes from the play start or situation, not a bare play team."""
    if not isinstance(spot, Mapping):
        return None
    team = spot.get("team")
    if isinstance(team, Mapping) and team.get("id") is not None:
        return team.get("id")
    if spot.get("possession") is not None:
        return spot.get("possession")
    return None


def _has_two_minute(period: int) -> bool:
    # Regulation warnings are at the end of each half. Overtime has one too.
    return period in {2, 4} or period > NFL_CONFIG.regulation_periods


def _build(
    *,
    game_id: str,
    home: _Side,
    away: _Side,
    home_score: int,
    away_score: int,
    period: int,
    period_seconds: int,
    status: str,
    prior: float,
    as_of: datetime,
    spot: Mapping[str, Any] | None,
    possessing_id: object | None,
) -> GameState:
    period_clock, total_clock = _remaining_pair(period, period_seconds)
    optional = _football_fields(spot, possessing_id, home, away)
    return GameState(
        sport="nfl",
        game_id=game_id,
        home=home.name,
        away=away.name,
        home_score=home_score,
        away_score=away_score,
        period=period,
        seconds_remaining_period=period_clock,
        seconds_remaining_total=total_clock,
        status=status,  # type: ignore[arg-type]
        source="espn",
        as_of=as_of,
        prior_home=prior,
        **optional,
    )


def _football_fields(
    spot: Mapping[str, Any] | None,
    possessing_id: object | None,
    home: _Side,
    away: _Side,
) -> dict[str, Any]:
    """Optional football fields. Missing situation keys are left unset."""
    fields: dict[str, Any] = {}
    blob: Mapping[str, Any] = spot if isinstance(spot, Mapping) else {}
    side = _possession_side(possessing_id, home, away)
    if side is not None:
        fields["possession"] = side
    down = _whole_number(blob.get("down"))
    if down is not None and down >= 1:
        fields["down"] = down
    distance = _whole_number(blob.get("distance"))
    if distance is not None and distance >= 0:
        fields["distance"] = distance
    abbreviation = home.abbreviation if side == "home" else None
    if side == "away":
        abbreviation = away.abbreviation
    yardline = _yards_from_own_goal(blob, abbreviation)
    if yardline is not None:
        fields["yardline"] = yardline
    timeouts = _timeouts(blob)
    if timeouts is not None:
        fields["timeouts"] = timeouts
    return fields


def _possession_side(
    team_id: object, home: _Side, away: _Side
) -> str | None:
    if team_id is None:
        return None
    token = str(team_id)
    if token == home.id:
        return "home"
    if token == away.id:
        return "away"
    return None


def _yards_from_own_goal(
    spot: Mapping[str, Any], possessing_abbr: str | None
) -> int | None:
    """Yards from the possessing team's own goal, in 1..99.

    ``yardsToEndzone`` is yards from the spot to the opponent's goal, so the
    own-goal line is 100 minus that value. A bare ``yardLine`` is the field
    marker named by ``possessionText`` (``HBR 25`` is Harbor's 25).
    """
    yards_to_endzone = _whole_number(spot.get("yardsToEndzone"))
    if yards_to_endzone is not None:
        own = 100 - yards_to_endzone
        if 1 <= own <= 99:
            return own
        return None

    marker = _whole_number(spot.get("yardLine"))
    side, text_number = _parse_spot_text(
        spot.get("possessionText"), spot.get("downDistanceText")
    )
    if text_number == 50 or (
        isinstance(side, str) and side.upper() in {"50", "MID", "MIDFIELD"}
    ):
        return 50
    number = text_number if text_number is not None else marker
    if number is None:
        return None
    if side and possessing_abbr:
        own = number if side.upper() == possessing_abbr.upper() else 100 - number
        if 1 <= own <= 99:
            return own
        return None
    # No side name. A value above 50 is not a yard marker.
    if marker is not None and 51 <= marker <= 99:
        return marker
    if marker == 50:
        return 50
    return None


def _parse_spot_text(*values: object) -> tuple[str | None, int | None]:
    for value in values:
        if not isinstance(value, str):
            continue
        match = _AT_SPOT.search(value)
        if match:
            return match.group(1), int(match.group(2))
        match = _TEAM_SPOT.search(value)
        if match:
            return match.group(1), int(match.group(2))
        if _MIDFIELD.search(value):
            return "50", 50
    return None, None


def _timeouts(spot: Mapping[str, Any]) -> dict[str, int] | None:
    home = spot.get("homeTimeouts")
    away = spot.get("awayTimeouts")
    if home is None or away is None:
        nested = spot.get("timeouts")
        if isinstance(nested, Mapping):
            home = nested.get("home")
            away = nested.get("away")
    if not _has_number(home) or not _has_number(away):
        return None
    home_n = _whole_number(home)
    away_n = _whole_number(away)
    if home_n is None or away_n is None or home_n < 0 or away_n < 0:
        return None
    return {"home": home_n, "away": away_n}


def _has_timeout_pair(play: Mapping[str, Any]) -> bool:
    return _has_number(play.get("homeTimeouts")) and _has_number(
        play.get("awayTimeouts")
    )


def _has_number(value: object) -> bool:
    return _whole_number(value) is not None


def _competitors(
    competition: Mapping[str, Any],
) -> tuple[_Side, _Side, int, int]:
    raw = competition.get("competitors")
    if not isinstance(raw, list):
        raise ValueError("ESPN competition is missing competitors")
    home: tuple[_Side, int] | None = None
    away: tuple[_Side, int] | None = None
    for side in raw:
        if not isinstance(side, Mapping):
            continue
        label = str(side.get("homeAway") or "").lower()
        parsed = _side(side)
        score = _score(side.get("score"))
        if label == "home":
            home = (parsed, score)
        elif label == "away":
            away = (parsed, score)
    if home is None or away is None:
        raise ValueError("ESPN competition is missing a home or away competitor")
    return home[0], away[0], home[1], away[1]


def _side(competitor: Mapping[str, Any]) -> _Side:
    team = competitor.get("team")
    team_map = team if isinstance(team, Mapping) else {}
    name = ""
    for key in ("abbreviation", "shortDisplayName", "displayName", "name", "location"):
        value = team_map.get(key)
        if isinstance(value, str) and value.strip():
            name = value.strip()
            break
    team_id = team_map.get("id", competitor.get("id"))
    if team_id is None:
        raise ValueError("ESPN competitor is missing a team id")
    if not name:
        name = str(team_id)
    abbreviation = team_map.get("abbreviation")
    abbr = abbreviation.strip() if isinstance(abbreviation, str) else None
    if abbr == "":
        abbr = None
    return _Side(id=str(team_id), name=name, abbreviation=abbr)


def _status_block(
    competition: Mapping[str, Any], fallback: Mapping[str, Any]
) -> Mapping[str, Any]:
    status = competition.get("status")
    if isinstance(status, Mapping):
        return status
    status = fallback.get("status")
    if isinstance(status, Mapping):
        return status
    raise ValueError("ESPN payload is missing a status")


def _status_parts(
    status: Mapping[str, Any],
) -> tuple[str, int | None, str | None]:
    """Map ESPN status to a state, period, and display clock.

    A final summary may omit period and displayClock. Callers then use the
    last play's period and 0:00.
    """
    kind = status.get("type")
    if not isinstance(kind, Mapping):
        raise ValueError("ESPN status is missing a type")
    espn_state = str(kind.get("state") or "").lower()
    if espn_state not in _OUR_STATUS:
        raise ValueError(f"ESPN status {espn_state!r} is not pre, in, or post")
    period = _whole_number(status.get("period"))
    if period is not None and period < 1:
        period = None
    raw_display = status.get("displayClock")
    if isinstance(raw_display, str) and raw_display.strip():
        display: str | None = raw_display
    elif status.get("clock") is not None and espn_state != "post":
        display = _seconds_to_display(_whole_number(status.get("clock")) or 0)
    else:
        display = None
    if espn_state == "pre":
        return "pre", 1, _seconds_to_display(NFL_CONFIG.period_seconds)
    if espn_state != "post" and period is None:
        raise ValueError("ESPN status period must be >= 1 once the game has started")
    return espn_state, period, display


def _period_length(period: int) -> int:
    if period <= NFL_CONFIG.regulation_periods:
        return NFL_CONFIG.period_seconds
    return NFL_CONFIG.ot_period_seconds


def _remaining_pair(period: int, period_seconds: int) -> tuple[int, int]:
    length = _period_length(period)
    remaining = max(0, min(int(period_seconds), length))
    if period <= NFL_CONFIG.regulation_periods:
        after = (NFL_CONFIG.regulation_periods - period) * NFL_CONFIG.period_seconds
        return remaining, remaining + after
    return remaining, remaining


def _resolve_prior(payload: Mapping[str, Any], prior_home: float | None) -> float:
    odds = _home_american_odds(payload)
    if odds is not None:
        return _american_implied(odds)
    if prior_home is not None:
        return float(prior_home)
    return DEFAULT_PRIOR_HOME


def _american_implied(odds: int) -> float:
    if odds == 0:
        raise ValueError("American moneyline of 0 cannot be converted")
    if odds > 0:
        return 100.0 / (odds + 100.0)
    magnitude = -odds
    return magnitude / (magnitude + 100.0)


def _home_american_odds(payload: Mapping[str, Any]) -> int | None:
    for entries in _odds_lists(payload):
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            odds = _moneyline_from_entry(entry)
            if odds is not None and odds != 0:
                return odds
    return None


def _odds_lists(payload: Mapping[str, Any]) -> list[list[object]]:
    found: list[list[object]] = []

    def take(obj: object) -> None:
        if not isinstance(obj, Mapping):
            return
        for key in ("odds", "pickcenter"):
            value = obj.get(key)
            if isinstance(value, list):
                found.append(value)

    take(payload)
    take(payload.get("header"))
    for competition in _competitions(payload):
        take(competition)
    return found


def _moneyline_from_entry(entry: Mapping[str, Any]) -> int | None:
    home_team = entry.get("homeTeamOdds")
    if isinstance(home_team, Mapping):
        for key in ("moneyLine", "moneyline"):
            parsed = _parse_american(home_team.get(key))
            if parsed is not None:
                return parsed
    moneyline = entry.get("moneyline")
    if isinstance(moneyline, Mapping):
        home = moneyline.get("home")
        if isinstance(home, Mapping):
            for book in ("close", "open"):
                price = home.get(book)
                if isinstance(price, Mapping):
                    parsed = _parse_american(price.get("odds"))
                    if parsed is not None:
                        return parsed
            parsed = _parse_american(home.get("odds"))
            if parsed is not None:
                return parsed
        parsed = _parse_american(home)
        if parsed is not None:
            return parsed
    return None


def _parse_american(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip().upper().replace("−", "-").replace("+", "")
        if text in {"", "EVEN", "PK", "PICK"}:
            return 100 if text in {"EVEN", "PK", "PICK"} else None
        try:
            number = float(text)
        except ValueError:
            return None
        if number.is_integer():
            return int(number)
    return None


def _event_id(event_like: Mapping[str, Any], competition: Mapping[str, Any]) -> str:
    for source in (event_like, competition):
        raw = source.get("id")
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    raise ValueError("ESPN payload is missing an event id")


def _game_date(event_like: Mapping[str, Any], competition: Mapping[str, Any]) -> datetime:
    for source in (competition, event_like):
        parsed = _parse_time(source.get("date"))
        if parsed is not None:
            return parsed
    raise ValueError("ESPN payload is missing a game date")


def _event_as_of(event_like: Mapping[str, Any], competition: Mapping[str, Any]) -> datetime:
    situation = competition.get("situation")
    if isinstance(situation, Mapping):
        last = situation.get("lastPlay")
        if isinstance(last, Mapping):
            parsed = _parse_time(last.get("wallclock") or last.get("modified"))
            if parsed is not None:
                return parsed
    return _game_date(event_like, competition)


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _score(value: object) -> int:
    if value is None or value == "":
        return 0
    parsed = _whole_number(value)
    if parsed is None or parsed < 0:
        raise ValueError(f"ESPN score {value!r} is not a non-negative int")
    return parsed


def _whole_number(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        if number.is_integer():
            return int(number)
    return None


def _parse_clock(value: object) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"cannot read ESPN clock {value!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not float(value).is_integer():
            value = int(value)
        seconds = int(value)
        if seconds < 0:
            raise ValueError(f"cannot read ESPN clock {value!r}")
        return seconds
    if not isinstance(value, str):
        raise ValueError(f"cannot read ESPN clock {value!r}")
    text = value.strip()
    parts = text.split(":")
    try:
        numbers = [int(float(part)) for part in parts]
    except ValueError as exc:
        raise ValueError(f"cannot read ESPN clock {value!r}") from exc
    if len(numbers) == 1:
        seconds = numbers[0]
    elif len(numbers) == 2:
        seconds = numbers[0] * 60 + numbers[1]
    elif len(numbers) == 3:
        seconds = numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    else:
        raise ValueError(f"cannot read ESPN clock {value!r}")
    if seconds < 0:
        raise ValueError(f"cannot read ESPN clock {value!r}")
    return seconds


def _seconds_to_display(seconds: int) -> str:
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes}:{remainder:02d}"
