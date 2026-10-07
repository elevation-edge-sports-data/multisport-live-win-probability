"""Saved-feed adapters. They accept dicts the caller already loaded."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mswp import GameState

from live_wp.feeds.espn import (
    espn_scoreboard_event_to_state,
    espn_summary_to_states,
    states_from_espn,
)
from live_wp.feeds.espn_basketball import (
    events_from_espn_basketball,
    is_basketball_summary,
)


def states_from_ingest(
    payload: Mapping[str, Any],
    *,
    density: str = "scoring",
) -> list[GameState]:
    """Map one saved ESPN object the way ``ingest-espn`` does.

    NBA and NCAAB summaries use the basketball adapter. NFL, college
    football, and NHL stay on ``states_from_espn``.
    """
    if is_basketball_summary(payload):
        return events_from_espn_basketball(payload, density=density)
    return states_from_espn(payload, density=density)


__all__ = [
    "espn_scoreboard_event_to_state",
    "espn_summary_to_states",
    "states_from_espn",
    "states_from_ingest",
]
