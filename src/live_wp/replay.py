"""Load a JSON replay of GameState snapshots and format lines for the CLI.

Optional football fields (down, distance, yard line, possession, timeouts)
are stored on GameState when the row has them. The model uses possession,
down, distance, and yard line only when all four are present. It does not
read timeouts.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from mswp import (
    NCAAF_CONFIG,
    DEFAULT_PRIOR_HOME,
    GameState,
    NFL_CONFIG,
    NCAAH_CONFIG,
    NHL_CONFIG,
    compute_wp,
)
from mswp.basketball.config import NBA_CONFIG, NCAAB_CONFIG
from mswp.config import SportConfig

from live_wp.colors import team_color

# Marks live under assets/logos. The path is relative to the repo root page.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_WIDGET_DIR = _REPO_ROOT / "widget"
_LOGO_ROOT = _REPO_ROOT / "assets" / "logos"
_LOGO_SPORTS = ("nfl", "nhl", "nba", "ncaaf", "ncaah", "ncaab")
_LOGO_NAMES: dict[str, dict[str, str]] | None = None
_BINDING_RE = re.compile(r"window\.(NFL|NHL|NBA|NCAAF|NCAAH|NCAAB)_REPLAY\s*=")
_SPORT_ORDER = ("nfl", "nhl", "nba", "ncaaf", "ncaah", "ncaab")
# The page opens the first NFL entry. Keep the six presentation demos first in each sport.
_DEMO_FILE = {
    "nfl": "nfl_nyg_den.js",
    "nhl": "nhl_edm_col.js",
    "nba": "nba_den_lal.js",
    "ncaaf": "ncaaf_cu_ttu.js",
    "ncaah": "ncaah_den_mich.js",
    "ncaab": "ncaab_cu_fla.js",
}

_REQUIRED = (
    "sport",
    "game_id",
    "home",
    "away",
    "home_score",
    "away_score",
    "period",
    "seconds_remaining_period",
    "seconds_remaining_total",
    "status",
    "source",
    "as_of",
)


def load_replay(path: Path | str) -> list[GameState]:
    """Read a JSON list of snapshots, in file order."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("replay file must be a non-empty JSON list")
    return [game_state_from_row(row) for row in payload]


def _as_int(row: Mapping[str, object], name: str) -> int:
    value = row[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    return value


def game_state_from_row(row: Mapping[str, object]) -> GameState:
    """Map one feed row to a GameState.

    Optional football fields are stored when present. The win-probability
    model does not read them.
    """
    if not isinstance(row, Mapping):
        raise TypeError("replay row must be a JSON object")
    missing = [name for name in _REQUIRED if name not in row]
    if missing:
        raise ValueError(f"replay row missing {', '.join(missing)}")
    as_of = row["as_of"]
    if not isinstance(as_of, str):
        raise TypeError("as_of must be an ISO-8601 string")
    prior = row["prior_home"] if "prior_home" in row else DEFAULT_PRIOR_HOME
    optional: dict[str, object] = {}
    for name in ("down", "distance", "yardline"):
        if name in row and row[name] is not None:
            optional[name] = _as_int(row, name)
    if row.get("possession") not in (None, ""):
        optional["possession"] = str(row["possession"])
    if row.get("strength") not in (None, ""):
        optional["strength"] = str(row["strength"])
    if "extra_attacker" in row and row["extra_attacker"] is not None:
        extra = row["extra_attacker"]
        if not isinstance(extra, bool):
            raise TypeError("extra_attacker must be a bool")
        optional["extra_attacker"] = extra
    if "timeouts" in row and row["timeouts"] is not None:
        optional["timeouts"] = _timeout_map(row["timeouts"])
    return GameState(
        sport=str(row["sport"]),
        game_id=str(row["game_id"]),
        home=str(row["home"]),
        away=str(row["away"]),
        home_score=_as_int(row, "home_score"),
        away_score=_as_int(row, "away_score"),
        period=_as_int(row, "period"),
        seconds_remaining_period=_as_int(row, "seconds_remaining_period"),
        seconds_remaining_total=_as_int(row, "seconds_remaining_total"),
        status=str(row["status"]),  # type: ignore[arg-type]
        source=str(row["source"]),
        as_of=datetime.fromisoformat(as_of.replace("Z", "+00:00")),
        prior_home=float(prior),  # type: ignore[arg-type]
        **optional,  # type: ignore[arg-type]
    )


def _timeout_map(raw: object) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        raise TypeError("timeouts must be an object")
    parsed: dict[str, int] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"timeouts.{key} must be an int")
        parsed[str(key)] = value
    return parsed


