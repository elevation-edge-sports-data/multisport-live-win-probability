"""Club colors for the replay widget. No logos and no remote assets.

Demo matchups live in data/colors/demo.json. ``team_color`` still returns
the primary hex so existing replay renderers keep working. Other NFL and
NHL clubs keep a primary-only entry.
"""

from __future__ import annotations

import json
from pathlib import Path

# Primary hexes for clubs that are not in the demo palette. Jacksonville
# teal stays here. Denver's full palette is in the demo file. Unknown names,
# including Harbor and Red Oak, are omitted.
NFL_PRIMARY: dict[str, str] = {
    "ARI": "#97233F",
    "ATL": "#A71930",
    "BAL": "#241773",
    "BUF": "#00338D",
    "CAR": "#0085CA",
    "CHI": "#0B162A",
    "CIN": "#FB4F14",
    "CLE": "#311D00",
    "DAL": "#003594",
    "DEN": "#FB4F14",
    "DET": "#0076B6",
    "GB": "#203731",
    "HOU": "#03202F",
    "IND": "#002C5F",
    "JAX": "#006778",
    "KC": "#E31837",
    "LAC": "#0080C6",
    "LAR": "#003594",
    "LV": "#000000",
    "MIA": "#008E97",
    "MIN": "#4F2683",
    "NE": "#002244",
    "NO": "#D3BC8D",
    "NYG": "#0B2265",
    "NYJ": "#125740",
    "PHI": "#004C54",
    "PIT": "#FFB612",
    "SEA": "#002244",
    "SF": "#AA0000",
    "TB": "#D50A0A",
    "TEN": "#0C2340",
    "WAS": "#5A1414",
    "WSH": "#5A1414",
}

# Georgia Tech gold is the home color on the Colorado at Georgia Tech
# replay. Colorado's primary is gold in the demo palette.
NCAAF_PRIMARY: dict[str, str] = {
    "GT": "#B3A369",
}

# NHL primaries are separate from the NFL map. Minnesota's football purple
# is not the Wild's forest green, and Colorado's football navy is not the
# Avalanche burgundy.
NHL_PRIMARY: dict[str, str] = {
    "COL": "#6F263D",
    "MIN": "#154734",
    "EDM": "#FF4C00",
}

NCAAH_PRIMARY: dict[str, str] = {
    "DEN": "#8B2332",
    "MICH": "#FFCB05",
}

_CLUBS: list[dict[str, object]] | None = None


def _demo_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "colors" / "demo.json"


def demo_clubs() -> list[dict[str, object]]:
    """Rows from the demo palette. One row per sport, even when the id repeats."""
    global _CLUBS
    if _CLUBS is None:
        payload = json.loads(_demo_path().read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("demo colors must be a list")
        _CLUBS = payload
    return _CLUBS


def club_colors(name: str, sport: str = "nfl") -> dict[str, object] | None:
    """Primary, secondary, white, and owns_black for one demo club."""
    if not isinstance(name, str) or not isinstance(sport, str):
        return None
    key = name.strip().upper()
    if not key:
        return None
    sport_key = sport.strip().lower()
    for row in demo_clubs():
        if str(row.get("sport", "")).lower() != sport_key:
            continue
        names = [str(row.get("id", "")).upper()]
        aliases = row.get("aliases") or []
        if isinstance(aliases, list):
            names.extend(str(alias).upper() for alias in aliases)
        if key in names:
            return row
    return None


def team_color(name: str, sport: str = "nfl") -> str | None:
    """Primary color for an abbreviation, or None when it is unknown."""
    if not isinstance(name, str):
        return None
    club = club_colors(name, sport)
    if club is not None:
        primary = club.get("primary")
        if isinstance(primary, str):
            return primary
    key = name.strip().upper()
    if sport == "ncaaf":
        return NCAAF_PRIMARY.get(key)
    if sport == "nhl":
        return NHL_PRIMARY.get(key)
    if sport == "ncaah":
        return NCAAH_PRIMARY.get(key)
    if sport == "nfl":
        return NFL_PRIMARY.get(key)
    return None
