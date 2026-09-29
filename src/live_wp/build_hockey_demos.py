"""Build COL–EDM NHL and DEN–MICH NCAAH demos."""

from __future__ import annotations

from pathlib import Path

from live_wp.feeds.espn_hockey import events_from_espn_hockey, load_summary
from live_wp.feeds.sidearm_hockey import events_from_gamebook_text, load_gamebook_text
from live_wp.replay import dump_replay, render_widget_script
from live_wp.thin import thin_states
from mswp.hockey.config import NCAAH_CONFIG, NHL_CONFIG

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
EXAMPLES = ROOT / "examples"
WIDGET = ROOT / "widget"


def build_hockey_demos() -> int:
    nhl_full, nhl_thin = _nhl()
    ncaah_full, ncaah_thin = _ncaah()
    print(f"NHL EDM@COL events={nhl_full} thinned={nhl_thin}")
    print(f"NCAAH MICH@DEN events={ncaah_full} thinned={ncaah_thin}")
    return 0


def _nhl() -> tuple[int, int]:
    payload = load_summary(FIXTURES / "espn_nhl_401442762_summary.json")
    states = events_from_espn_hockey(payload, prior_home=121 / 221)  # COL -121
    EXAMPLES.mkdir(parents=True, exist_ok=True)
    (EXAMPLES / "nhl_edm_col_full.json").write_text(
        dump_replay(states), encoding="utf-8", newline="\n"
    )
    thin = thin_states(states, NHL_CONFIG, eps=0.0005)
    (EXAMPLES / "nhl_edm_col.json").write_text(
        dump_replay(thin), encoding="utf-8", newline="\n"
    )
    (WIDGET / "nhl_edm_col.js").write_text(
        render_widget_script(thin), encoding="utf-8", newline="\n"
    )
    return len(states), len(thin)


def _ncaah() -> tuple[int, int]:
    text = load_gamebook_text(FIXTURES / "ncaah_den_mich_gamebook.txt")
    states = events_from_gamebook_text(text, prior_home=100 / 205)  # DEN +105
    (EXAMPLES / "ncaah_den_mich_full.json").write_text(
        dump_replay(states), encoding="utf-8", newline="\n"
    )
    thin = thin_states(states, NCAAH_CONFIG, eps=0.0005)
    (EXAMPLES / "ncaah_den_mich.json").write_text(
        dump_replay(thin), encoding="utf-8", newline="\n"
    )
    (WIDGET / "ncaah_den_mich.js").write_text(
        render_widget_script(thin), encoding="utf-8", newline="\n"
    )
    return len(states), len(thin)
