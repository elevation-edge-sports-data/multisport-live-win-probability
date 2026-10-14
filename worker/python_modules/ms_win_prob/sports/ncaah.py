"""NCAAH entry point for the hockey pack."""

from __future__ import annotations

from ms_win_prob.compute import compute_win_prob
from ms_win_prob.config import SportConfig
from ms_win_prob.hockey.config import NCAAH_CONFIG
from ms_win_prob.state import GameState


class NcaahModel:
    sport = "ncaah"

    def sport_config(self) -> SportConfig:
        return NCAAH_CONFIG

    def win_probability(self, state: GameState, prior: float) -> float:
        return compute_win_prob(state, prior, self.sport_config())
