"""Basketball-pack configs. NBA and NCAAB share the pack."""

from __future__ import annotations

from ms_win_prob.config import SportConfig

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

# 1.40 won the moneyline possession grid: 1015 games, 127222 snapshots,
# Brier 0.139094. The previous production value was 1.30.
NBA_POSSESSION_POINTS = 1.40
NCAAB_POSSESSION_POINTS = 1.04
