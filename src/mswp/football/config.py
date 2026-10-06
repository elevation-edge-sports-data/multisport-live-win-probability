"""Football-pack configs. NFL and college football share this pack."""

from __future__ import annotations

from mswp.config import SportConfig

# v0 league anchors, not a fitted rating and not an Elo k-factor.
# 22.5 points per team is a recent regular-season scoring level.
# Dispersion 4.05 makes a full-game margin standard deviation of 13.5 points:
# 2 * 4.05 * 22.5 = 13.5^2.
# Regular-season overtime changed in 2025. It is one 10-minute period.
# Each team still gets a possession if the first team scores a touchdown.
# The clock can expire in a tie, including on the first possession.
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

# Same 2025 possession rule as the regular season. Playoff overtime is
# 15 minutes and cannot tie. Demos stay on ``NFL_CONFIG``.
NFL_PLAYOFF_CONFIG = SportConfig(
    sport="nfl",
    family="football",
    regulation_periods=4,
    period_seconds=15 * 60,
    mean_score_per_team=22.5,
    score_dispersion=4.05,
    ot_period_seconds=15 * 60,
    tie_after_ot=False,
)

# 27 points per team. Dispersion 256/54 makes a full-game margin standard
# deviation of 16: 2 * (256/54) * 27 = 16**2.
# ``ot_period_seconds`` is only here because SportConfig requires a positive
# length. College overtime is not that clock. The model does not read it.
NCAAF_CONFIG = SportConfig(
    sport="ncaaf",
    family="football",
    regulation_periods=4,
    period_seconds=15 * 60,
    mean_score_per_team=27.0,
    score_dispersion=256 / 54,
    ot_period_seconds=10 * 60,
    tie_after_ot=False,
)
