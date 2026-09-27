"""Hockey pack. Does not import any other sport pack."""

from mswp.hockey.config import NHL_CONFIG
from mswp.hockey.model import hockey_win_probability, team_goals_per_second

__all__ = [
    "NHL_CONFIG",
    "hockey_win_probability",
    "team_goals_per_second",
]
