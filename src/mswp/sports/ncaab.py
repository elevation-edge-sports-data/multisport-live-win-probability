"""NCAAB entry point for the basketball pack."""

from __future__ import annotations

from mswp.basketball.config import NCAAB_CONFIG
from mswp.compute import compute_wp
from mswp.config import SportConfig
from mswp.state import GameState


class NcaabModel:
    sport = "ncaab"

    def sport_config(self) -> SportConfig:
        return NCAAB_CONFIG

    def win_probability(self, state: GameState, prior: float) -> float:
        return compute_wp(state, prior, self.sport_config())
