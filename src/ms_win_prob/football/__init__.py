"""Football pack. Does not import any other sport pack."""

from ms_win_prob.football.config import NCAAF_CONFIG, NFL_CONFIG, NFL_PLAYOFF_CONFIG
from ms_win_prob.football.model import football_win_probability, team_points_per_second

__all__ = [
    "NCAAF_CONFIG",
    "NFL_CONFIG",
    "NFL_PLAYOFF_CONFIG",
    "football_win_probability",
    "team_points_per_second",
]
