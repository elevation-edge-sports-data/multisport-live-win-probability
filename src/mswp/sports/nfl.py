"""NFL entry point for the football pack.

College football is ``CfbModel`` beside this module: another config of the
same pack, not a copy of this file.
"""

from __future__ import annotations

from mswp.compute import compute_wp
from mswp.config import SportConfig
from mswp.football.config import NFL_CONFIG
from mswp.state import GameState


class NFLModel:
    """Remaining-score NFL model. Down and distance are not required."""

    sport = "nfl"

    def sport_config(self) -> SportConfig:
        return NFL_CONFIG

    def win_probability(self, state: GameState, prior: float) -> float:
        return compute_wp(state, prior, self.sport_config())
