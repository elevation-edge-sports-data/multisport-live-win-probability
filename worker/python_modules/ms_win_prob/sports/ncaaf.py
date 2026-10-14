"""College football entry point for the football pack.

Regulation uses the shared football model. Extra periods do not. They are
possessions from the opponent 25, then 2-point tries after the second extra
period. This module does not copy ``football_win_probability``.
"""

from __future__ import annotations

from ms_win_prob.compute import compute_win_prob
from ms_win_prob.config import SportConfig
from ms_win_prob.football.config import NCAAF_CONFIG
from ms_win_prob.state import GameState


class NcaafModel:
    """College football model. Down and distance are not required."""

    sport = "ncaaf"

    def sport_config(self) -> SportConfig:
        return NCAAF_CONFIG

    def win_probability(self, state: GameState, prior: float) -> float:
        return compute_win_prob(state, prior, self.sport_config())
