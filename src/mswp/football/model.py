"""Remaining-score win probability for the football pack.

Clock, current score, and the pregame prior. Not a rating update. When
possession, down, distance, and yard line are all present, a small
expected-points term shifts the remaining-score mean. Timeouts are not read.

NFL overtime is the 2025 rule. Each team is owed a possession, then the
next score wins. A first-drive touchdown does not end it. A safety does.
Regular season is 10 minutes and can tie. Playoffs are 15 minutes and
cannot. College overtime is a separate possession path.
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
    if _ncaaf_overtime(state, config):
        return ncaaf_overtime_win_probability(state, prior, config)

    rate_home, rate_away = team_points_per_second(prior, config)
    score_margin = state.home_score - state.away_score

    # A final snapshot has no remaining football, including a finished tie.
    if state.status == "final":
        return _decided(score_margin)

    remaining = state.seconds_remaining_total
    in_regulation = state.period <= config.regulation_periods
    if in_regulation:
        remaining = min(remaining, config.regulation_seconds)

    if _nfl_overtime_state(state, config, in_regulation, remaining, score_margin):
        return _nfl_overtime(state, prior, config)

    if remaining <= 0:
        return _decided(score_margin)

    return _remaining_score(
        _margin_with_situation(state, score_margin),
        rate_home,
        rate_away,
        remaining,
        config,
    )


def _nfl_overtime_state(
    state: GameState,
    config: SportConfig,
    in_regulation: bool,
    remaining: int,
    score_margin: int,
) -> bool:
    """True when this snapshot is NFL overtime, not more regulation time."""
    if state.period > config.regulation_periods:
        return True
    return in_regulation and remaining <= 0 and score_margin == 0


# Regulation is modeled as this many alternating possessions. The count is
# the possession clock. It is not a new points-per-game rate.
_POSSESSIONS_PER_TEAM = 11
# Partition of the points already implied by a team's rate. Touchdowns are
# 7, field goals are 3. The shares are not a separate scoring level.
_TD_POINT_SHARE = 0.70
# Chance an average defense ends the opponent's possession with a score.
# A safety is the part a snapshot can see as a two-point margin.
_DEFENSIVE_CHANCE = 0.02
_SAFETY_SHARE = 0.35


def _nfl_overtime(state: GameState, prior: float, config: SportConfig) -> float:
    """2025 overtime. Two phases, then the clock.

    Both teams are owed a possession. An opening safety ends it. A
    touchdown or field goal does not: the other team still possesses.
    After both have possessed, the next score wins. The first possession
    can use the whole period, and then the second team never possesses.
    Regular season (``tie_after_ot``) ties at 0.5. Playoffs start another
    period. This is not more seconds of the regulation scoring rate.
    """
    rate_home, rate_away = team_points_per_second(prior, config)
    margin = state.home_score - state.away_score
    window = _ot_window(state, config)

    if state.period > config.regulation_periods and window <= 0.0:
        if margin == 0:
            if config.tie_after_ot:
                return 0.5
            return _solved_window(
                rate_home, rate_away, float(config.ot_period_seconds), config, None
            )
        return _decided(margin)

    if abs(margin) == 2 and state.period > config.regulation_periods:
        return _decided(margin)

    if margin == 0:
        receiver = state.possession if state.possession in ("home", "away") else None
        return _solved_window(rate_home, rate_away, window, config, receiver)

    if abs(margin) > 8:
        return _decided(margin)

    leader = "home" if margin > 0 else "away"
    return _answering_possession(
        rate_home,
        rate_away,
        window,
        config,
        leader,
        abs(margin),
        _tied_restart(rate_home, rate_away, config),
    )


def _ot_window(state: GameState, config: SportConfig) -> float:
    """Seconds left in the overtime period. A tied end of regulation is full."""
    if state.period <= config.regulation_periods:
        return float(config.ot_period_seconds)
    window = float(state.seconds_remaining_total)
    cap = float(config.ot_period_seconds)
    if window > cap:
        return cap
    if window < 0.0:
        return 0.0
    return window


def _possession_seconds(config: SportConfig) -> float:
    return config.regulation_seconds / (2.0 * _POSSESSIONS_PER_TEAM)


def _points_per_score() -> float:
    weight = _TD_POINT_SHARE / 7.0 + (1.0 - _TD_POINT_SHARE) / 3.0
    return 1.0 / weight


def _drive(
    offense_rate: float, defense_rate: float, config: SportConfig
) -> tuple[float, float, float, float, float]:
    """Touchdown, field goal, no score, safety, defensive touchdown.

    The mean is this team's share of ``mean_score_per_team``. The rate
    gap tilts the chances. It does not add a new points total.
    """
    base = config.mean_score_per_team / config.regulation_seconds
    offense = 0.0 if base <= 0.0 else max(offense_rate, 0.0) / base
    defense = 0.0 if base <= 0.0 else max(defense_rate, 0.0) / base
    expected = offense * (config.mean_score_per_team / _POSSESSIONS_PER_TEAM)
    p_def = _DEFENSIVE_CHANCE * defense
    if p_def > 0.08:
        p_def = 0.08
    if p_def < 0.0:
        p_def = 0.0
    p_safety = p_def * _SAFETY_SHARE
    p_def_td = p_def - p_safety
    p_td = _TD_POINT_SHARE * expected / 7.0
    p_fg = (1.0 - _TD_POINT_SHARE) * expected / 3.0
    room = 1.0 - p_def
    if room < 0.0:
        room = 0.0
    if p_td + p_fg > room and p_td + p_fg > 0.0:
        scale = room / (p_td + p_fg)
        p_td *= scale
        p_fg *= scale
    p_none = room - p_td - p_fg
    if p_none < 0.0:
        p_none = 0.0
    return p_td, p_fg, p_none, p_safety, p_def_td


def _fit_on_clock(
    drive: tuple[float, float, float, float, float],
    window: float,
    config: SportConfig,
) -> tuple[tuple[float, float, float, float, float], float]:
    """Shrink a possession so it can run out the period without a score."""
    if window <= 0.0:
        return (0.0, 0.0, 0.0, 0.0, 0.0), 1.0
    p_expire = math.exp(-window / _possession_seconds(config))
    if p_expire > 1.0:
        p_expire = 1.0
    scale = 1.0 - p_expire
    touchdown, field_goal, no_score, safety, defensive_td = drive
    return (
        touchdown * scale,
        field_goal * scale,
        no_score * scale,
        safety * scale,
        defensive_td * scale,
    ), p_expire


def _remaining_after_drive(window: float, config: SportConfig) -> float:
    """Expected seconds left after a possession that finished in time."""
    mean = _possession_seconds(config)
    if window <= 0.0:
        return 0.0
    p_long = math.exp(-window / mean)
    if p_long >= 1.0:
        return 0.0
    elapsed = mean - window * p_long / (1.0 - p_long)
    if elapsed < 0.0:
        elapsed = 0.0
    if elapsed > window:
        elapsed = window
    return window - elapsed


def _tied_restart(rate_home: float, rate_away: float, config: SportConfig) -> float:
    if config.tie_after_ot:
        return 0.5
    return _solved_window(
        rate_home, rate_away, float(config.ot_period_seconds), config, None
    )


def _solved_window(
    rate_home: float,
    rate_away: float,
    window: float,
    config: SportConfig,
    receiver: str | None,
) -> float:
    """One overtime window. Playoff clock death starts another full period."""
    if config.tie_after_ot:
        return _opening_phase(rate_home, rate_away, window, config, receiver, 0.5)

    full = float(config.ot_period_seconds)
    if window >= full and receiver is None:
        zero = _opening_phase(rate_home, rate_away, full, config, None, 0.0)
        one = _opening_phase(rate_home, rate_away, full, config, None, 1.0)
        slope = one - zero
        if slope >= 1.0:
            return 0.5
        return zero / (1.0 - slope)

    fresh = _solved_window(rate_home, rate_away, full, config, None)
    return _opening_phase(rate_home, rate_away, window, config, receiver, fresh)


def _opening_phase(
    rate_home: float,
    rate_away: float,
    window: float,
    config: SportConfig,
    receiver: str | None,
    restart: float,
) -> float:
    """Both teams are still owed a possession. ``receiver`` goes first."""
    if receiver is None:
        return 0.5 * (
            _opening_phase(rate_home, rate_away, window, config, "home", restart)
            + _opening_phase(rate_home, rate_away, window, config, "away", restart)
        )
    if window <= 0.0:
        return restart

    offense = rate_home if receiver == "home" else rate_away
    defense = rate_away if receiver == "home" else rate_home
    drive, p_expire = _fit_on_clock(_drive(offense, defense, config), window, config)
    p_td, p_fg, p_none, p_safety, p_def_td = drive
    after = _remaining_after_drive(window, config)
    # A defensive score on the first possession ends the game.
    defense_wins = 0.0 if receiver == "home" else 1.0

    def answer(lead: int) -> float:
        return _answering_possession(
            rate_home, rate_away, after, config, receiver, lead, restart
        )

    return (
        p_expire * restart
        + p_td * answer(7)
        + p_fg * answer(3)
        + p_none * answer(0)
        + (p_safety + p_def_td) * defense_wins
    )


def _answering_possession(
    rate_home: float,
    rate_away: float,
    window: float,
    config: SportConfig,
    leader: str,
    lead: int,
    restart: float,
) -> float:
    """The other team still has not finished a possession.

    A matching score goes to sudden death. A lower score loses, because
    both teams have had their possession. Running the clock out while
    behind also loses. Running it out while tied is ``restart``.
    """
    trailer = "away" if leader == "home" else "home"
    leader_wins = 1.0 if leader == "home" else 0.0
    trailer_wins = 1.0 if trailer == "home" else 0.0
    if lead > 8:
        return leader_wins
    if window <= 0.0:
        return leader_wins if lead > 0 else restart

    offense = rate_home if trailer == "home" else rate_away
    defense = rate_away if trailer == "home" else rate_home
    drive, p_expire = _fit_on_clock(_drive(offense, defense, config), window, config)
    p_td, p_fg, p_none, p_safety, p_def_td = drive
    after = _remaining_after_drive(window, config)

    def scored(points: int) -> float:
        if points > lead:
            return trailer_wins
        if points < lead:
            return leader_wins
        return _sudden_death(rate_home, rate_away, after, restart)

    expire = leader_wins if lead > 0 else restart
    return (
        p_expire * expire
        + p_td * scored(7)
        + p_fg * scored(3)
        + p_none * scored(0)
        + (p_safety + p_def_td) * leader_wins
    )


def _sudden_death(
    rate_home: float, rate_away: float, window: float, restart: float
) -> float:
    """Next score wins. A scoreless end is ``restart``, not more regulation."""
    per_score = _points_per_score()
    home = max(rate_home, 0.0) / per_score
    away = max(rate_away, 0.0) / per_score
    total = home + away
    if total <= 0.0 or window <= 0.0:
        return restart
    share = home / total
    quiet = math.exp(-total * window)
    return share * (1.0 - quiet) + restart * quiet


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
_NCAAF_OT_YARDLINE = 75
# A 2-point try is worth about 0.9 points (0 or 2, not a drive).
_NCAAF_TWO_POINT_EP = 0.9


def _ncaaf_overtime(state: GameState, config: SportConfig) -> bool:
    """True when this snapshot is college overtime, not the NFL period.

    A tie at 0:00 of regulation is the start of the first extra period.
    NFL overtime is the 2025 possession rule above. This path does not
    read ``ot_period_seconds``.
    """
    if state.sport != "ncaaf" and config.sport != "ncaaf":
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


def ncaaf_overtime_win_probability(
    state: GameState, prior: float, config: SportConfig
) -> float:
    """College overtime stub. This is not a timed quarter.

    The first two extra periods give each team a possession from the
    opponent 25 (yard line 75). Expected points come from that spot.
    A tied score is treated as both teams still to possess, so a 0.60
    pregame favorite stays a small favorite. If one team has already
    scored and the other is on offense, the current score is the margin
    and only that offense adds a possession.

    After two extra periods, each remaining possession is a 2-point try
    (expected points about 0.9, outcome 0 or 2). ``ot_period_seconds``
    is not the process. Possessions are not scaled into regulation
    seconds, and they are not the NFL 10-minute clock.
    """
    points = _ncaaf_ot_points(state, config)
    if state.home_score == state.away_score:
        return _both_still_to_possess(prior, config, points)
    possession = state.possession if state.possession in ("home", "away") else None
    if possession is None:
        possession = "away" if state.home_score > state.away_score else "home"
    return _one_possession_left(
        state.home_score - state.away_score, prior, config, points, possession
    )


def _ncaaf_ot_points(state: GameState, config: SportConfig) -> float:
    extra = state.period - config.regulation_periods
    if extra < 1:
        extra = 1
    if extra >= 3:
        return _NCAAF_TWO_POINT_EP
    return expected_points(1, 10, _NCAAF_OT_YARDLINE)


def _both_still_to_possess(prior: float, config: SportConfig, points: float) -> float:
    """Tied, both offenses still to go.

    The edge is the pregame margin scaled by this possession's share of
    a team's full-game points. That share is not turned back into
    regulation seconds, and it is not ``ot_period_seconds``.
    """
    share = points / config.mean_score_per_team
    if share <= 0.0:
        return 0.5
    return _NORMAL.cdf(_NORMAL.inv_cdf(prior) * math.sqrt(share))


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
