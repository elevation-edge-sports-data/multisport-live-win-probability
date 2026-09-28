"""Map a saved ESPN basketball summary to GameState snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from live_wp.feeds.espn import home_moneyline_prior
from mswp import DEFAULT_PRIOR_HOME, GameState
from mswp.basketball.config import NCAAB_CONFIG, NBA_CONFIG
from mswp.config import SportConfig


def load_summary(path: Path | str) -> Mapping[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("ESPN summary must be a JSON object")
    return payload


def events_from_espn_basketball(
    payload: Mapping[str, Any],
    *,
    prior_home: float | None = None,
) -> list[GameState]:
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
    return states


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
