"""Skater strength helpers for the hockey pack."""

from __future__ import annotations

import re

from mswp.state import GameState

_STRENGTH = re.compile(r"^(\d+)\s*v\s*(\d+)$", re.I)


def parse_strength(value: str | None) -> tuple[int, int]:
    if value is None or value == "":
        return 5, 5
    match = _STRENGTH.match(value.strip())
    if match is None:
        return 5, 5
    home = max(3, min(6, int(match.group(1))))
    away = max(3, min(6, int(match.group(2))))
    return home, away


def rate_multipliers(state: GameState) -> tuple[float, float]:
    home_skaters, away_skaters = parse_strength(state.strength)
    diff = home_skaters - away_skaters
    home_mult = 1.0
    away_mult = 1.0
    if home_skaters <= 3 and away_skaters <= 3 and diff == 0:
        home_mult = 1.35
        away_mult = 1.35
    elif diff > 0:
        home_mult = 1.0 + 0.75 * diff
        away_mult = max(0.35, 1.0 - 0.30 * diff)
    elif diff < 0:
        step = -diff
        away_mult = 1.0 + 0.75 * step
        home_mult = max(0.35, 1.0 - 0.30 * step)
    if state.extra_attacker and (home_skaters == 6 or away_skaters == 6):
        if home_skaters > away_skaters:
            home_mult *= 1.10
            away_mult *= 4.20
        elif away_skaters > home_skaters:
            away_mult *= 1.10
            home_mult *= 4.20
    return home_mult, away_mult
