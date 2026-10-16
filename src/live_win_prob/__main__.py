"""python -m live_win_prob replay|ingest-espn|render-widget|write-manifest|follow|live|slate|serve|calibrate|tune-nfl"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ms_win_prob import compute_win_prob

from live_win_prob.calibrate import run_calibrate
from live_win_prob.tune import run_tune_nfl
from live_win_prob.feeds import states_from_ingest
from live_win_prob.feeds.espn import DENSITIES
from live_win_prob.follow import run_follow
from live_win_prob.live import run_live
from live_win_prob.replay import (
    config_for_state,
    dump_replay,
    format_line,
    load_replay,
    refresh_manifest_if_widget,
    render_widget_script,
    write_manifest,
)
from live_win_prob.serve import run_serve
from live_win_prob.slate import run_slate

_USAGE = """\
usage: python -m live_win_prob replay <json>
       python -m live_win_prob ingest-espn <in.json> <out.json> [--density scoring|situation|all]
       python -m live_win_prob render-widget <replay.json> <out.js>
       python -m live_win_prob write-manifest
       python -m live_win_prob follow [--date YYYYMMDD] [--game ESPN_EVENT_ID] [--interval 15] [--sport nfl|nhl|nba|ncaaf|ncaah|ncaab]
       python -m live_win_prob live [--game ESPN_EVENT_ID] [--sport nfl|nhl|nba] [--interval 15] [--out replays/live_replay.js]
       python -m live_win_prob slate [--date YYYYMMDD] [--interval 15] [--out slate.js] [--sport nfl|nhl|nba|ncaaf|ncaah|ncaab]
       python -m live_win_prob serve [--port 8765]
       python -m live_win_prob calibrate [replay-or-espn.json ...]
       python -m live_win_prob tune-nfl [--mean MEAN_SCORE_PER_TEAM]
       python -m live_win_prob build-football-demos
       python -m live_win_prob build-hockey-demos
       python -m live_win_prob build-basketball-demos\
"""


def replay_to_stdout(path: Path) -> int:
    if not path.is_file():
        print(f"replay file not found: {path}", file=sys.stderr)
        return 1
    for state in load_replay(path):
        win_prob = compute_win_prob(state, state.prior_home, config_for_state(state))
        print(format_line(state, win_prob))
    return 0


def ingest_espn(source: Path, dest: Path, density: str = "scoring") -> int:
    if density not in DENSITIES:
        print(f"density must be one of {', '.join(DENSITIES)}", file=sys.stderr)
        return 2
    if not source.is_file():
        print(f"ESPN file not found: {source}", file=sys.stderr)
        return 1
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        states = states_from_ingest(payload, density=density)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(dump_replay(states), encoding="utf-8")
    return 0


def render_widget(source: Path, dest: Path) -> int:
    if not source.is_file():
        print(f"replay file not found: {source}", file=sys.stderr)
        return 1
    try:
        script = render_widget_script(load_replay(source))
    except (TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(script, encoding="utf-8", newline="\n")
    try:
        refresh_manifest_if_widget(dest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def write_manifest_command() -> int:
    try:
        write_manifest()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 2 and args[0] == "replay":
        return replay_to_stdout(Path(args[1]))
    if args and args[0] == "ingest-espn":
        density = "scoring"
        paths = args[1:]
        if len(paths) == 4 and paths[2] == "--density":
            density = paths[3]
            paths = paths[:2]
        elif len(paths) >= 1 and paths[-1].startswith("--density="):
            density = paths[-1].split("=", 1)[1]
            paths = paths[:-1]
        if len(paths) != 2:
            print(_USAGE, file=sys.stderr)
            return 2
        return ingest_espn(Path(paths[0]), Path(paths[1]), density)
    if len(args) == 3 and args[0] == "render-widget":
        return render_widget(Path(args[1]), Path(args[2]))
    if args == ["write-manifest"]:
        return write_manifest_command()
    if args and args[0] == "follow":
        return run_follow(args[1:])
    if args and args[0] == "live":
        return run_live(args[1:])
    if args and args[0] == "slate":
        return run_slate(args[1:])
    if args and args[0] == "serve":
        return run_serve(args[1:])
    if args and args[0] == "calibrate":
        return run_calibrate(args[1:])
    if args and args[0] == "tune-nfl":
        return run_tune_nfl(args[1:])
    if args and args[0] == "build-football-demos":
        from live_win_prob.build_football_demos import build_football_demos

        return build_football_demos()
    if args and args[0] == "build-hockey-demos":
        from live_win_prob.build_hockey_demos import build_hockey_demos

        return build_hockey_demos()
    if args and args[0] == "build-basketball-demos":
        from live_win_prob.build_basketball_demos import build_basketball_demos

        return build_basketball_demos()
    print(_USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
