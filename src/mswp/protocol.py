"""Sport pack surface. Packs must not import each other."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mswp.config import SportConfig
from mswp.state import GameState


@runtime_checkable
class SportModel(Protocol):
    """Config plus a pure home-win-probability function."""

    sport: str

    def sport_config(self) -> SportConfig:
        """Scoring rates and overtime rules for this sport."""

    def win_probability(self, state: GameState, prior: float) -> float:
        """Home win probability for ``state`` given a pregame ``prior``."""
