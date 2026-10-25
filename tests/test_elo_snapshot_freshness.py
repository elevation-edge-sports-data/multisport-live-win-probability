"""The checked-in Elo snapshot has a numeric home advantage for each pro sport."""

from __future__ import annotations

import json
import math
from pathlib import Path

_SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "elo_snapshot.json"
_SPORTS = ("nfl", "nhl", "nba")


def test_snapshot_home_advantage_keys_are_numeric() -> None:
    payload = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    sports = payload["sports"]
    for sport in _SPORTS:
        assert sport in sports
        assert "home_advantage" in sports[sport]
        value = sports[sport]["home_advantage"]
        assert not isinstance(value, bool)
        assert isinstance(value, (int, float))
        assert math.isfinite(value)
