"""Scoring rates and overtime rules owned by a sport pack.

A pack is data plus one model. College football is a later config of the
football pack, not a new ``GameState``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SportConfig:
    """League anchors for one sport.

    ``mean_score_per_team`` is the regulation scoring rate. ``score_dispersion``
    scales variance above a one-point Poisson: variance of one team's
    regulation score is ``score_dispersion * mean_score_per_team``. The rate
    gap between the two teams comes from the pregame prior, not from a rating
    update.
    """

    sport: str
    family: str
    regulation_periods: int
    period_seconds: int
    mean_score_per_team: float
    score_dispersion: float
    ot_period_seconds: int
    tie_after_ot: bool

    def __post_init__(self) -> None:
        if not self.sport or not self.family:
            raise ValueError("sport and family are required")
        if self.regulation_periods < 1:
            raise ValueError("regulation_periods must be >= 1")
        if self.period_seconds <= 0 or self.ot_period_seconds <= 0:
            raise ValueError("period lengths must be > 0")
        if self.mean_score_per_team <= 0 or self.score_dispersion <= 0:
            raise ValueError("scoring rate and dispersion must be > 0")

    @property
    def regulation_seconds(self) -> int:
        return self.regulation_periods * self.period_seconds

    @property
    def margin_sd(self) -> float:
        """Full-game standard deviation of home score minus away score."""
        return math.sqrt(2.0 * self.score_dispersion * self.mean_score_per_team)
