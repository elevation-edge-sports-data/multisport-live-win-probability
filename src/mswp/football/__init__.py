"""Football pack. Does not import any other sport pack."""

from mswp.football.config import NCAAF_CONFIG, NFL_CONFIG, NFL_PLAYOFF_CONFIG
from mswp.football.model import football_win_probability, team_points_per_second

__all__ = [
    "NCAAF_CONFIG",
    "NFL_CONFIG",
    "NFL_PLAYOFF_CONFIG",
    "football_win_probability",
    "team_points_per_second",
]