def state_to_row(state: GameState) -> dict[str, object]:
    """JSON object for one snapshot. Absent football fields are omitted."""
    if state.as_of.tzinfo is None:
        as_of = state.as_of.replace(microsecond=0).isoformat(timespec="seconds")
    else:
        utc = state.as_of.astimezone(timezone.utc).replace(microsecond=0)
        as_of = utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    row: dict[str, object] = {
        "sport": state.sport,
        "game_id": state.game_id,
        "home": state.home,
        "away": state.away,
        "home_score": state.home_score,
        "away_score": state.away_score,
        "period": state.period,
        "seconds_remaining_period": state.seconds_remaining_period,
        "seconds_remaining_total": state.seconds_remaining_total,
        "status": state.status,
        "prior_home": state.prior_home,
    }
    if state.possession is not None:
        row["possession"] = state.possession
    if state.down is not None:
        row["down"] = state.down
    if state.distance is not None:
        row["distance"] = state.distance
    if state.yardline is not None:
        row["yardline"] = state.yardline
    if state.timeouts is not None:
        row["timeouts"] = {
            "home": int(state.timeouts["home"]),
            "away": int(state.timeouts["away"]),
        }
    if state.strength is not None:
        row["strength"] = state.strength
    if state.extra_attacker is not None:
        row["extra_attacker"] = state.extra_attacker
    row["source"] = state.source
    row["as_of"] = as_of
    return row


def dump_replay(states: list[GameState]) -> str:
    """Serialize snapshots in the same shape ``load_replay`` reads."""
    return json.dumps([state_to_row(state) for state in states], indent=2) + "\n"


def config_for_state(state: GameState) -> SportConfig:
    """Config for one replay snapshot, including the basketball packs."""
    if state.sport == "ncaaf":
        return NCAAF_CONFIG
    if state.sport == "nhl":
        return NHL_CONFIG
    if state.sport == "ncaah":
        return NCAAH_CONFIG
    if state.sport == "nba":
        return NBA_CONFIG
    if state.sport == "ncaab":
        return NCAAB_CONFIG
    if state.sport == "nfl":
        return NFL_CONFIG
    raise ValueError(
        f"replay sport {state.sport!r} is not nfl, nba, ncaaf, ncaah, ncaab, or nhl"
    )


def format_clock(state: GameState) -> str:
    """Period clock label. A final snapshot is labeled FINAL.

    Football regulation is Q1-Q4. Period 5 is OT and period 6 is 2OT.
    College basketball regulation is H1-H2. Period 3 is OT.
    Hockey regulation is P1-P3. Period 4 is OT and period 5 is 2OT.
    """
    if state.status == "final":
        return "FINAL"
    minutes, seconds = divmod(state.seconds_remaining_period, 60)
    return f"{_period_label(state)} {minutes}:{seconds:02d}"


def _period_label(state: GameState) -> str:
    if state.sport in {"nhl", "ncaah"}:
        if state.period <= 3:
            return f"P{state.period}"
        if state.period == 4:
            return "OT"
        return f"{state.period - 3}OT"
    if state.sport == "ncaab":
        if state.period <= 2:
            return f"H{state.period}"
        if state.period == 3:
            return "OT"
        return f"{state.period - 2}OT"
    if state.period <= 4:
        return f"Q{state.period}"
    if state.period == 5:
        return "OT"
    return f"{state.period - 4}OT"


def format_line(state: GameState, wp: float) -> str:
    """One CLI line: time, score, home win probability."""
    score = f"{state.home} {state.home_score}, {state.away} {state.away_score}"
    return f"{format_clock(state)} | {score} | {wp:.3f}"


def _logo_names() -> dict[str, dict[str, str]]:
    """Filename stems keyed by sport and uppercase stem.

    The directory entry keeps its own spelling. A case-insensitive volume
    would otherwise treat ``jax.png`` as the file ``JAX.png``.
    """
    global _LOGO_NAMES
    if _LOGO_NAMES is None:
        index: dict[str, dict[str, str]] = {}
        for sport in _LOGO_SPORTS:
            folder = _LOGO_ROOT / sport
            names: dict[str, str] = {}
            if folder.is_dir():
                for entry in folder.iterdir():
                    if entry.suffix.lower() != ".png":
                        continue
                    names[entry.stem.upper()] = entry.stem
            index[sport] = names
        _LOGO_NAMES = index
    return _LOGO_NAMES


