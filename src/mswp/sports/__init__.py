"""Per-sport entry points. Each module is a pack facade and they do not import each other."""

from mswp.sports.nfl import NFLModel

__all__ = ["NFLModel"]
