"""Per-sport entry points. Each module is a pack facade and they do not import each other."""

from mswp.sports.ncaaf import NcaafModel
from mswp.sports.nfl import NFLModel
from mswp.sports.nhl import NhlModel

__all__ = ["NcaafModel", "NHLModel", "NFLModel"]
