"""NHL entry point for the hockey pack."""

from __future__ import annotations

from mswp.compute import compute_wp
from mswp.config import SportConfig
from mswp.hockey.config import NHL_CONFIG
from mswp.state import GameState


class NhlModel:
    """Remaining-goals NHL model. Strength is not required.

    ``sport_config`` is playoff overtime: 20 minutes of sudden death.
    Regular season passes ``NHL_REGULAR_CONFIG`` to ``compute_wp``.
    """

    sport = "nhl"

    def sport_config(self) -> SportConfig:
        return NHL_CONFIG

    def win_probability(self, state: GameState, prior: float) -> float:
        return compute_wp(state, prior, self.sport_config())
