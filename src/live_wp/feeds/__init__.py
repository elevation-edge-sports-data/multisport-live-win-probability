"""Saved-feed adapters. They accept dicts the caller already loaded."""

from live_wp.feeds.espn import (
    espn_scoreboard_event_to_state,
    espn_summary_to_states,
    states_from_espn,
)

__all__ = [
    "espn_scoreboard_event_to_state",
    "espn_summary_to_states",
    "states_from_espn",
]
