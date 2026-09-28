"""Remaining-points win probability for the basketball pack."""

from __future__ import annotations

import math
from statistics import NormalDist

from mswp.basketball.config import NCAAB_POSSESSION_POINTS, NBA_POSSESSION_POINTS
from mswp.config import SportConfig
from mswp.state import GameState

_NORMAL = NormalDist()


def team_points_per_second(prior: float, config: SportConfig) -> tuple[float, float]:
    if not math.isfinite(prior) or not 0.0 < prior < 1.0:
        raise ValueError("prior must be in (0, 1)")
    expected_margin = config.margin_sd * _NORMAL.inv_cdf(prior)
    base = config.mean_score_per_team / config.regulation_seconds
    half_gap = expected_margin / (2.0 * config.regulation_seconds)
    return base + half_gap, base - half_gap


def basketball_win_probability(
    state: GameState, prior: float, config: SportConfig
) -> float:
    if config.family != "basketball":
        raise ValueError(f"basketball model cannot use family {config.family!r}")
    rate_home, rate_away = team_points_per_second(prior, config)
    margin = float(state.home_score - state.away_score)
    if state.status == "final":
        return _decided(margin)

    in_regulation = state.period <= config.regulation_periods
    remaining = float(state.seconds_remaining_total)
    if in_regulation:
        remaining = min(remaining, float(config.regulation_seconds))
    else:
        remaining = min(max(remaining, 0.0), float(config.ot_period_seconds))

    if remaining <= 0.0 and margin != 0.0:
        return _decided(margin)
    if remaining <= 0.0:
        remaining = float(config.ot_period_seconds)

    margin = _margin_with_possession(state, margin, config)
    return _remaining_score(margin, rate_home, rate_away, remaining, config)


def _margin_with_possession(
    state: GameState, margin: float, config: SportConfig
) -> float:
    if state.possession not in {"home", "away"}:
        return margin
    points = NBA_POSSESSION_POINTS if config.sport == "nba" else NCAAB_POSSESSION_POINTS
    return margin + points if state.possession == "home" else margin - points


def _remaining_score(
    margin: float,
    rate_home: float,
    rate_away: float,
    remaining: float,
    config: SportConfig,
) -> float:
    mean = margin + (rate_home - rate_away) * remaining
    variance_scale = remaining / config.regulation_seconds
    if variance_scale <= 0.0:
        return _decided(mean)
    if variance_scale < 0.08:
        variance_scale = 0.08
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
