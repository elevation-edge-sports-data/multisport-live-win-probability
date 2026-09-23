"""python -m live_wp replay <fixture.json>"""

from __future__ import annotations

import sys
from pathlib import Path

from mswp import NFL_CONFIG as nfl_config
from mswp import compute_wp

from live_wp.replay import format_line, load_replay


def replay_to_stdout(path: Path) -> int:
    if not path.is_file():
        print(f"replay file not found: {path}", file=sys.stderr)
        return 1
    for state in load_replay(path):
        wp = compute_wp(state, state.prior_home, nfl_config)
        print(format_line(state, wp))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 2 and args[0] == "replay":
        return replay_to_stdout(Path(args[1]))
    print("usage: python -m live_wp replay <path>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
