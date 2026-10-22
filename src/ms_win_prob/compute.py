"""Single entry point for every sport."""

from __future__ import annotations

import math
from collections.abc import Callable
from statistics import NormalDist

from ms_win_prob.config import SportConfig
from ms_win_prob.basketball.model import basketball_win_probability
from ms_win_prob.football.model import football_win_probability
from ms_win_prob.hockey.model import hockey_win_probability
from ms_win_prob.state import GameState

# Live snapshots can still change, so they stay off 0 and 1.
# A decided game (final, or the end of regulation or overtime at 0:00
# and not tied) is 1.0 or 0.0.
LIVE_WIN_PROB_FLOOR = 0.0001
LIVE_WIN_PROB_CEIL = 0.9999

_NORMAL = NormalDist()

PackFn = Callable[[GameState, float, SportConfig], float]

_PACKS: dict[str, PackFn] = {
    "football": football_win_probability,
    "hockey": hockey_win_probability,
    "basketball": basketball_win_probability,
}


def _decided_win_prob(state: GameState, sport_config: SportConfig) -> float | None:
    """1.0 or 0.0 from the score when the winner is fixed.

    ``None`` means the game can still change, including a tie at 0:00 of
    regulation (overtime) or a tie at 0:00 of overtime when another period
    is possible. A final tie is 0.5.

    College overtime is not a timed clock, so a live extra period is not
    decided by 0:00. It is decided only when the lead cannot be erased by
    the possession that is still possible: 8 points from the 25, or 2 points
    once the tries are 2-point plays.
    """
    if state.status == "final":
        if state.home_score > state.away_score:
            return 1.0
        if state.home_score < state.away_score:
            return 0.0
        return 0.5

    if state.sport == "ncaaf" and state.period > sport_config.regulation_periods:
        return _ncaaf_extra_period_decided(state, sport_config)

    # A safety is the defensive score a clock-and-score snapshot can see.
    # In NFL overtime it ends the game even if the period clock is running.
    # A touchdown margin does not: the other team still has a possession.
    if (
        state.sport == "nfl"
        and state.period > sport_config.regulation_periods
        and abs(state.home_score - state.away_score) == 2
    ):
        if state.home_score > state.away_score:
            return 1.0
        return 0.0

    clock_out = (
        state.period >= sport_config.regulation_periods
        and state.seconds_remaining_period == 0
        and state.seconds_remaining_total == 0
    )
    if not clock_out:
        return None
    if state.home_score > state.away_score:
        return 1.0
    if state.home_score < state.away_score:
        return 0.0
    return None


def _ncaaf_extra_period_decided(
    state: GameState, sport_config: SportConfig
) -> float | None:
    margin = state.home_score - state.away_score
    if margin == 0:
        return None
    # Third extra period and later: a 2-point try. Before that, one drive.
    two_point = state.period >= sport_config.regulation_periods + 3
    max_points = 2 if two_point else 8
    if abs(margin) > max_points:
        return 1.0 if margin > 0 else 0.0
    return None


def prior_for_site(state: GameState, prior: float, sport_config: SportConfig) -> float:
    """Prior the sport model should see after the site adjustment.

    ``home_advantage`` is a full-game expected margin in the sport's score
    units. It is added in that margin space, then converted back to a
    probability. A neutral site skips the adjustment. A zero advantage
    leaves ``prior`` unchanged, including its exact float.
    """
    if state.neutral or sport_config.home_advantage == 0.0:
        return prior
    if not math.isfinite(prior) or not 0.0 < prior < 1.0:
        raise ValueError("prior must be in (0, 1)")
    z = _NORMAL.inv_cdf(prior) + sport_config.home_advantage / sport_config.margin_sd
    adjusted = _NORMAL.cdf(z)
    if adjusted <= 0.0:
        return math.nextafter(0.0, 1.0)
    if adjusted >= 1.0:
        return math.nextafter(1.0, 0.0)
    return adjusted


def compute_win_prob(state: GameState, prior: float, sport_config: SportConfig) -> float:
    """Home win probability.

    Live and calibration both enter here. When the site is not neutral,
    ``sport_config.home_advantage`` is applied to ``prior`` before the
    sport model runs. A neutral site skips that adjustment.

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

    raw = pack(state, prior_for_site(state, prior, sport_config), sport_config)
    if not math.isfinite(raw):
        raise ValueError("win probability was not finite")
    decided = _decided_win_prob(state, sport_config)
    if decided is not None:
        return decided
    if raw < LIVE_WIN_PROB_FLOOR:
        return LIVE_WIN_PROB_FLOOR
    if raw > LIVE_WIN_PROB_CEIL:
        return LIVE_WIN_PROB_CEIL
    return float(raw)
