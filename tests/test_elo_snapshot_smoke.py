"""Smoke check of the copied Elo snapshot and the pro prior chain.

Loads the real ``data/elo_snapshot.json``. One home/away pair per pro
sport. No sockets, and no playoff-lab import.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from live_win_prob.priors import elo_prior_home, load_snapshot
from ms_win_prob.basketball.config import NBA_CONFIG
from ms_win_prob.compute import prior_for_site
from ms_win_prob.football.config import NFL_CONFIG
from ms_win_prob.hockey.config import NHL_CONFIG
from ms_win_prob.state import GameState

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "elo_snapshot.json"
AS_OF = datetime(2026, 10, 22, 18, 0, tzinfo=timezone.utc)
MONEYLINE = 0.61

# Home, away. All six clubs are in the copied snapshot.
PAIRS = (
    ("nfl", "DEN", "NYG", NFL_CONFIG),
    ("nhl", "COL", "EDM", NHL_CONFIG),
    ("nba", "LAL", "DEN", NBA_CONFIG),
)


def _state(
    sport: str,
    home: str,
    away: str,
    prior: float,
    prior_source: str,
    *,
    neutral: bool,
    period_seconds: int,
    regulation_seconds: int,
) -> GameState:
    return GameState(
        sport=sport,
        game_id=f"elo-smoke-{sport}",
        home=home,
        away=away,
        home_score=0,
        away_score=0,
        period=1,
        seconds_remaining_period=period_seconds,
        seconds_remaining_total=regulation_seconds,
        status="pre",
        source="elo-snapshot-smoke",
        as_of=AS_OF,
        prior_home=prior,
        prior_source=prior_source,
        neutral=neutral,
    )


def test_real_snapshot_prior_chain_for_one_pair_per_pro_sport() -> None:
    on_disk = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert load_snapshot() == on_disk

    for sport, home, away, config in PAIRS:
        teams = on_disk["sports"][sport]["teams"]
        assert home in teams
        assert away in teams
        assert config.sport == sport
        assert config.home_advantage == 0.0

        elo = elo_prior_home(sport, home, away)
        assert elo is not None

        elo_home = _state(
            sport,
            home,
            away,
            elo,
            "elo",
            neutral=False,
            period_seconds=config.period_seconds,
            regulation_seconds=config.regulation_seconds,
        )
        assert elo_home.neutral is False
        assert (
            prior_for_site(elo_home, elo, config, elo_home.prior_source) is elo
        )

        market = _state(
            sport,
            home,
            away,
            MONEYLINE,
            "moneyline",
            neutral=False,
            period_seconds=config.period_seconds,
            regulation_seconds=config.regulation_seconds,
        )
        assert (
            prior_for_site(market, MONEYLINE, config, market.prior_source)
            is MONEYLINE
        )

        neutral = _state(
            sport,
            home,
            away,
            elo,
            "elo",
            neutral=True,
            period_seconds=config.period_seconds,
            regulation_seconds=config.regulation_seconds,
        )
        assert (
            prior_for_site(neutral, elo, config, neutral.prior_source) is elo
        )
