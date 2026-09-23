"""Single entry point for every sport."""

from __future__ import annotations

import math
from collections.abc import Callable

from mswp.config import SportConfig
from mswp.football.model import football_win_probability
from mswp.state import GameState

# Live snapshots can still change, so they stay off 0 and 1.
# A decided game (final, or Q4/OT at 0:00 and not tied) is 1.0 or 0.0.
LIVE_WP_FLOOR = 0.0001
LIVE_WP_CEIL = 0.9999

PackFn = Callable[[GameState, float, SportConfig], float]

_PACKS: dict[str, PackFn] = {
    "football": football_win_probability,
}


def _decided_wp(state: GameState, sport_config: SportConfig) -> float | None:
    """1.0 or 0.0 from the score when the winner is fixed.

    ``None`` means the game can still change, including a tie at 0:00 of
    regulation (overtime) or a tie at 0:00 of overtime when another period
    is possible. A final tie is 0.5.
    """
    clock_out = (
        state.period >= sport_config.regulation_periods
        and state.seconds_remaining_period == 0
        and state.seconds_remaining_total == 0
    )
    if state.status != "final" and not clock_out:
        return None
    if state.home_score > state.away_score:
        return 1.0
    if state.home_score < state.away_score:
        return 0.0
    if state.status == "final":
        return 0.5
    return None


def compute_wp(state: GameState, prior: float, sport_config: SportConfig) -> float:
    """Home win probability.

    Live values are clipped to ``[0.0001, 0.9999]``. A decided home win is
    ``1.0`` and a decided home loss is ``0.0``, with no clip. ``prior`` is
    the pregame home win probability. Pass ``state.prior_home`` to use the
    snapshot's prior. The same state and prior always return the same float.
    """
    if not isinstance(state, GameState):
        raise TypeError("state must be a GameState")
    if state.sport != sport_config.sport:
        raise ValueError(
            f"state.sport {state.sport!r} does not match "
            f"sport_config.sport {sport_config.sport!r}"
        )
    try:
        pack = _PACKS[sport_config.family]
    except KeyError as exc:
        raise NotImplementedError(
            f"no win-probability pack for family {sport_config.family!r}"
        ) from exc

    raw = pack(state, prior, sport_config)
    if not math.isfinite(raw):
        raise ValueError("win probability was not finite")
    decided = _decided_wp(state, sport_config)
    if decided is not None:
        return decided
    if raw < LIVE_WP_FLOOR:
        return LIVE_WP_FLOOR
    if raw > LIVE_WP_CEIL:
        return LIVE_WP_CEIL
    return float(raw)
