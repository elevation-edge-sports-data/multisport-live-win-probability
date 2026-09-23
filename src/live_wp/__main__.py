"""python -m live_wp replay|ingest-espn|render-widget"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mswp import NFL_CONFIG as nfl_config
from mswp import compute_wp

from live_wp.feeds.espn import DENSITIES, states_from_espn
from live_wp.replay import dump_replay, format_line, load_replay, render_widget_script

_USAGE = """\
usage: python -m live_wp replay <json>
       python -m live_wp ingest-espn <in.json> <out.json> [--density scoring|situation|all]
       python -m live_wp render-widget <replay.json> <out.js>\
"""


def replay_to_stdout(path: Path) -> int:
    if not path.is_file():
        print(f"replay file not found: {path}", file=sys.stderr)
        return 1
    for state in load_replay(path):
        wp = compute_wp(state, state.prior_home, nfl_config)
        print(format_line(state, wp))
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
        states = states_from_espn(payload, density=density)
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
    dest.write_text(script, encoding="utf-8")
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
    print(_USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
