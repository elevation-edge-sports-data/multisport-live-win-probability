"""Basketball-pack configs. NBA and NCAAB share the pack."""

from __future__ import annotations

from mswp.config import SportConfig

NBA_CONFIG = SportConfig(
    sport="nba",
    family="basketball",
    regulation_periods=4,
    period_seconds=12 * 60,
    mean_score_per_team=114.0,
    score_dispersion=1.05,
    ot_period_seconds=5 * 60,
    tie_after_ot=False,
)

NCAAB_CONFIG = SportConfig(
    sport="ncaab",
    family="basketball",
    regulation_periods=2,
    period_seconds=20 * 60,
    mean_score_per_team=72.0,
    score_dispersion=1.05,
    ot_period_seconds=5 * 60,
    tie_after_ot=False,
)

NBA_POSSESSION_POINTS = 1.12
NCAAB_POSSESSION_POINTS = 1.04
