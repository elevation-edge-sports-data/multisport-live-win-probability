"""Drop replay vertices that do not change the drawn WP polyline."""

from __future__ import annotations

from mswp import GameState, compute_wp
from mswp.config import SportConfig

DEFAULT_EPS = 0.0005


def discrete_state(state: GameState) -> tuple[object, ...]:
    return (
        state.home_score,
        state.away_score,
        state.period,
        state.status,
        state.strength or "5v5",
        bool(state.extra_attacker),
    )


def elapsed_axis(state: GameState, config: SportConfig) -> float:
    if state.period <= config.regulation_periods:
        remaining = min(state.seconds_remaining_total, config.regulation_seconds)
        return float(config.regulation_seconds - remaining)
    extra = (state.period - config.regulation_periods - 1) * config.ot_period_seconds
    remaining_ot = min(state.seconds_remaining_total, config.ot_period_seconds)
    return float(
        config.regulation_seconds + extra + (config.ot_period_seconds - remaining_ot)
    )


def thin_states(
    states: list[GameState],
    config: SportConfig,
    *,
    eps: float = DEFAULT_EPS,
) -> list[GameState]:
    if len(states) <= 2:
        return list(states)
    wps = [compute_wp(state, state.prior_home, config) for state in states]
    xs = [elapsed_axis(state, config) for state in states]
    keep = [False] * len(states)
    keep[0] = True
    keep[-1] = True
    for i, state in enumerate(states):
        if i == 0:
            continue
        if discrete_state(state) != discrete_state(states[i - 1]):
            keep[i] = True
        if state.status == "final" or states[i - 1].period != state.period:
            keep[i] = True

    def chord_error(i: int, left: int, right: int) -> float:
        span = xs[right] - xs[left]
        if span <= 0:
            return abs(wps[i] - wps[left])
        t = (xs[i] - xs[left]) / span
        return abs(wps[i] - (wps[left] + t * (wps[right] - wps[left])))

    changed = True
    while changed:
        changed = False
        anchors = [i for i, flag in enumerate(keep) if flag]
        for a, b in zip(anchors, anchors[1:]):
            if b - a <= 1:
                continue
            worst_i = a + 1
            worst = -1.0
            for i in range(a + 1, b):
                err = chord_error(i, a, b)
                if err > worst:
                    worst = err
                    worst_i = i
            if worst > eps and not keep[worst_i]:
                keep[worst_i] = True
                changed = True
    return [state for state, flag in zip(states, keep) if flag]
