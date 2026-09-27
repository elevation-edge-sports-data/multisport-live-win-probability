"""Remaining-goals win probability for the hockey pack.

Clock, current score, and the pregame prior. Not a rating update.
Home and away goal rates are split from that prior the same way the
football pack splits point rates. The remaining goals are a Poisson
pair, so the margin is Skellam. Strength and extra attacker are not read.
"""

from __future__ import annotations

import math
from statistics import NormalDist

from mswp.config import SportConfig
from mswp.state import GameState

_NORMAL = NormalDist()


def team_goals_per_second(prior: float, config: SportConfig) -> tuple[float, float]:
    """Home and away goals per second implied by a pregame home win probability.

    The rates sum to the pack's league scoring level. The gap is the constant
    edge that reproduces ``prior`` under a normal goal margin at 0-0 with a
    full regulation clock. The same split is what the football pack uses for
    points. A negative rate is clipped to zero so the Poisson mean stays valid.
    """
    if not math.isfinite(prior) or not 0.0 < prior < 1.0:
        raise ValueError("prior must be in (0, 1)")
    expected_margin = config.margin_sd * _NORMAL.inv_cdf(prior)
    base = config.mean_score_per_team / config.regulation_seconds
    half_gap = expected_margin / (2.0 * config.regulation_seconds)
    home = base + half_gap
    away = base - half_gap
    if home < 0.0:
        home = 0.0
    if away < 0.0:
        away = 0.0
    return home, away


def hockey_win_probability(
    state: GameState, prior: float, config: SportConfig
) -> float:
    """Unclipped home win probability. ``compute_wp`` applies the clip.

    ``state.strength`` and ``state.extra_attacker`` are ignored.
    """
    if config.family != "hockey":
        raise ValueError(f"hockey model cannot use family {config.family!r}")
    rate_home, rate_away = team_goals_per_second(prior, config)
    margin = state.home_score - state.away_score
    if state.status == "final":
        return _score_decided(margin)

    in_regulation = state.period <= config.regulation_periods
    # A goal in sudden-death overtime has already ended the game.
    if not in_regulation and margin != 0:
        return _score_decided(margin)

    remaining = state.seconds_remaining_total
    if in_regulation:
        remaining = min(remaining, config.regulation_seconds)
    else:
        remaining = min(max(remaining, 0), config.ot_period_seconds)

    if remaining <= 0 and margin != 0:
        return _score_decided(margin)

    if remaining <= 0 or not in_regulation:
        window = float(config.ot_period_seconds if remaining <= 0 else remaining)
        return _overtime_home_win(
            rate_home, rate_away, window, config.tie_after_ot
        )

    overtime_win = _overtime_home_win(
        rate_home,
        rate_away,
        float(config.ot_period_seconds),
        config.tie_after_ot,
    )
    return _skellam_home_win(
        margin,
        rate_home * remaining,
        rate_away * remaining,
        overtime_win,
    )


def _overtime_home_win(
    rate_home: float,
    rate_away: float,
    window: float,
    tie_after_ot: bool,
) -> float:
    """Home win probability from a tied sudden-death window.

    Playoff overtime (``tie_after_ot`` false) repeats the 20:00 window until
    a goal, so the length cancels and the answer is the goal-rate share.
    A regular-season flag would stop after one window and call a scoreless
    period a tie.
    """
    total = rate_home + rate_away
    if total <= 0.0:
        return 0.5
    share = rate_home / total
    if window <= 0.0:
        return 0.5 if tie_after_ot else share
    quiet = math.exp(-total * window)
    home_in_window = share * (1.0 - quiet)
    if tie_after_ot:
        return home_in_window + 0.5 * quiet
    if quiet >= 1.0:
        return share
    return home_in_window / (1.0 - quiet)


def _skellam_home_win(
    margin: int,
    lam_home: float,
    lam_away: float,
    overtime_win: float,
) -> float:
    """P(home finishes ahead) plus a tied finish times the overtime chance."""
    home_probs = _poisson_probs(lam_home)
    away_probs = _poisson_probs(lam_away)
    win = 0.0
    tie = 0.0
    mass = 0.0
    for home_goals, p_home in enumerate(home_probs):
        if p_home <= 0.0:
            continue
        for away_goals, p_away in enumerate(away_probs):
            if p_away <= 0.0:
                continue
            probability = p_home * p_away
            mass += probability
            diff = margin + home_goals - away_goals
            if diff > 0:
                win += probability
            elif diff == 0:
                tie += probability
    if mass <= 0.0:
        return _score_decided(margin)
    return (win + tie * overtime_win) / mass


def _poisson_probs(lam: float) -> list[float]:
    """Poisson probabilities from the standard library, recursive in k."""
    if lam <= 0.0:
        return [1.0]
    width = math.sqrt(lam)
    limit = int(lam + 14.0 * width + 8.0)
    if limit < 12:
        limit = 12
    probs = [0.0] * (limit + 1)
    probability = math.exp(-lam)
    probs[0] = probability
    for goals in range(1, limit + 1):
        probability *= lam / goals
        probs[goals] = probability
    return probs


def _score_decided(margin: int) -> float:
    if margin > 0:
        return 1.0
    if margin < 0:
        return 0.0
    return 0.5
