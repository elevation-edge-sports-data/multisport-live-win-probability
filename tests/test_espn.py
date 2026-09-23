"""Offline ESPN NFL ingest. No test in this module opens a socket."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mswp import NFL_CONFIG, compute_wp

from live_wp.feeds.espn import (
    espn_scoreboard_event_to_state,
    espn_summary_to_states,
    states_from_espn,
)
from live_wp.replay import (
    dump_replay,
    format_line,
    load_replay,
    render_widget_script,
)

ROOT = Path(__file__).resolve().parents[1]
SNIPPET = ROOT / "tests" / "fixtures" / "espn_nfl_summary_snippet.json"
SAMPLE = ROOT / "examples" / "nfl_espn_sample.json"
HARBOR = ROOT / "examples" / "nfl_sample.json"
WIDGET_SCRIPT = ROOT / "widget" / "nfl_replay.js"


def _summary() -> dict:
    return json.loads(SNIPPET.read_text(encoding="utf-8"))


def _event(
    *,
    uid: str = "s:20~l:28~e:55",
    state: str = "in",
    period: int = 2,
    clock: str = "6:40",
    home_score: str = "7",
    away_score: str = "3",
    situation: dict | None = None,
    odds: list | None = None,
    league: dict | None = None,
    team_uid_league: str = "28",
) -> dict:
    home_uid = f"s:20~l:{team_uid_league}~t:101"
    away_uid = f"s:20~l:{team_uid_league}~t:202"
    competition: dict = {
        "id": "55",
        "uid": uid,
        "date": "2026-09-20T17:00:00Z",
        "competitors": [
            {
                "homeAway": "home",
                "score": home_score,
                "team": {
                    "id": "101",
                    "uid": home_uid,
                    "abbreviation": "HBR",
                    "displayName": "Harbor",
                },
            },
            {
                "homeAway": "away",
                "score": away_score,
                "team": {
                    "id": "202",
                    "uid": away_uid,
                    "abbreviation": "ROK",
                    "displayName": "Red Oak",
                },
            },
        ],
        "status": {
            "displayClock": clock,
            "period": period,
            "type": {"state": state, "name": "STATUS"},
        },
    }
    if situation is not None:
        competition["situation"] = situation
    if odds is not None:
        competition["odds"] = odds
    event: dict = {
        "id": "55",
        "uid": uid,
        "date": "2026-09-20T17:00:00Z",
        "competitions": [competition],
    }
    if league is not None:
        event["league"] = league
    return event


def test_summary_maps_scores_clocks_and_a_decided_final():
    states = espn_summary_to_states(_summary())
    assert [(s.status, s.period, s.seconds_remaining_period, s.home_score, s.away_score) for s in states] == [
        ("pre", 1, 900, 0, 0),
        ("live", 1, 612, 7, 0),
        ("live", 2, 900, 7, 0),
        ("live", 2, 400, 7, 7),
        ("live", 2, 185, 7, 10),
        ("live", 2, 120, 7, 10),
        ("live", 3, 900, 7, 10),
        ("live", 4, 900, 7, 10),
        ("live", 4, 260, 14, 10),
        ("live", 4, 120, 14, 10),
        ("final", 4, 0, 14, 10),
    ]
    # 10:12 in Q1 still has three quarters after it. Q4 4:20 does not.
    assert states[1].seconds_remaining_total == 612 + 3 * 900
    assert states[8].seconds_remaining_total == 260
    assert states[-1].seconds_remaining_total == 0
    # The two non-scoring plays exist only so the two-minute warning is visible.
    assert 100 not in [s.seconds_remaining_period for s in states]
    assert 72 not in [s.seconds_remaining_period for s in states]
    leaders = []
    for state in states:
        if state.home_score > state.away_score:
            leaders.append("home")
        elif state.away_score > state.home_score:
            leaders.append("away")
    assert leaders[0] == "home"
    assert "away" in leaders
    assert any(leaders[i] != leaders[i - 1] for i in range(1, len(leaders)))
    final = states[-1]
    assert final.status == "final"
    assert compute_wp(final, final.prior_home, NFL_CONFIG) == 1.0
    assert all(state.sport == "nfl" and state.source == "espn" for state in states)
    assert {state.game_id for state in states} == {"9001001"}
    times = [state.as_of for state in states]
    assert times == sorted(times)
    assert all(times[i] < times[i + 1] for i in range(len(times) - 1))


def test_optional_fields_map_and_a_missing_situation_is_omitted():
    states = espn_summary_to_states(_summary())
    scored = states[1]
    assert scored.down == 1
    assert scored.distance == 10
    assert scored.yardline == 25
    assert scored.possession == "home"
    assert dict(scored.timeouts) == {"home": 3, "away": 3}

    # yardsToEndzone 12 on the opponent's side is 88 yards from Harbor's goal.
    fourth = next(
        state
        for state in states
        if state.period == 4 and state.seconds_remaining_period == 260
    )
    assert fourth.down == 1
    assert fourth.distance == 10
    assert fourth.yardline == 88
    assert fourth.possession == "home"
    assert fourth.timeouts is None

    tied = next(state for state in states if state.home_score == 7 and state.away_score == 7)
    assert tied.down is None
    assert tied.distance is None
    assert tied.yardline is None
    assert tied.possession is None
    assert tied.timeouts is None


def test_yardline_text_is_translated_on_a_scoreboard_event():
    on_opponent = espn_scoreboard_event_to_state(
        _event(
            situation={
                "down": 2,
                "distance": 7,
                "yardLine": 22,
                "possessionText": "HBR 22",
                "possession": "202",
                "homeTimeouts": 1,
                "awayTimeouts": 2,
            }
        )
    )
    assert on_opponent.possession == "away"
    assert on_opponent.yardline == 78
    assert on_opponent.down == 2
    assert on_opponent.distance == 7
    assert dict(on_opponent.timeouts) == {"home": 1, "away": 2}
    assert on_opponent.seconds_remaining_period == 400
    assert on_opponent.seconds_remaining_total == 400 + 2 * 900

    on_own = espn_scoreboard_event_to_state(
        _event(
            situation={
                "down": 1,
                "distance": 10,
                "yardLine": 35,
                "possessionText": "ROK 35",
                "possession": "202",
            }
        )
    )
    assert on_own.possession == "away"
    assert on_own.yardline == 35
    assert on_own.timeouts is None


def test_pregame_clock_and_a_missing_situation_on_a_scoreboard_event():
    pre = espn_scoreboard_event_to_state(
        _event(state="pre", period=0, clock="0:00", home_score="", away_score="")
    )
    assert pre.status == "pre"
    assert pre.period == 1
    assert pre.seconds_remaining_period == 900
    assert pre.seconds_remaining_total == 3600
    assert pre.home_score == 0 and pre.away_score == 0
    assert pre.down is None and pre.possession is None

    bare = espn_scoreboard_event_to_state(
        _event(state="in", period=4, clock="1:00", home_score="14", away_score="10")
    )
    assert bare.seconds_remaining_period == 60
    assert bare.seconds_remaining_total == 60
    assert bare.down is None
    assert bare.distance is None
    assert bare.yardline is None
    assert bare.possession is None
    assert bare.timeouts is None

    clamped = espn_scoreboard_event_to_state(_event(state="in", period=1, clock="20:00"))
    assert clamped.seconds_remaining_period == 900
    assert clamped.seconds_remaining_total == 3600


def test_moneyline_becomes_one_prior_and_espn_win_probability_is_ignored():
    states = espn_summary_to_states(_summary(), prior_home=0.51)
    assert states[0].prior_home == pytest.approx(0.6)
    assert all(state.prior_home == states[0].prior_home for state in states)
    assert 0.0 < states[0].prior_home < 1.0
    assert states[0].prior_home != 0.91
    kickoff = compute_wp(states[0], states[0].prior_home, NFL_CONFIG)
    assert kickoff == pytest.approx(0.6, abs=1e-9)
    assert kickoff != 0.91

    plus = espn_scoreboard_event_to_state(
        _event(odds=[{"homeTeamOdds": {"moneyLine": 130}}])
    )
    assert plus.prior_home == pytest.approx(100 / 230)
    assert 0.0 < plus.prior_home < 0.5

    nested = espn_scoreboard_event_to_state(
        _event(
            state="post",
            period=4,
            clock="0:00",
            home_score="21",
            away_score="17",
            odds=[{"moneyline": {"home": {"close": {"odds": "-150"}}}}],
        )
    )
    assert nested.prior_home == pytest.approx(0.6)
    assert compute_wp(nested, nested.prior_home, NFL_CONFIG) == 1.0

    away_final = espn_scoreboard_event_to_state(
        _event(state="post", period=4, clock="0:00", home_score="17", away_score="21")
    )
    assert compute_wp(away_final, away_final.prior_home, NFL_CONFIG) == 0.0

    no_price = _event()
    assert espn_scoreboard_event_to_state(no_price, prior_home=0.62).prior_home == 0.62
    assert espn_scoreboard_event_to_state(no_price).prior_home == 0.5


def test_college_football_and_other_leagues_are_refused():
    college = _summary()
    college["header"]["league"] = {
        "id": "23",
        "uid": "s:20~l:23",
        "name": "NCAA Football",
        "abbreviation": "NCAAF",
        "slug": "college-football",
    }
    college["header"]["uid"] = "s:20~l:23~e:9001001"
    with pytest.raises(ValueError, match="college football"):
        espn_summary_to_states(college)

    uid_only = _event(uid="s:20~l:23~e:9", team_uid_league="23")
    with pytest.raises(ValueError, match="cfb"):
        espn_scoreboard_event_to_state(uid_only)

    nba = _event(
        uid="s:40~l:46~e:9",
        team_uid_league="46",
        league={
            "id": "46",
            "slug": "nba",
            "abbreviation": "NBA",
            "name": "National Basketball Association",
        },
    )
    with pytest.raises(ValueError, match="not NFL"):
        espn_scoreboard_event_to_state(nba)

    unlabeled = _event(uid="e:55", team_uid_league="0")
    unlabeled.pop("uid")
    unlabeled["competitions"][0].pop("uid")
    for side in unlabeled["competitions"][0]["competitors"]:
        side["team"].pop("uid")
    with pytest.raises(ValueError, match="not NFL"):
        states_from_espn(unlabeled)

    with pytest.raises(ValueError, match="scoreboard list"):
        states_from_espn({"events": [_event()], "leagues": [{"slug": "nfl"}]})


def test_overtime_uses_the_ten_minute_clock():
    summary = _summary()
    summary["header"]["competitions"][0]["status"]["period"] = 5
    summary["header"]["competitions"][0]["competitors"][0]["score"] = "17"
    summary["header"]["competitions"][0]["competitors"][1]["score"] = "14"
    summary["drives"] = {
        "previous": [
            {
                "plays": [
                    {
                        "id": "ot1",
                        "sequenceNumber": "1",
                        "awayScore": 14,
                        "homeScore": 17,
                        "period": {"number": 5},
                        "clock": {"displayValue": "8:00"},
                        "scoringPlay": True,
                        "wallclock": "2026-09-20T19:10:00Z",
                        "start": {
                            "down": 1,
                            "distance": 10,
                            "yardsToEndzone": 25,
                            "team": {"id": "101"},
                        },
                    }
                ]
            }
        ]
    }
    summary["scoringPlays"] = []
    states = espn_summary_to_states(summary)
    overtime_start = next(state for state in states if state.period == 5 and state.seconds_remaining_period == 600)
    assert overtime_start.seconds_remaining_total == 600
    score = next(state for state in states if state.period == 5 and state.home_score == 17)
    assert score.seconds_remaining_period == 480
    assert score.seconds_remaining_total == 480
    assert score.yardline == 75
    assert states[-1].status == "final"
    assert states[-1].period == 5
    assert compute_wp(states[-1], states[-1].prior_home, NFL_CONFIG) == 1.0


def test_a_partial_situation_matches_clock_and_score_wp():
    state = espn_summary_to_states(_summary())[1]
    assert None not in (state.down, state.distance, state.yardline, state.possession)
    bare = replace(
        state,
        down=None,
        distance=None,
        yardline=None,
        possession=None,
        timeouts=None,
    )
    bare_wp = compute_wp(bare, bare.prior_home, NFL_CONFIG)
    for name in ("down", "distance", "yardline", "possession"):
        partial = replace(state, **{name: None})
        assert compute_wp(partial, partial.prior_home, NFL_CONFIG) == bare_wp
    assert compute_wp(state, state.prior_home, NFL_CONFIG) != bare_wp


def test_top_level_plays_match_plays_nested_on_drives():
    driven = _summary()
    lifted = _summary()
    plays = []
    for drive in lifted["drives"]["previous"]:
        plays.extend(drive["plays"])
    lifted["plays"] = plays
    del lifted["drives"]
    assert espn_summary_to_states(lifted) == espn_summary_to_states(driven)


def test_density_selects_how_many_plays_become_snapshots():
    summary = _summary()
    play = summary["drives"]["previous"][1]["plays"][2]
    assert play["clock"]["displayValue"] == "1:40"
    play["start"] = {
        "down": 2,
        "distance": 8,
        "yardLine": 40,
        "yardsToEndzone": 60,
        "possessionText": "ROK 40",
        "team": {"id": "202"},
    }
    scoring = espn_summary_to_states(summary, density="scoring")
    situation = espn_summary_to_states(summary, density="situation")
    everything = espn_summary_to_states(summary, density="all")
    assert 100 not in [state.seconds_remaining_period for state in scoring]
    marked = [
        state
        for state in situation
        if state.seconds_remaining_period == 100 and state.down == 2
    ]
    assert marked and marked[0].possession == "away" and marked[0].yardline == 40
    assert any(state.seconds_remaining_period == 100 for state in everything)
    assert everything[0].status == "pre" and everything[-1].status == "final"
    assert len(everything) >= 8
    with pytest.raises(ValueError, match="density"):
        espn_summary_to_states(summary, density="plays")


def test_jax_at_den_is_the_widget_replay():
    states = load_replay(ROOT / "examples" / "nfl_jax_den.json")
    assert states
    assert {state.sport for state in states} == {"nfl"}
    assert {state.home for state in states} == {"DEN"}
    assert {state.away for state in states} == {"JAX"}
    final = states[-1]
    assert final.status == "final"
    assert final.home_score == 20
    assert final.away_score == 13
    assert compute_wp(final, final.prior_home, NFL_CONFIG) == 1.0
    assert any(
        state.status == "live" and state.away_score > state.home_score for state in states
    )
    assert final.home_score > final.away_score
    assert any(
        state.period == 4 and state.home_score == 13 and state.away_score == 13
        for state in states
    )
    priors = {state.prior_home for state in states}
    assert len(priors) == 1
    prior = priors.pop()
    assert 0.0 < prior < 1.0
    # Home moneyline -142. Not the summary's own winprobability value.
    assert prior == pytest.approx(142 / 242)
    assert prior != pytest.approx(0.3593)
    assert len(states) >= 40
    twitch = False
    for earlier, later in zip(states, states[1:]):
        if earlier.status != "live" or later.status != "live":
            continue
        if (earlier.home_score, earlier.away_score) != (later.home_score, later.away_score):
            continue
        left = (earlier.down, earlier.distance, earlier.yardline, earlier.possession)
        right = (later.down, later.distance, later.yardline, later.possession)
        if None in left or None in right or left == right:
            continue
        if compute_wp(earlier, earlier.prior_home, NFL_CONFIG) != compute_wp(
            later, later.prior_home, NFL_CONFIG
        ):
            twitch = True
            break
    assert twitch

    script_path = ROOT / "widget" / "nfl_jax_den.js"
    script = script_path.read_text(encoding="utf-8")
    assert "window.NFL_REPLAY = " in script
    assert "espn" not in script.lower()
    assert "https://" not in script and "http://" not in script
    assert "fetch(" not in script
    frames = json.loads(script[script.index("[") : script.rindex("]") + 1])
    assert len(frames) == len(states)
    for frame, state in zip(frames, states, strict=True):
        assert frame["home"] == "DEN"
        assert frame["away"] == "JAX"
        assert frame["home_color"] == "#FB4F14"
        assert frame["away_color"] == "#006778"
        assert frame["wp"] == compute_wp(state, state.prior_home, NFL_CONFIG)
        assert "down" not in frame


def test_checked_in_sample_matches_the_snippet_and_loads():
    states = espn_summary_to_states(_summary())
    assert SAMPLE.read_text(encoding="utf-8") == dump_replay(states)
    assert load_replay(SAMPLE) == states
    assert states_from_espn(_summary()) == states


def test_ingest_and_replay_and_render_cli(tmp_path: Path):
    ingested = tmp_path / "nfl.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "live_wp",
            "ingest-espn",
            str(SNIPPET),
            str(ingested),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout == ""
    assert load_replay(ingested) == espn_summary_to_states(_summary())

    replayed = subprocess.run(
        [sys.executable, "-m", "live_wp", "replay", str(SAMPLE)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    states = load_replay(SAMPLE)
    expected = [
        format_line(state, compute_wp(state, state.prior_home, NFL_CONFIG))
        for state in states
    ]
    assert replayed.stdout.splitlines() == expected
    assert replayed.stdout.splitlines()[-1].endswith("| 1.000")

    rendered = tmp_path / "replay.js"
    subprocess.run(
        [sys.executable, "-m", "live_wp", "render-widget", str(SAMPLE), str(rendered)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    script = rendered.read_text(encoding="utf-8")
    assert script == render_widget_script(states)
    assert "window.NFL_REPLAY = " in script
    assert "espn" not in script.lower()
    harbor_text = WIDGET_SCRIPT.read_text(encoding="utf-8")
    harbor_frames = json.loads(harbor_text[harbor_text.index("[") : harbor_text.rindex("]") + 1])
    frames = json.loads(script[script.index("[") : script.rindex("]") + 1])
    assert list(frames[0]) == list(harbor_frames[0])
    for frame, state in zip(frames, states):
        assert frame["wp"] == compute_wp(state, state.prior_home, NFL_CONFIG)
        assert "down" not in frame
        assert "yardline" not in frame

    harbor_out = tmp_path / "harbor.js"
    subprocess.run(
        [sys.executable, "-m", "live_wp", "render-widget", str(HARBOR), str(harbor_out)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    harbor_rendered = json.loads(
        harbor_out.read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";")
    )
    harbor_states = load_replay(HARBOR)
    assert len(harbor_rendered) == len(harbor_states)
    assert harbor_rendered[-1]["wp"] == 1.0

    refused = tmp_path / "cfb.json"
    refused.write_text(
        json.dumps(
            {
                "header": {
                    "id": "1",
                    "uid": "s:20~l:23~e:1",
                    "league": {"slug": "college-football", "abbreviation": "NCAAF", "id": "23"},
                    "competitions": [
                        {
                            "id": "1",
                            "date": "2026-09-20T17:00:00Z",
                            "competitors": [],
                            "status": {
                                "period": 4,
                                "displayClock": "0:00",
                                "type": {"state": "post"},
                            },
                        }
                    ],
                },
                "drives": {"previous": []},
            }
        ),
        encoding="utf-8",
    )
    failed = subprocess.run(
        [sys.executable, "-m", "live_wp", "ingest-espn", str(refused), str(tmp_path / "out.json")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert failed.returncode == 1
    assert "college football" in failed.stderr.lower()
    assert not (tmp_path / "out.json").exists()
