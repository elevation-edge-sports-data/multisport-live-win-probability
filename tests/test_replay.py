"""Sample NFL replay and the live_wp replay command."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from mswp import NCAAF_CONFIG, NFL_CONFIG as nfl_config
from mswp import GameState, compute_wp

from live_wp.colors import team_color
from live_wp.replay import (
    elapsed_game_seconds,
    format_clock,
    format_line,
    load_replay,
    render_widget_script,
    team_logo,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "nfl_sample.json"
NCAAF_FIXTURE = ROOT / "examples" / "ncaaf_sample.json"
WIDGET_SCRIPT = ROOT / "widget" / "nfl_replay.js"
NCAAF_WIDGET = ROOT / "widget" / "ncaaf_replay.js"

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
    assert "compute_wp(state, state.prior_home, config_for_state(state))" in source

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
        assert "home_logo" not in frame
        assert "away_logo" not in frame
    assert frames[0]["elapsed_seconds"] == 0
    assert frames[-1]["elapsed_seconds"] == 3600
    assert frames[-1]["wp"] == 1.0


def test_ncaaf_sample_reaches_two_overtimes_and_matches_compute_wp():
    rows = json.loads(NCAAF_FIXTURE.read_text(encoding="utf-8"))
    assert 25 <= len(rows) <= 80
    assert rows[0]["status"] == "pre"
    assert rows[-1]["status"] == "final"
    assert {row["sport"] for row in rows} == {"ncaaf"}
    assert len({row["prior_home"] for row in rows}) == 1
    assert any(row["period"] == 5 and row["status"] == "live" for row in rows)
    assert any(row["period"] == 6 and row["status"] == "live" for row in rows)
    for row in rows:
        if row["status"] != "live":
            continue
        assert row["possession"] in {"home", "away"}
        assert row["down"] in {1, 2, 3, 4}
        assert isinstance(row["distance"], int)
        assert isinstance(row["yardline"], int)

    states = load_replay(NCAAF_FIXTURE)
    assert [state.as_of for state in states] == sorted(state.as_of for state in states)
    order = [(state.period, -state.seconds_remaining_total, state.as_of) for state in states]
    assert order == sorted(order)

    def leader(group):
        marks = []
        for state in group:
            if state.home_score > state.away_score:
                marks.append("home")
            elif state.away_score > state.home_score:
                marks.append("away")
        return marks

    regulation = leader(state for state in states if state.period <= 4)
    extra = leader(state for state in states if state.period > 4)
    assert any(regulation[i] != regulation[i - 1] for i in range(1, len(regulation)))
    assert any(extra[i] != extra[i - 1] for i in range(1, len(extra)))

    final = states[-1]
    assert final.home_score > final.away_score
    assert compute_wp(final, final.prior_home, NCAAF_CONFIG) == 1.0

    completed = subprocess.run(
        [sys.executable, "-m", "live_wp", "replay", str(NCAAF_FIXTURE)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    expected = [
        format_line(state, compute_wp(state, state.prior_home, NCAAF_CONFIG))
        for state in states
    ]
    assert completed.stdout.splitlines() == expected
    assert "OT " in completed.stdout
    assert "2OT " in completed.stdout

    text = NCAAF_WIDGET.read_text(encoding="utf-8")
    assert "window.NCAAF_REPLAY = " in text
    lowered = text.lower()
    assert "espn" not in lowered
    assert "fetch(" not in text
    assert "https://" not in text and "http://" not in text
    assert "logos/" not in text
    frames = json.loads(text[text.index("[") : text.rindex("]") + 1])
    assert len(frames) == len(states)
    for frame, state in zip(frames, states, strict=True):
        assert frame["wp"] == compute_wp(state, state.prior_home, NCAAF_CONFIG)
        assert frame["clock"] == format_clock(state)
        assert "home_logo" not in frame
        assert "away_logo" not in frame
        assert "home_color" not in frame
        assert "away_color" not in frame
    assert frames[-1]["wp"] == 1.0
    fresh = render_widget_script(states)
    fresh_frames = json.loads(fresh[fresh.index("[") : fresh.rindex("]") + 1])
    assert len(fresh_frames) == len(states)
    for frame in fresh_frames:
        assert frame["home_logo"] == "assets/logos/ncaaf/TEX.png"
        assert frame["away_logo"] == "assets/logos/ncaaf/OU.png"
        assert frame["home_color"] == team_color("TEX", "ncaaf")
        assert frame["away_color"] == team_color("OU", "ncaaf")
        assert "widget/logos" not in frame["home_logo"]


def _nfl_state(**overrides: object) -> GameState:
    fields: dict[str, object] = dict(
        sport="nfl",
        game_id="situation",
        home="DEN",
        away="NYG",
        home_score=10,
        away_score=7,
        period=2,
        seconds_remaining_period=8 * 60 + 14,
        seconds_remaining_total=2 * 900 + 8 * 60 + 14,
        status="live",
        source="test",
        as_of=datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc),
        prior_home=0.8,
    )
    fields.update(overrides)
    return GameState(**fields)  # type: ignore[arg-type]


def _script_frames(script: str) -> list[dict[str, object]]:
    payload = script[script.index("[") : script.rindex("]") + 1]
    frames = json.loads(payload)
    assert isinstance(frames, list)
    return frames


def test_render_widget_script_copies_situation_fields_only_when_set():
    rich = _nfl_state(
        possession="away",
        down=2,
        distance=7,
        yardline=35,
        timeouts={"home": 3, "away": 2},
        strength="5v4",
        extra_attacker=True,
    )
    bare = _nfl_state()
    partial = _nfl_state(down=2)
    flagged = _nfl_state(extra_attacker=False)
    named = _nfl_state(timeouts={"NYG": 2, "DEN": 3})
    script = render_widget_script([rich, bare, partial, flagged, named])
    frames = _script_frames(script)
    assert frames[0]["possession"] == "away"
    assert frames[0]["down"] == 2
    assert frames[0]["distance"] == 7
    assert frames[0]["yardline"] == 35
    assert frames[0]["timeouts"] == {"NYG": 2, "DEN": 3}
    assert list(frames[0]["timeouts"]) == ["NYG", "DEN"]
    assert frames[0]["strength"] == "5v4"
    assert frames[0]["extra_attacker"] is True
    assert frames[0]["wp"] == compute_wp(rich, rich.prior_home, nfl_config)
    assert frames[1]["wp"] == compute_wp(bare, bare.prior_home, nfl_config)
    for name in _OPTIONAL:
        assert name not in frames[1]
    assert frames[2]["down"] == 2
    for name in _OPTIONAL - {"down"}:
        assert name not in frames[2]
    assert frames[3]["extra_attacker"] is False
    for name in _OPTIONAL - {"extra_attacker"}:
        assert name not in frames[3]
    assert frames[4]["timeouts"] == {"NYG": 2, "DEN": 3}
    for name in _OPTIONAL - {"timeouts"}:
        assert name not in frames[4]


def test_team_logo_reads_assets_not_the_widget_tree():
    assert team_logo("DEN", sport="nfl") == "assets/logos/nfl/DEN.png"
    assert team_logo("jax", sport="nfl") == "assets/logos/nfl/JAX.png"
    assert team_logo("COLO", sport="ncaaf") == "assets/logos/ncaaf/COLO.png"
    assert team_logo("DEN", sport="nba") == "assets/logos/nba/DEN.png"
    assert team_logo("DEN", sport="ncaah") == "assets/logos/ncaah/DEN.png"
    assert team_logo("DEN", sport="nfl") != team_logo("DEN", sport="nba")
    assert team_logo("Harbor", sport="nfl") is None
    assert team_logo("Red Oak", sport="nfl") is None
    assert (ROOT / "assets" / "logos" / "nfl" / "DEN.png").is_file()
    assert "widget/logos" not in (ROOT / "src" / "live_wp" / "replay.py").read_text(encoding="utf-8")


def test_harbor_final_is_one():
    states = load_replay(FIXTURE)
    final = states[-1]
    assert final.status == "final"
    assert final.home == "Harbor"
    assert final.home_score > final.away_score
    assert compute_wp(final, final.prior_home, nfl_config) == 1.0
