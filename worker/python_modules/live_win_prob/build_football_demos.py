"""Stamp moneyline priors on the NYG–DEN and COLO–GT replays and render them."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from live_win_prob.replay import dump_replay, load_replay, render_widget_script
from ms_win_prob.state import GameState

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
REPLAYS = ROOT / "replays"


def build_football_demos() -> int:
    nfl = _stamp(EXAMPLES / "nfl_nyg_den.json", 425 / 525)  # DEN -425
    ncaaf = _stamp(EXAMPLES / "ncaaf_cu_gt.json", 238 / 338)  # GT -238
    print(f"NFL NYG@DEN snapshots={len(nfl)}")
    print(f"NCAAF COLO@GT snapshots={len(ncaaf)}")
    return 0


def _stamp(path: Path, prior: float) -> list[GameState]:
    states = [replace(state, prior_home=prior) for state in load_replay(path)]
    path.write_text(dump_replay(states), encoding="utf-8", newline="\n")
    sport, _, rest = path.stem.partition("_")
    dest = REPLAYS / sport / f"{rest}.js"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_widget_script(states), encoding="utf-8", newline="\n")
    return states
