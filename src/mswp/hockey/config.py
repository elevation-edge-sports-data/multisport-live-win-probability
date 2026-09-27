"""Hockey-pack config. NHL uses this pack."""

from __future__ import annotations

from mswp.config import SportConfig

# About 3.05 goals per team across three 20-minute periods.
# Dispersion 1 is a Poisson pair. The implied full-game goal-differential
# standard deviation is sqrt(6.1): 2 * 1 * 3.05 = 6.1.
# Overtime here is playoff sudden death, a 20:00 period. It is not the
# regular-season 3-on-3 overtime of 5:00. A scoreless playoff period
# starts another 20:00. ``tie_after_ot`` is false for that reason.
NHL_CONFIG = SportConfig(
    sport="nhl",
    family="hockey",
    regulation_periods=3,
    period_seconds=20 * 60,
    mean_score_per_team=3.05,
    score_dispersion=1.0,
    ot_period_seconds=20 * 60,
    tie_after_ot=False,
)
