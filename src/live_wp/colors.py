"""Primary colors for the replay widget. No logos and no remote assets."""

from __future__ import annotations

# One primary hex per club. Jacksonville teal and Denver orange are the
# demo pair. Unknown names, including Harbor and Red Oak, are omitted.
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

# College primaries for the widget demo. Georgia Tech gold is the home
# color. Colorado is black; a gold accent is not the primary. Unknown
# abbreviations, including the TEX–OU sample, are omitted.
CFB_PRIMARY: dict[str, str] = {
    "GT": "#B3A369",
    "COLO": "#000000",
    "CU": "#000000",
}

# NHL primaries are separate from the NFL map. Minnesota's football purple
# is not the Wild's forest green, and Colorado's football navy is not the
# Avalanche burgundy.
NHL_PRIMARY: dict[str, str] = {
    "COL": "#6F263D",
    "MIN": "#154734",
}


def team_color(name: str, sport: str = "nfl") -> str | None:
    """Primary color for an abbreviation, or None when it is unknown."""
    if not isinstance(name, str):
        return None
    key = name.strip().upper()
    if sport == "cfb":
        return CFB_PRIMARY.get(key)
    if sport == "nhl":
        return NHL_PRIMARY.get(key)
    if sport == "nfl":
        return NFL_PRIMARY.get(key)
    return None
