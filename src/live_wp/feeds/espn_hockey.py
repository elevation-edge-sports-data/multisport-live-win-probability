"""Map a saved ESPN NHL summary to GameState snapshots.

ESPN hockey clocks on this payload are elapsed period time.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from live_wp.feeds.espn import home_moneyline_prior
from mswp import DEFAULT_PRIOR_HOME, GameState
from mswp.hockey.config import NHL_CONFIG


def load_summary(path: Path | str) -> Mapping[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("ESPN summary must be a JSON object")
    return payload


def events_from_espn_hockey(
    payload: Mapping[str, Any],
    *,
    prior_home: float | None = None,
) -> list[GameState]:
    header = payload.get("header")
    if not isinstance(header, Mapping):
        raise ValueError("ESPN hockey summary is missing header")
    competitions = header.get("competitions")
    if not isinstance(competitions, list) or not competitions:
        raise ValueError("ESPN hockey summary is missing competitions")
    competition = competitions[0]
    home, away, home_id, away_id = _teams(competition)
    game_id = str(header.get("id") or "unknown")
    prior = home_moneyline_prior(payload)
    if prior is None:
        prior = prior_home if prior_home is not None else DEFAULT_PRIOR_HOME
    plays = payload.get("plays")
    if not isinstance(plays, list) or not plays:
        raise ValueError("ESPN hockey summary has no plays")

    as_of = datetime(2022, 6, 1, tzinfo=timezone.utc)
    boxes: list[tuple[str, int, int]] = []  # side, period, expire_elapsed
    states: list[GameState] = []
    period_len = NHL_CONFIG.period_seconds

    for index, raw in enumerate(plays):
        if not isinstance(raw, Mapping):
            continue
        period_block = raw.get("period") if isinstance(raw.get("period"), Mapping) else {}
        period = int(period_block.get("number") or 1)
        clock = raw.get("clock") if isinstance(raw.get("clock"), Mapping) else {}
        elapsed = _parse_clock(str(clock.get("displayValue") or "0:00"))
        elapsed = min(max(elapsed, 0), period_len)
        typ = str((raw.get("type") or {}).get("text") or "")
        if typ == "Period Start":
            carried = []
            for side, box_period, expire in boxes:
                leftover = expire - period_len
                if box_period == period - 1 and leftover > 0:
                    carried.append((side, period, leftover))
            boxes = carried
            elapsed = 0
        boxes = [
            box
            for box in boxes
            if box[1] > period or (box[1] == period and box[2] > elapsed)
        ]
        if typ == "Penalty":
            team = raw.get("team") if isinstance(raw.get("team"), Mapping) else {}
            ident = str(team.get("id") or "")
            side = "home" if ident == home_id else "away"
            boxes.append((side, period, elapsed + 120))
        strength, extra = _boxes_to_strength(boxes)
        label = (raw.get("strength") or {}).get("text") if isinstance(raw.get("strength"), Mapping) else ""
        if label == "Power Play" and strength == "5v5":
            # fallback if the box tracker missed the call
            team = raw.get("team") if isinstance(raw.get("team"), Mapping) else {}
            ident = str(team.get("id") or "")
            strength = "5v4" if ident == home_id else "4v5"
        period_left = period_len - elapsed
        if period <= 3:
            total_left = (3 - period) * period_len + period_left
        else:
            total_left = period_left
        home_score = int(raw.get("homeScore") or 0)
        away_score = int(raw.get("awayScore") or 0)
        status = "live"
        if index == 0 and home_score == 0 and away_score == 0:
            status = "pre"
        if typ in {"End of Game"} or (
            index == len(plays) - 1 and home_score != away_score
        ):
            status = "final"
        if typ == "Goal":
            team = raw.get("team") if isinstance(raw.get("team"), Mapping) else {}
            ident = str(team.get("id") or "")
            scored_home = ident == home_id
            boxes = [b for b in boxes if b[0] != ("away" if scored_home else "home")]
        states.append(
            GameState(
                sport="nhl",
                game_id=game_id,
                home=home,
                away=away,
                home_score=home_score,
                away_score=away_score,
                period=max(period, 1),
                seconds_remaining_period=period_left,
                seconds_remaining_total=max(total_left, 0),
                status=status,  # type: ignore[arg-type]
                source="espn-summary",
                as_of=as_of,
                prior_home=prior,
                strength=strength,
                extra_attacker=extra,
            )
        )
    return states


def _teams(competition: Mapping[str, Any]) -> tuple[str, str, str, str]:
    home = away = home_id = away_id = ""
    for row in competition.get("competitors") or []:
        if not isinstance(row, Mapping):
            continue
        team = row.get("team") if isinstance(row.get("team"), Mapping) else {}
        abbr = str(team.get("abbreviation") or "")
        ident = str(team.get("id") or "")
        if row.get("homeAway") == "home":
            home, home_id = abbr, ident
        elif row.get("homeAway") == "away":
            away, away_id = abbr, ident
    return home, away, home_id, away_id


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


def _boxes_to_strength(boxes: list[tuple[str, int, int]]) -> tuple[str, bool]:
    home_down = sum(1 for side, _p, _e in boxes if side == "home")
    away_down = sum(1 for side, _p, _e in boxes if side == "away")
    return f"{max(3, 5 - home_down)}v{max(3, 5 - away_down)}", False
