"""NCAAH entry point for the hockey pack."""

from __future__ import annotations

from mswp.compute import compute_wp
from mswp.config import SportConfig
from mswp.hockey.config import NCAAH_CONFIG
from mswp.state import GameState


class NcaahModel:
    sport = "ncaah"

    def sport_config(self) -> SportConfig:
        return NCAAH_CONFIG

    def win_probability(self, state: GameState, prior: float) -> float:
        return compute_wp(state, prior, self.sport_config())
