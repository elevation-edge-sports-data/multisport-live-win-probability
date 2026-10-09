"""Club colors for the replay widget. No logos and no remote assets.

Colors are read from ``assets/colors/{sport}.json``. A row is keyed by
sport and the logo filename stem. Pro files store that stem in ``id``.
College files still store an ESPN id in ``id`` and the stem in
``abbreviation``. The same stem in another sport is a different club.
"""

from __future__ import annotations

import json
from pathlib import Path

_SPORTS = ("nfl", "nhl", "nba", "ncaaf", "ncaah", "ncaab")
_CLUBS: dict[str, list[dict[str, object]]] | None = None


def _colors_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "colors"


def _stem(row: dict[str, object]) -> str:
    """Logo filename stem. College rows keep that stem on ``abbreviation``."""
    abbreviation = row.get("abbreviation")
    if isinstance(abbreviation, str) and abbreviation.strip():
        return abbreviation.strip()
    ident = row.get("id")
    if isinstance(ident, str) and ident.strip():
        return ident.strip()
    if isinstance(ident, int) and not isinstance(ident, bool):
        return str(ident)
    return ""


def _normalize(row: dict[str, object], sport: str) -> dict[str, object] | None:
    stem = _stem(row)
    if not stem:
        return None
    aliases = row.get("aliases") or []
    if not isinstance(aliases, list):
        aliases = []
    source = row.get("source")
    if not isinstance(source, str):
        source = row.get("color_source")
    return {
        "sport": sport,
        "id": stem,
        "aliases": [str(alias) for alias in aliases],
        "primary": row.get("primary"),
        "secondary": row.get("secondary"),
        "white": row.get("white"),
        "black": row.get("black"),
        "source": source if isinstance(source, str) else None,
        "as_of": row.get("as_of"),
    }


def load_clubs() -> dict[str, list[dict[str, object]]]:
    """One list per sport, keyed by the logo filename stem."""
    global _CLUBS
    if _CLUBS is None:
        loaded: dict[str, list[dict[str, object]]] = {}
        root = _colors_dir()
        for sport in _SPORTS:
            payload = json.loads((root / f"{sport}.json").read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError(f"{sport} colors must be a list")
            rows: list[dict[str, object]] = []
            for row in payload:
                if not isinstance(row, dict):
                    continue
                club = _normalize(row, sport)
                if club is not None:
                    rows.append(club)
            loaded[sport] = rows
        _CLUBS = loaded
    return _CLUBS


def _names(club: dict[str, object]) -> list[str]:
    names = [str(club.get("id", "")).upper()]
    aliases = club.get("aliases") or []
    if isinstance(aliases, list):
        names.extend(str(alias).upper() for alias in aliases)
    return names


def club_colors(name: str, sport: str = "nfl") -> dict[str, object] | None:
    """Palette for one club in one sport, or None when the stem is unknown."""
    if not isinstance(name, str) or not isinstance(sport, str):
        return None
    key = name.strip().upper()
    if not key:
        return None
    sport_key = sport.strip().lower()
    for row in load_clubs().get(sport_key, []):
        if key in _names(row):
            return row
    return None


def team_color(name: str, sport: str = "nfl") -> str | None:
    """Primary color for an abbreviation, or None when it is unknown."""
    club = club_colors(name, sport)
    if club is None:
        return None
    primary = club.get("primary")
    if isinstance(primary, str):
        return primary
    return None
