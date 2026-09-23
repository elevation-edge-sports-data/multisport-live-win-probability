"""Remaining-score win probability for the football pack.

Clock, current score, and the pregame prior. Not EPA, not WPA, and not a
rating update. Down, distance, yard line, possession, and timeouts are not read.
"""

from __future__ import annotations

import math
from statistics import NormalDist

from mswp.config import SportConfig
from mswp.state import GameState

_NORMAL = NormalDist()


def team_points_per_second(prior: float, config: SportConfig) -> tuple[float, float]:
    """Home and away points per second implied by a pregame home win probability.

    The rates sum to the pack's league scoring level. The gap is the constant
    edge that reproduces ``prior`` at 0-0 with a full regulation clock.
    """
    if not math.isfinite(prior) or not 0.0 < prior < 1.0:
        raise ValueError("prior must be in (0, 1)")
    expected_margin = config.margin_sd * _NORMAL.inv_cdf(prior)
    base = config.mean_score_per_team / config.regulation_seconds
    half_gap = expected_margin / (2.0 * config.regulation_seconds)
    return base + half_gap, base - half_gap


def football_win_probability(
    state: GameState, prior: float, config: SportConfig
) -> float:
    """Unclipped home win probability. ``compute_wp`` applies the clip."""
    if config.family != "football":
        raise ValueError(f"football model cannot use family {config.family!r}")

    rate_home, rate_away = team_points_per_second(prior, config)
    margin = state.home_score - state.away_score

    # A final snapshot has no remaining football, including a finished tie.
    if state.status == "final":
        return _decided(margin)

    remaining = state.seconds_remaining_total
    in_regulation = state.period <= config.regulation_periods
    if in_regulation:
        remaining = min(remaining, config.regulation_seconds)

    if remaining <= 0:
        return _clock_expired(margin, in_regulation, rate_home, rate_away, config)

    return _remaining_score(margin, rate_home, rate_away, remaining, config)


def _clock_expired(
    margin: int,
    in_regulation: bool,
    rate_home: float,
    rate_away: float,
    config: SportConfig,
) -> float:
    if margin > 0:
        return 1.0
    if margin < 0:
        return 0.0
    # Tied at 0:00 of regulation starts overtime. It is not a walk-off.
    if in_regulation:
        return _remaining_score(
            0, rate_home, rate_away, config.ot_period_seconds, config
        )
    if config.tie_after_ot:
        return 0.5
    return _remaining_score(
        0, rate_home, rate_away, config.ot_period_seconds, config
    )


def _remaining_score(
    margin: int,
    rate_home: float,
    rate_away: float,
    remaining: int,
    config: SportConfig,
) -> float:
    mean = margin + (rate_home - rate_away) * remaining
    variance_scale = remaining / config.regulation_seconds
    sd = config.margin_sd * math.sqrt(variance_scale)
    if sd == 0.0:
        return _decided(mean)
    return _NORMAL.cdf(mean / sd)


def _decided(margin: float) -> float:
    if margin > 0:
        return 1.0
    if margin < 0:
        return 0.0
    return 0.5
