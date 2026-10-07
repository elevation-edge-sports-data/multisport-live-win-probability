"""Map a saved ESPN basketball summary to GameState snapshots.

The caller loads the JSON. This module does not fetch.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from live_wp.feeds.espn import DENSITIES, home_moneyline_prior
from mswp import DEFAULT_PRIOR_HOME, GameState
from mswp.basketball.config import NCAAB_CONFIG, NBA_CONFIG
from mswp.config import SportConfig

_NBA_LEAGUE_ID = "46"
_NCAAB_LEAGUE_ID = "41"
_UID_LEAGUE = re.compile(r"(?:^|~)l:(\d+)(?:~|$)")


def load_summary(path: Path | str) -> Mapping[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("ESPN summary must be a JSON object")
    return payload


def is_basketball_summary(payload: Mapping[str, Any]) -> bool:
    """True when the object is an NBA or NCAAB summary with plays."""
    if not isinstance(payload, Mapping):
        return False
    if not isinstance(payload.get("header"), Mapping):
        return False
    if not isinstance(payload.get("plays"), list):
        return False
    return classify_basketball(payload) in {"nba", "ncaab"}


def classify_basketball(payload: Mapping[str, Any]) -> str | None:
    """Return ``nba``, ``ncaab``, or None. A mixed payload returns None."""
    if not isinstance(payload, Mapping):
        return None
    nba = False
    ncaab = False

    def mark(slug: str, abbreviation: str, league_id: str) -> None:
        nonlocal nba, ncaab
        if (
            slug in {"mens-college-basketball", "ncaab"}
            or abbreviation in {"NCAAB", "NCAAM"}
            or league_id == _NCAAB_LEAGUE_ID
        ):
            ncaab = True
        elif slug == "nba" or abbreviation == "NBA" or league_id == _NBA_LEAGUE_ID:
            nba = True

    for league in _league_rows(payload):
        mark(
            str(league.get("slug") or "").strip().lower(),
            str(league.get("abbreviation") or "").strip().upper(),
            str(league.get("id") or "").strip(),
        )
    for uid in _identity_uids(payload):
        for league_id in _UID_LEAGUE.findall(uid):
            if league_id == _NCAAB_LEAGUE_ID:
                ncaab = True
            elif league_id == _NBA_LEAGUE_ID:
                nba = True
    for href in _identity_hrefs(payload):
        lowered = href.lower()
        if "mens-college-basketball" in lowered or "/ncaab/" in lowered:
            ncaab = True
        elif "/nba/" in lowered or "/basketball/nba" in lowered:
            nba = True
    if nba and ncaab:
        return None
    if ncaab:
        return "ncaab"
    if nba:
        return "nba"
    return None


def require_nba_payload(payload: Mapping[str, Any]) -> None:
    """Raise unless this payload is confirmed NBA. This does not fetch."""
    if not isinstance(payload, Mapping):
        raise TypeError("ESPN payload must be an object")
    sport = classify_basketball(payload)
    if sport == "ncaab":
        raise ValueError(
            "ESPN payload is college basketball (ncaab), not NBA. "
            "This adapter maps NBA games only."
        )
    if sport != "nba":
        raise ValueError(
            "ESPN payload is not NBA. The league could not be confirmed as nba."
        )


def scoreboard_event_to_state(
    event: Mapping[str, Any],
    *,
    prior_home: float | None = None,
) -> GameState:
    """One snapshot for an NBA or NCAAB scoreboard event."""
    if not isinstance(event, Mapping):
        raise TypeError("ESPN scoreboard event must be an object")
    sport = classify_basketball(event)
    if sport not in {"nba", "ncaab"}:
        raise ValueError("ESPN payload is not NBA or NCAAB")
    config = NBA_CONFIG if sport == "nba" else NCAAB_CONFIG
    competitions = event.get("competitions")
    if not isinstance(competitions, list) or not competitions:
        raise ValueError("ESPN basketball scoreboard event is missing competitions")
    competition = competitions[0]
    if not isinstance(competition, Mapping):
        raise ValueError("ESPN basketball competition is invalid")
    home, away, home_id, away_id = _teams(competition)
    home_score, away_score = _competitor_scores(competition)
    status_block = competition.get("status")
    if not isinstance(status_block, Mapping):
        raise ValueError("ESPN basketball scoreboard event is missing a status")
    kind = status_block.get("type")
    if not isinstance(kind, Mapping):
        raise ValueError("ESPN status is missing a type")
    espn_state = str(kind.get("state") or "").lower()
    if espn_state not in {"pre", "in", "post"}:
        raise ValueError(f"ESPN status {espn_state!r} is not pre, in, or post")
    period = _whole_period(status_block.get("period"))
    if espn_state == "pre":
        period = 1
    elif period is None:
        period = config.regulation_periods if espn_state == "post" else 1
    period_left = _status_clock(status_block, config, espn_state, period)
    total_left = _total_remaining(period, period_left, config)
    prior = home_moneyline_prior(event)
    if prior is None:
        prior = prior_home if prior_home is not None else DEFAULT_PRIOR_HOME
    game_id = str(event.get("id") or competition.get("id") or "unknown")
    return GameState(
        sport=sport,
        game_id=game_id,
        home=home,
        away=away,
        home_score=home_score,
        away_score=away_score,
        period=max(period, 1),
        seconds_remaining_period=period_left,
        seconds_remaining_total=total_left,
        status={"pre": "pre", "in": "live", "post": "final"}[espn_state],  # type: ignore[arg-type]
        source="espn",
        as_of=_event_as_of(event, competition),
        prior_home=prior,
        possession=_situation_possession(competition, home_id, away_id),
    )


def events_from_espn_basketball(
    payload: Mapping[str, Any],
    *,
    prior_home: float | None = None,
    density: str = "all",
) -> list[GameState]:
    """Play snapshots for one basketball summary.

    ``density="all"`` keeps every play. That is the default so existing
    callers still receive the full list.

    ``density="scoring"`` keeps the opening snapshot, the first play of
    each period, every scoring change, and the final.

    ``density="situation"`` also keeps about one clock sample per minute.
    Basketball plays have no down or distance, so a situation event is a
    change of score, period, or clock.
    """
    if density not in DENSITIES:
        raise ValueError("density must be scoring, situation, or all")
    sport = _sport(payload)
    config = NBA_CONFIG if sport == "nba" else NCAAB_CONFIG
    header = payload.get("header")
    if not isinstance(header, Mapping):
        raise ValueError("ESPN basketball summary is missing header")
    competitions = header.get("competitions")
    if not isinstance(competitions, list) or not competitions:
        raise ValueError("ESPN basketball summary is missing competitions")
    competition = competitions[0]
    if not isinstance(competition, Mapping):
        raise ValueError("ESPN basketball competition is invalid")
    home, away, home_id, away_id = _teams(competition)
    game_id = str(header.get("id") or competition.get("id") or "unknown")
    prior = home_moneyline_prior(payload)
    if prior is None:
        prior = prior_home if prior_home is not None else DEFAULT_PRIOR_HOME
    plays = payload.get("plays")
    if not isinstance(plays, list) or not plays:
        raise ValueError("ESPN basketball summary has no plays")

    as_of = datetime(2024, 4, 1, tzinfo=timezone.utc)
    states: list[GameState] = []
    for index, raw in enumerate(plays):
        if not isinstance(raw, Mapping):
            continue
        period_block = raw.get("period") if isinstance(raw.get("period"), Mapping) else {}
        period = int(period_block.get("number") or 1)
        clock = raw.get("clock") if isinstance(raw.get("clock"), Mapping) else {}
        display = str(clock.get("displayValue") or "0:00")
        period_left = _parse_clock(display)
        total_left = _total_remaining(period, period_left, config)
        home_score = int(raw.get("homeScore") or 0)
        away_score = int(raw.get("awayScore") or 0)
        possession = _possession(raw, home_id, away_id)
        status = "live"
        text = str(raw.get("text") or "").lower()
        if index == 0 and home_score == 0 and away_score == 0:
            status = "pre"
        if "end of game" in text:
            status = "final"
        if index == len(plays) - 1 and home_score != away_score:
            status = "final"
        states.append(
            GameState(
                sport=sport,
                game_id=game_id,
                home=home,
                away=away,
                home_score=home_score,
                away_score=away_score,
                period=max(period, 1),
                seconds_remaining_period=period_left,
                seconds_remaining_total=total_left,
                status=status,  # type: ignore[arg-type]
                source="espn-summary",
                as_of=as_of,
                prior_home=prior,
                possession=possession,
            )
        )
    if not states:
        raise ValueError("ESPN basketball summary produced no snapshots")
    if density == "all":
        return states
    return _select_density(states, density)


def _sport(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(payload.get("header") or {}, default=str).lower()
    if "mens-college-basketball" in blob or "l:41" in blob or '"id": "41"' in blob:
        return "ncaab"
    if "l:46" in blob or '"nba"' in blob or '"id": "46"' in blob:
        return "nba"
    raise ValueError("ESPN payload is not NBA or NCAAB")


def _teams(competition: Mapping[str, Any]) -> tuple[str, str, str, str]:
    home = away = home_id = away_id = ""
    for row in competition.get("competitors") or []:
        if not isinstance(row, Mapping):
            continue
        team = row.get("team") if isinstance(row.get("team"), Mapping) else {}
        abbr = str(team.get("abbreviation") or team.get("shortDisplayName") or "")
        ident = str(team.get("id") or "")
        if row.get("homeAway") == "home":
            home, home_id = abbr, ident
        elif row.get("homeAway") == "away":
            away, away_id = abbr, ident
    if not home or not away:
        raise ValueError("ESPN basketball competition is missing teams")
    return home, away, home_id, away_id


def _possession(play: Mapping[str, Any], home_id: str, away_id: str) -> str | None:
    team = play.get("team")
    if not isinstance(team, Mapping):
        return None
    ident = str(team.get("id") or "")
    if ident and ident == home_id:
        return "home"
    if ident and ident == away_id:
        return "away"
    return None


def _parse_clock(display: str) -> int:
    text = display.strip()
    if ":" not in text:
        try:
            return int(float(text))
        except ValueError:
            return 0
    minutes, _, rest = text.partition(":")
    seconds = rest.split(".")[0]
    try:
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        return 0


def _total_remaining(period: int, period_left: int, config: SportConfig) -> int:
    if period <= config.regulation_periods:
        return max((config.regulation_periods - period) * config.period_seconds + period_left, 0)
    return min(max(period_left, 0), config.ot_period_seconds)


def _select_density(states: list[GameState], density: str) -> list[GameState]:
    kept: list[GameState] = []
    seen_minutes: set[tuple[int, int]] = set()
    previous_score: tuple[int, int] | None = None
    previous_period: int | None = None
    for state in states:
        score = (state.home_score, state.away_score)
        score_changed = previous_score is not None and score != previous_score
        period_start = previous_period is None or state.period != previous_period
        minute_key = (state.period, state.seconds_remaining_period // 60)
        fresh_minute = minute_key not in seen_minutes
        seen_minutes.add(minute_key)
        keep = period_start or score_changed or state.status == "final"
        if density == "situation" and fresh_minute:
            keep = True
        if keep:
            kept.append(state)
        previous_score = score
        previous_period = state.period
    return kept


def _league_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
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
    uids: list[str] = []

    def add(obj: object) -> None:
        if isinstance(obj, Mapping) and isinstance(obj.get("uid"), str):
            uids.append(obj["uid"])

    add(payload)
    header = payload.get("header")
    if isinstance(header, Mapping):
        add(header)
        add(header.get("league"))
    add(payload.get("league"))
    for row in _league_rows(payload):
        add(row)
    for competition in _competitions(payload):
        add(competition)
        for side in competition.get("competitors") or []:
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


def _competitor_scores(competition: Mapping[str, Any]) -> tuple[int, int]:
    home: int | None = None
    away: int | None = None
    for row in competition.get("competitors") or []:
        if not isinstance(row, Mapping):
            continue
        score = int(row.get("score") or 0)
        if row.get("homeAway") == "home":
            home = score
        elif row.get("homeAway") == "away":
            away = score
    if home is None or away is None:
        raise ValueError("ESPN basketball competition is missing teams")
    return home, away


def _situation_possession(
    competition: Mapping[str, Any], home_id: str, away_id: str
) -> str | None:
    situation = competition.get("situation")
    if not isinstance(situation, Mapping) or situation.get("possession") is None:
        return None
    ident = str(situation.get("possession"))
    if ident == home_id:
        return "home"
    if ident == away_id:
        return "away"
    return None


def _whole_period(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        return number if number >= 1 else None
    return None


def _status_clock(
    status: Mapping[str, Any],
    config: SportConfig,
    espn_state: str,
    period: int,
) -> int:
    length = (
        config.period_seconds
        if period <= config.regulation_periods
        else config.ot_period_seconds
    )
    display = status.get("displayClock")
    if isinstance(display, str) and display.strip():
        remaining = _parse_clock(display)
    elif espn_state == "pre":
        remaining = length
    elif espn_state == "post":
        remaining = 0
    else:
        clock = status.get("clock")
        if isinstance(clock, bool) or not isinstance(clock, (int, float)):
            remaining = length
        else:
            remaining = int(clock)
    return min(max(remaining, 0), length)


def _event_as_of(event: Mapping[str, Any], competition: Mapping[str, Any]) -> datetime:
    for source in (competition, event):
        raw = source.get("date")
        if not isinstance(raw, str) or not raw.strip():
            continue
        text = raw.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0)
    return datetime(2024, 4, 1, tzinfo=timezone.utc)
