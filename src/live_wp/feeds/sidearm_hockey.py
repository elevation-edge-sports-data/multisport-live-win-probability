"""NCAA LiveStats / Sidearm hockey gamebook text (pdftotext -layout)."""

from __future__ import annotations

import re
from pathlib import Path

from mswp import GameState
from mswp.hockey.config import NCAAH_CONFIG

_CLOCK = re.compile(r"\[(\d{1,2}:\d{2}(?:\.\d+)?)\]\s*(.*)$")
_START = re.compile(r"Start of (\d)(?:st|nd|rd|th) (period|overtime period)", re.I)
_END = re.compile(r"End of period", re.I)
_PENALTY = re.compile(r"Penalty on .+? (DEN|MIC|MICH) (\d+) minutes", re.I)
_GOAL = re.compile(r"GOAL by (Denver|Michigan)", re.I)


def load_gamebook_text(path: Path | str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def events_from_gamebook_text(
    text: str,
    *,
    home: str = "DEN",
    away: str = "MICH",
    prior_home: float = 0.45,
    game_id: str = "15520",
) -> list[GameState]:
    from datetime import datetime, timezone

    marker = re.search(r"Play By Play", text, re.I)
    body = text[marker.start() :] if marker else text
    joined: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _CLOCK.search(line) or _START.search(line) or line.startswith("Play"):
            joined.append(line)
        elif joined:
            joined[-1] = joined[-1] + " " + line

    period = 1
    home_score = 0
    away_score = 0
    boxes: list[tuple[str, int, int]] = []
    events: list[tuple] = []
    for line in joined:
        clock_match = _CLOCK.search(line)
        if clock_match is None:
            continue
        elapsed = _elapsed(clock_match.group(1))
        action = clock_match.group(2).strip()
        kind = _kind(action)
        if kind == "period-start":
            new_period = _period_from_start(action, period)
            if new_period != period:
                carried = []
                for side, box_period, expire in boxes:
                    leftover = expire - 20 * 60
                    if box_period == period and leftover > 0:
                        carried.append((side, new_period, leftover))
                boxes = carried
            period = new_period
            elapsed = 0
        boxes = [
            box
            for box in boxes
            if box[1] > period or (box[1] == period and box[2] > elapsed)
        ]
        if kind == "penalty":
            pen = _PENALTY.search(action)
            if pen:
                code = pen.group(1).upper()
                minutes = int(pen.group(2))
                side = "home" if code == "DEN" else "away"
                boxes.append((side, period, elapsed + minutes * 60))
        strength = _boxes_to_strength(boxes)
        if kind == "goal":
            match = _GOAL.search(action)
            if match and "denver" in match.group(1).lower():
                home_score += 1
                boxes = [b for b in boxes if b[0] != "away"]
            elif match:
                away_score += 1
                boxes = [b for b in boxes if b[0] != "home"]
        events.append((period, elapsed, kind, home_score, away_score, strength, action))

    config = NCAAH_CONFIG
    stamp = datetime(2026, 4, 10, tzinfo=timezone.utc)
    states: list[GameState] = []
    for index, (period, elapsed, kind, hs, aws, strength, action) in enumerate(events):
        period_len = (
            config.period_seconds if period <= 3 else config.ot_period_seconds
        )
        elapsed = min(elapsed, period_len)
        period_left = period_len - elapsed
        if period <= 3:
            total_left = (3 - period) * config.period_seconds + period_left
        else:
            total_left = period_left
        status = "live"
        if index == 0:
            status = "pre"
        last = index == len(events) - 1
        if kind == "game-end" or (last and hs != aws):
            status = "final"
        states.append(
            GameState(
                sport="ncaah",
                game_id=game_id,
                home=home,
                away=away,
                home_score=hs,
                away_score=aws,
                period=period,
                seconds_remaining_period=period_left,
                seconds_remaining_total=max(total_left, 0),
                status=status,  # type: ignore[arg-type]
                source="sidearm-gamebook",
                as_of=stamp,
                prior_home=prior_home,
                strength=strength,
            )
        )
    if states and states[-1].status != "final" and states[-1].home_score != states[-1].away_score:
        last = states[-1]
        states.append(
            GameState(
                sport=last.sport,
                game_id=last.game_id,
                home=last.home,
                away=last.away,
                home_score=last.home_score,
                away_score=last.away_score,
                period=last.period,
                seconds_remaining_period=last.seconds_remaining_period,
                seconds_remaining_total=last.seconds_remaining_total,
                status="final",
                source=last.source,
                as_of=last.as_of,
                prior_home=last.prior_home,
                strength="5v5",
            )
        )
    return states


def _elapsed(stamp: str) -> int:
    if "." in stamp:
        stamp = stamp.split(".", 1)[0]
    minutes, _, seconds = stamp.partition(":")
    return int(minutes) * 60 + int(seconds)


def _kind(action: str) -> str:
    if _START.search(action):
        return "period-start"
    if _END.search(action):
        return "period-end"
    if action.upper().startswith("GOAL") or "GOAL by" in action:
        return "goal"
    if action.lower().startswith("penalty on"):
        return "penalty"
    return "other"


def _period_from_start(action: str, current: int) -> int:
    match = _START.search(action)
    if match is None:
        return current
    number = int(match.group(1))
    if "overtime" in match.group(2).lower():
        return 3 + number
    return number


def _boxes_to_strength(boxes: list[tuple[str, int, int]]) -> str:
    home_down = sum(1 for side, _p, _e in boxes if side == "home")
    away_down = sum(1 for side, _p, _e in boxes if side == "away")
    return f"{max(3, 5 - home_down)}v{max(3, 5 - away_down)}"