def team_logo(name: str, *, sport: str = "nfl") -> str | None:
    """Logo URL relative to the repo root page when the PNG exists.

    The file is ``assets/logos/{sport}/{stem}.png``. Unknown names,
    including Harbor and Red Oak, return None so the page can omit the
    image. Each sport has its own folder. A missing file hides the image.
    """
    if sport not in _LOGO_SPORTS or not isinstance(name, str):
        return None
    abbr = name.strip()
    if not abbr or "/" in abbr or "\\" in abbr or ".." in abbr:
        return None
    stem = _logo_names().get(sport, {}).get(abbr.upper())
    if stem is None:
        return None
    return f"assets/logos/{sport}/{stem}.png"


_SITUATION_FIELDS = (
    "possession",
    "down",
    "distance",
    "yardline",
    "timeouts",
    "strength",
    "extra_attacker",
)


def _frame_timeouts(state: GameState) -> dict[str, int]:
    """Timeouts keyed by team abbreviation.

    GameState stores ``home`` and ``away``. The frame uses the abbreviations
    on the snapshot, away then home. A mapping that is already keyed by
    abbreviation is copied through.
    """
    raw = state.timeouts
    assert raw is not None
    if set(raw) == {"home", "away"}:
        return {state.away: int(raw["away"]), state.home: int(raw["home"])}
    return {str(key): int(value) for key, value in raw.items()}


def _situation_fields(state: GameState) -> dict[str, object]:
    """Situation keys that this snapshot actually set."""
    copied: dict[str, object] = {}
    for name in _SITUATION_FIELDS:
        value = getattr(state, name)
        if value is None:
            continue
        if name == "timeouts":
            copied[name] = _frame_timeouts(state)
        else:
            copied[name] = value
    return copied


def elapsed_game_seconds(state: GameState) -> int:
    """Seconds from kickoff, read from the game clock on the snapshot.

    College overtime is not a timed period, so extra periods stay at the
    end of regulation. NFL and NHL overtime still add the timed period.
    """
    config = config_for_state(state)
    if state.period <= config.regulation_periods:
        remaining = min(state.seconds_remaining_total, config.regulation_seconds)
        return config.regulation_seconds - remaining
    if state.sport == "ncaaf":
        return config.regulation_seconds
    remaining_ot = min(state.seconds_remaining_total, config.ot_period_seconds)
    return config.regulation_seconds + (config.ot_period_seconds - remaining_ot)


def render_widget_script(states: list[GameState], *, live: bool = False) -> str:
    """JavaScript assignment of the replay, including precomputed home win probability.

    The page displays those values. It does not carry a second model.
    NFL replays bind ``window.NFL_REPLAY``. College replays bind
    ``window.NCAAF_REPLAY``. NHL replays bind ``window.NHL_REPLAY``.
    A college frame includes a logo path only when that abbreviation's PNG
    is on disk. A known abbreviation still gets its primary color. NHL
    logos are used only when the PNG is on disk.

    ``live`` keeps that sport binding and also assigns ``window.MSWP_LIVE``
    to the same array. Each live frame includes ``sport``, ``away``, and
    ``home``. Archive renders omit both so loading a saved replay does not
    become the live game.

    Possession, down, distance, yard line, timeouts, strength, and extra
    attacker are copied only when that snapshot set them. Timeouts stay a
    mapping of team abbreviation to int. ``home`` and ``away`` keys are
    written as the snapshot's abbreviations, away then home.
    """
    if not states:
        raise ValueError("replay file must be a non-empty JSON list")
    config = config_for_state(states[0])
    for state in states:
        if state.sport != config.sport:
            raise ValueError("replay mixes sports")
    binding = {
        "nfl": "window.NFL_REPLAY",
        "ncaaf": "window.NCAAF_REPLAY",
        "nhl": "window.NHL_REPLAY",
        "ncaah": "window.NCAAH_REPLAY",
        "nba": "window.NBA_REPLAY",
        "ncaab": "window.NCAAB_REPLAY",
    }[config.sport]
    frames = []
    for state in states:
        wp = compute_wp(state, state.prior_home, config)
        frame: dict[str, object] = {
            "clock": format_clock(state),
            "wp": wp,
            "home": state.home,
            "away": state.away,
            "home_score": state.home_score,
            "away_score": state.away_score,
            "status": state.status,
            "period": state.period,
            "seconds_remaining_period": state.seconds_remaining_period,
            "seconds_remaining_total": state.seconds_remaining_total,
            "prior_home": state.prior_home,
            "game_id": state.game_id,
            "elapsed_seconds": elapsed_game_seconds(state),
        }
        if live:
            frame = {"sport": config.sport, **frame}
        frame.update(_situation_fields(state))
        home_color = team_color(state.home, state.sport)
        away_color = team_color(state.away, state.sport)
        if home_color is not None:
            frame["home_color"] = home_color
        if away_color is not None:
            frame["away_color"] = away_color
        if config.sport in _LOGO_SPORTS:
            home_logo = team_logo(state.home, sport=config.sport)
            away_logo = team_logo(state.away, sport=config.sport)
            if home_logo is not None:
                frame["home_logo"] = home_logo
            if away_logo is not None:
                frame["away_logo"] = away_logo
        frames.append(frame)
    body = json.dumps(frames, indent=2)
    script = (
        "// Precomputed by compute_wp.\n"
        "// The widget displays these values and does not run a second model.\n"
        f"{binding} = {body};\n"
    )
    if live:
        script += f"window.MSWP_LIVE = {binding};\n"
    return script


