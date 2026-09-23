"""Sample NFL replay and the live_wp replay command."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from mswp import NFL_CONFIG as nfl_config
from mswp import compute_wp

from live_wp.replay import elapsed_game_seconds, format_clock, format_line, load_replay

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "nfl_sample.json"
WIDGET_SCRIPT = ROOT / "widget" / "nfl_replay.js"

_OPTIONAL = {
    "possession",
    "down",
    "distance",
    "yardline",
    "timeouts",
    "strength",
    "extra_attacker",
}


def test_sample_is_a_chronological_nfl_path_without_football_details():
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert rows[0]["home_score"] == 0 and rows[0]["away_score"] == 0
    assert rows[0]["status"] == "pre"
    assert rows[0]["period"] == 1
    assert rows[0]["seconds_remaining_total"] == 3600
    assert rows[-1]["status"] == "final"
    assert {row["prior_home"] for row in rows} == {0.58}
    assert {row["sport"] for row in rows} == {"nfl"}
    for row in rows:
        assert _OPTIONAL.isdisjoint(row)

    states = load_replay(FIXTURE)
    assert all(state.down is None and state.distance is None for state in states)
    assert [state.as_of for state in states] == sorted(state.as_of for state in states)
    order = [(state.period, -state.seconds_remaining_total) for state in states]
    assert order == sorted(order)

    leaders = []
    for state in states:
        if state.home_score > state.away_score:
            leaders.append("home")
        elif state.away_score > state.home_score:
            leaders.append("away")
    assert leaders[0] == "home"
    assert "away" in leaders
    assert any(leaders[i] != leaders[i - 1] for i in range(1, len(leaders)))
    assert any(
        state.period == 4 and state.status == "live" and state.home_score > state.away_score
        for state in states
    )


def test_replay_cli_prints_compute_wp():
    source = (ROOT / "src" / "live_wp" / "__main__.py").read_text(encoding="utf-8")
    assert "compute_wp(state, state.prior_home, nfl_config)" in source

    completed = subprocess.run(
        [sys.executable, "-m", "live_wp", "replay", str(FIXTURE)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = completed.stdout.splitlines()
    states = load_replay(FIXTURE)
    expected = [
        format_line(state, compute_wp(state, state.prior_home, nfl_config))
        for state in states
    ]
    assert lines == expected


def test_widget_replay_matches_compute_wp():
    text = WIDGET_SCRIPT.read_text(encoding="utf-8")
    payload = text[text.index("[") : text.rindex("]") + 1]
    frames = json.loads(payload)
    states = load_replay(FIXTURE)
    assert len(frames) == len(states)
    for frame, state in zip(frames, states):
        wp = compute_wp(state, state.prior_home, nfl_config)
        assert frame["wp"] == wp
        assert frame["clock"] == format_clock(state)
        assert frame["home_score"] == state.home_score
        assert frame["away_score"] == state.away_score
        assert frame["prior_home"] == state.prior_home
        assert frame["elapsed_seconds"] == elapsed_game_seconds(state)
        assert "down" not in frame
    assert frames[0]["elapsed_seconds"] == 0
    assert frames[-1]["elapsed_seconds"] == 3600
    assert frames[-1]["wp"] == 1.0


def test_harbor_final_is_one():
    states = load_replay(FIXTURE)
    final = states[-1]
    assert final.status == "final"
    assert final.home == "Harbor"
    assert final.home_score > final.away_score
    assert compute_wp(final, final.prior_home, nfl_config) == 1.0
