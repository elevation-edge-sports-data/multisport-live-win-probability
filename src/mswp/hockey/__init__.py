"""Hockey pack. Does not import any other sport pack."""

from mswp.hockey.config import NHL_CONFIG, NHL_REGULAR_CONFIG
from mswp.hockey.model import (
    hockey_standings_tie_probability,
    hockey_win_probability,
    team_goals_per_second,
)

__all__ = [
    "NHL_CONFIG",
    "NHL_REGULAR_CONFIG",
    "hockey_standings_tie_probability",
    "hockey_win_probability",
    "team_goals_per_second",
]