def _manifest_sort_key(entry: dict[str, str]) -> tuple[int, int, str]:
    sport = entry["sport"]
    sport_index = _SPORT_ORDER.index(sport) if sport in _SPORT_ORDER else len(_SPORT_ORDER)
    demo_first = 0 if entry["file"] == _DEMO_FILE.get(sport) else 1
    return (sport_index, demo_first, entry["file"])


def _is_harbor_replay(home: object, away: object) -> bool:
    """True for the Red Oak at Harbor prototype on either side of the ball."""
    names = []
    for name in (home, away):
        if isinstance(name, str):
            names.append(name.strip().casefold())
    return "harbor" in names


def manifest_entry(path: Path) -> dict[str, str] | None:
    """One picker row from a rendered replay script, or None if it is not one.

    ``live_replay.js`` is the file ``python -m live_wp live`` rewrites. It is
    not a game button. A replay whose home or away team is Harbor is the
    nfl_sample prototype. That file stays on disk and is omitted here.
    """
    if path.name == "live_replay.js":
        return None
    text = path.read_text(encoding="utf-8")
    match = _BINDING_RE.search(text)
    if match is None:
        return None
    start = text.find("[")
    if start < 0:
        raise ValueError(f"{path.name} has no replay frames")
    frames, _end = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(frames, list) or not frames or not isinstance(frames[0], dict):
        raise ValueError(f"{path.name} has no replay frames")
    away = frames[0].get("away")
    home = frames[0].get("home")
    if not isinstance(away, str) or not isinstance(home, str) or not away or not home:
        raise ValueError(f"{path.name} replay frame is missing teams")
    if _is_harbor_replay(home, away):
        return None
    return {
        "sport": match.group(1).lower(),
        "away": away,
        "home": home,
        "label": f"{away} at {home}",
        "file": path.name,
    }


def manifest_entries(directory: Path | None = None) -> list[dict[str, str]]:
    """Rendered replays under ``directory``, demo matchups first within each sport.

    ``live_replay.js`` and the Harbor prototype are omitted.
    """
    widget = Path(directory) if directory is not None else _WIDGET_DIR
    entries: list[dict[str, str]] = []
    for path in sorted(widget.glob("*.js")):
        entry = manifest_entry(path)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=_manifest_sort_key)
    return entries


def render_manifest_script(entries: list[dict[str, str]]) -> str:
    """JavaScript assignment of the game list. The page does not fetch it."""
    body = json.dumps(entries, indent=2)
    return (
        "// Rendered replays the page can open.\n"
        "// The page lists these files and does not fetch.\n"
        f"window.MSWP_MANIFEST = {body};\n"
    )


def write_manifest(directory: Path | None = None) -> Path:
    """Write ``manifest.js`` for the replays the picker can open."""
    widget = Path(directory) if directory is not None else _WIDGET_DIR
    dest = widget / "manifest.js"
    dest.write_text(
        render_manifest_script(manifest_entries(widget)),
        encoding="utf-8",
        newline="\n",
    )
    return dest


def refresh_manifest_if_widget(dest: Path) -> None:
    """Rewrite ``widget/manifest.js`` when ``dest`` is a script in that directory."""
    if dest.resolve().parent == _WIDGET_DIR.resolve():
        write_manifest(_WIDGET_DIR)
