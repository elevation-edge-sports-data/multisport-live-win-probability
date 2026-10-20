"""Static Elo priors for NFL, NHL, and NBA.

``data/elo_snapshot.json`` is a copied export. This package does not import
the playoff-lab package. Refresh the file by copying
``outputs/elo_snapshot.json`` from that repo.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "data" / "elo_snapshot.json"
_ELO_SPORTS = frozenset({"nfl", "nhl", "nba"})


@lru_cache(maxsize=1)
def load_snapshot() -> dict[str, Any]:
    """Read ``data/elo_snapshot.json`` once and reuse the parsed object."""
    payload = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("elo snapshot must be a JSON object")
    return payload


def elo_prior_home(sport: str, home: str, away: str) -> float | None:
    """Home win probability from the snapshot, or None when it cannot be used.

    Only ``nfl``, ``nhl``, and ``nba`` are attempted. The sport's
    ``home_advantage`` is added to the home rating. No further boost is
    applied. Missing sports, missing clubs, and any read or math error
    return None.
    """
    if not isinstance(sport, str):
        return None
    key = sport.strip().lower()
    if key not in _ELO_SPORTS:
        return None
    if not isinstance(home, str) or not isinstance(away, str):
        return None
    home_key = home.strip()
    away_key = away.strip()
    if not home_key or not away_key:
        return None
    try:
        block = load_snapshot()["sports"][key]
        teams = block["teams"]
        home_elo = float(teams[home_key]) + float(block["home_advantage"])
        away_elo = float(teams[away_key])
        prior = 1.0 / (1.0 + 10.0 ** ((away_elo - home_elo) / 400.0))
    except Exception:
        return None
    if isinstance(prior, bool) or not isinstance(prior, float):
        return None
    if prior != prior or not 0.0 < prior < 1.0:
        return None
    return prior
