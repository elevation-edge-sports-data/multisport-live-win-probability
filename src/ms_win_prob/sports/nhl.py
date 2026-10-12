"""NHL entry point for the hockey pack."""

from __future__ import annotations

from ms_win_prob.compute import compute_win_prob
from ms_win_prob.config import SportConfig
from ms_win_prob.hockey.config import NHL_CONFIG
from ms_win_prob.state import GameState


class NhlModel:
    """Remaining-goals NHL model. Strength is not required.

    ``sport_config`` is playoff overtime: 20 minutes of sudden death.
    Regular season passes ``NHL_REGULAR_CONFIG`` to ``compute_win_prob``.
    """

    sport = "nhl"

    def sport_config(self) -> SportConfig:
        return NHL_CONFIG

    def win_probability(self, state: GameState, prior: float) -> float:
        return compute_win_prob(state, prior, self.sport_config())
