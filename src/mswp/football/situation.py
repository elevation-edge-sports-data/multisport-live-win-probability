"""Handwritten expected points for one snap. This is not nflfastR WPA.

``yardline`` is yards from the possessing team's own goal: 1 is backed up,
99 is the opponent's 1. The backbone is a 1st-and-10 field-position curve.
Down and distance only nudge that value. Third and fourth and long are
worth less. Short yardage and goal-to-go are worth more.
"""

from __future__ import annotations


def expected_points(down: int, distance: int, yardline: int) -> float:
    """Expected points for the possessing team at this snap.

    The curve is piecewise and written by hand. It is not a fitted table.
    """
    return _field_position(yardline) + _down_distance_nudge(down, distance, yardline)


def _field_position(yardline: int) -> float:
    """About -1.2 at the own 1, +1.8 at midfield, +6.0 at the opponent 1."""
    if yardline <= 50:
        return -1.2 + (yardline - 1) * (3.0 / 49.0)
    return 1.8 + (yardline - 50) * (4.2 / 49.0)


def _down_distance_nudge(down: int, distance: int, yardline: int) -> float:
    if down <= 1:
        nudge = 0.2 if distance <= 3 else (0.0 if distance <= 10 else -0.3)
    elif down == 2:
        nudge = 0.4 if distance <= 3 else (-0.45 if distance >= 10 else -0.05)
    elif down == 3:
        nudge = 0.35 if distance <= 2 else (-1.1 if distance >= 8 else -0.5)
    else:
        nudge = 0.15 if distance <= 2 else (-1.6 if distance >= 8 else -0.8)
    yards_to_goal = 100 - yardline
    if yards_to_goal <= 10 and distance <= yards_to_goal and down <= 3:
        nudge += 0.5
    return nudge
