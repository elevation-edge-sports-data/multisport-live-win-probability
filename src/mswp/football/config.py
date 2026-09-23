"""Football-pack configs. NFL now; college football is another config later."""

from __future__ import annotations

from mswp.config import SportConfig

# v0 league anchors, not a fitted rating and not an Elo k-factor.
# 22.5 points per team is a recent regular-season scoring level.
# Dispersion 4.05 makes a full-game margin standard deviation of 13.5 points:
# 2 * 4.05 * 22.5 = 13.5^2.
NFL_CONFIG = SportConfig(
    sport="nfl",
    family="football",
    regulation_periods=4,
    period_seconds=15 * 60,
    mean_score_per_team=22.5,
    score_dispersion=4.05,
    ot_period_seconds=10 * 60,
    tie_after_ot=True,
)
