"""Remaining-score win probability for the football pack.

Clock, current score, and the pregame prior. Not a rating update. When
possession, down, distance, and yard line are all present, a small
expected-points term shifts the remaining-score mean. Timeouts are not read.
"""

from __future__ import annotations

import math
from statistics import NormalDist

from mswp.config import SportConfig
from mswp.football.situation import expected_points
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
    if _cfb_overtime(state, config):
        return cfb_overtime_win_probability(state, prior, config)

    rate_home, rate_away = team_points_per_second(prior, config)
    score_margin = state.home_score - state.away_score

    # A final snapshot has no remaining football, including a finished tie.
    if state.status == "final":
        return _decided(score_margin)

    remaining = state.seconds_remaining_total
    in_regulation = state.period <= config.regulation_periods
    if in_regulation:
        remaining = min(remaining, config.regulation_seconds)

    if remaining <= 0:
        return _clock_expired(
            score_margin, in_regulation, rate_home, rate_away, config, state
        )

    return _remaining_score(
        _margin_with_situation(state, score_margin),
        rate_home,
        rate_away,
        remaining,
        config,
    )


def _clock_expired(
    score_margin: int,
    in_regulation: bool,
    rate_home: float,
    rate_away: float,
    config: SportConfig,
    state: GameState,
) -> float:
    # The score fixes the winner. Situation does not overturn it.
    if score_margin > 0:
        return 1.0
    if score_margin < 0:
        return 0.0
    # Tied at 0:00 of regulation starts overtime. It is not a walk-off.
    if in_regulation:
        return _remaining_score(
            _margin_with_situation(state, 0),
            rate_home,
            rate_away,
            config.ot_period_seconds,
            config,
        )
    if config.tie_after_ot:
        return 0.5
    return _remaining_score(
        _margin_with_situation(state, 0),
        rate_home,
        rate_away,
        config.ot_period_seconds,
        config,
    )


def _margin_with_situation(state: GameState, score_margin: int) -> float:
    """Score margin, plus expected points when the whole situation is known.

    A missing possession, down, distance, or yard line leaves the margin
    untouched, so the clock-and-score number is unchanged.
    """
    ep = _situation_points(state)
    if ep is None:
        return score_margin
    if state.possession == "home":
        return score_margin + ep
    return score_margin - ep


def _situation_points(state: GameState) -> float | None:
    if state.possession not in ("home", "away"):
        return None
    down = state.down
    distance = state.distance
    yardline = state.yardline
    if not _plain_int(down) or not _plain_int(distance) or not _plain_int(yardline):
        return None
    if down not in (1, 2, 3, 4) or distance < 0 or not 1 <= yardline <= 99:
        return None
    return expected_points(down, distance, yardline)


def _plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _remaining_score(
    margin: float,
    rate_home: float,
    rate_away: float,
    remaining: float,
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


# Opponent 25-yard line: yards from the offense's own goal.
_CFB_OT_YARDLINE = 75
# A 2-point try is worth about 0.9 points (0 or 2, not a drive).
_CFB_TWO_POINT_EP = 0.9


def _cfb_overtime(state: GameState, config: SportConfig) -> bool:
    """True when this snapshot is college overtime, not a timed NFL period.

    A tie at 0:00 of regulation is the start of the first extra period.
    NFL overtime stays on the timed clock above.
    """
    if state.sport != "cfb" and config.sport != "cfb":
        return False
    if state.status == "final":
        return False
    if str(state.status).lower() in {"ot", "overtime"}:
        return True
    if state.period > config.regulation_periods:
        return True
    return (
        state.period >= config.regulation_periods
        and state.seconds_remaining_period == 0
        and state.seconds_remaining_total == 0
        and state.home_score == state.away_score
    )


def cfb_overtime_win_probability(
    state: GameState, prior: float, config: SportConfig
) -> float:
    """College overtime stub. This is not a timed quarter.

    The first two extra periods give each team a possession from the
    opponent 25 (yard line 75). Expected points come from that spot, then
    a short remaining-score process. A tied score is treated as both teams
    still to possess, so a 0.60 pregame favorite stays a small favorite.
    If one team has already scored and the other is on offense, the current
    score is the margin and only that offense adds a possession.

    After two extra periods, each remaining possession is a 2-point try
    (expected points about 0.9, outcome 0 or 2). ``ot_period_seconds`` is
    not the process.
    """
    points = _cfb_ot_points(state, config)
    if state.home_score == state.away_score:
        return _both_still_to_possess(prior, config, points)
    possession = state.possession if state.possession in ("home", "away") else None
    if possession is None:
        possession = "away" if state.home_score > state.away_score else "home"
    return _one_possession_left(
        state.home_score - state.away_score, prior, config, points, possession
    )


def _cfb_ot_points(state: GameState, config: SportConfig) -> float:
    extra = state.period - config.regulation_periods
    if extra < 1:
        extra = 1
    if extra >= 3:
        return _CFB_TWO_POINT_EP
    return expected_points(1, 10, _CFB_OT_YARDLINE)


def _both_still_to_possess(prior: float, config: SportConfig, points: float) -> float:
    """Tied, both offenses still to go. A short slice of the full-game process.

    The slice is the expected points from the spot divided by a team's
    full-game points. It is not ``ot_period_seconds``.
    """
    rate_home, rate_away = team_points_per_second(prior, config)
    share = points / config.mean_score_per_team
    remaining = share * config.regulation_seconds
    return _remaining_score(0.0, rate_home, rate_away, remaining, config)


def _one_possession_left(
    score_margin: int,
    prior: float,
    config: SportConfig,
    points: float,
    possession: str,
) -> float:
    """Current score, plus one offense from the overtime spot."""
    expected_margin = config.margin_sd * _NORMAL.inv_cdf(prior)
    tilt = (expected_margin / 2.0) * (points / config.mean_score_per_team)
    if possession == "home":
        mean = score_margin + points + tilt
    else:
        mean = score_margin - points + tilt
    variance_scale = 0.5 * (points / config.mean_score_per_team)
    sd = config.margin_sd * math.sqrt(variance_scale)
    if sd == 0.0:
        return _decided(mean)
    return _NORMAL.cdf(mean / sd)
