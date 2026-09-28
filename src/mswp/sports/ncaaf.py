"""College football entry point for the football pack.

Regulation uses the shared football model. Extra periods do not. They are
possessions from the opponent 25, then 2-point tries after the second extra
period. This module does not copy ``football_win_probability``.
"""

from __future__ import annotations

from mswp.compute import compute_wp
from mswp.config import SportConfig
from mswp.football.config import NCAAF_CONFIG
from mswp.state import GameState


class NcaafModel:
    """College football model. Down and distance are not required."""

    sport = "ncaaf"

    def sport_config(self) -> SportConfig:
        return NCAAF_CONFIG

    def win_probability(self, state: GameState, prior: float) -> float:
        return compute_wp(state, prior, self.sport_config())
