"""Build the Lakers–Nuggets and Florida–Colorado basketball demos."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from live_wp.feeds.espn_basketball import events_from_espn_basketball, load_summary
from live_wp.replay import dump_replay, render_widget_script
from live_wp.thin import thin_states
from mswp.basketball.config import NCAAB_CONFIG, NBA_CONFIG
from mswp.config import SportConfig
from mswp.state import GameState

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
EXAMPLES = ROOT / "examples"
WIDGET = ROOT / "widget"


def build_basketball_demos() -> int:
    nba_full, nba_thin = _nba()
    ncaab_full, ncaab_thin = _ncaab()
    print(f"NBA DEN@LAL events={nba_full} thinned={nba_thin}")
    print(f"NCAAB COLO@FLA events={ncaab_full} thinned={ncaab_thin}")
    return 0


def _nba() -> tuple[int, int]:
    payload = load_summary(FIXTURES / "espn_nba_401547684_summary.json")
    states = events_from_espn_basketball(payload, prior_home=160 / 260)  # LAL -160
    EXAMPLES.mkdir(parents=True, exist_ok=True)
    (EXAMPLES / "nba_den_lal_full.json").write_text(
        dump_replay(states), encoding="utf-8", newline="\n"
    )
    thin = thin_basketball(states, NBA_CONFIG)
    (EXAMPLES / "nba_den_lal.json").write_text(
        dump_replay(thin), encoding="utf-8", newline="\n"
    )
    (WIDGET / "nba_den_lal.js").write_text(
        render_widget_script(thin), encoding="utf-8", newline="\n"
    )
    return len(states), len(thin)


def _ncaab() -> tuple[int, int]:
    payload = load_summary(FIXTURES / "espn_ncaab_401638608_summary.json")
    states = events_from_espn_basketball(payload, prior_home=120 / 220)  # FLA -120
    (EXAMPLES / "ncaab_cu_fla_full.json").write_text(
        dump_replay(states), encoding="utf-8", newline="\n"
    )
    thin = thin_basketball(states, NCAAB_CONFIG)
    (EXAMPLES / "ncaab_cu_fla.json").write_text(
        dump_replay(thin), encoding="utf-8", newline="\n"
    )
    (WIDGET / "ncaab_cu_fla.js").write_text(
        render_widget_script(thin), encoding="utf-8", newline="\n"
    )
    return len(states), len(thin)


def thin_basketball(states: list[GameState], config: SportConfig) -> list[GameState]:
    stripped = [replace(state, possession=None) for state in states]
    anchors = thin_states(stripped, config, eps=0.003)
    keys = {
        (
            state.period,
            state.seconds_remaining_period,
            state.home_score,
            state.away_score,
        )
        for state in anchors
    }
    out: list[GameState] = []
    seen: set[tuple[object, ...]] = set()
    for state in states:
        key = (
            state.period,
            state.seconds_remaining_period,
            state.home_score,
            state.away_score,
            state.possession,
        )
        late = (
            state.seconds_remaining_total <= 180
            or state.period > config.regulation_periods
        )
        keep = key[:4] in keys or (late and state.possession in {"home", "away"})
        if not keep or key in seen:
            continue
        seen.add(key)
        out.append(state)
    if states and states[-1].status == "final":
        if not out or out[-1].status != "final":
            out.append(states[-1])
    return out if out else list(states)
