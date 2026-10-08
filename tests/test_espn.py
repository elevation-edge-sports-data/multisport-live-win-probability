"""Offline ESPN NFL ingest. No test in this module opens a socket."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mswp import NCAAF_CONFIG, NFL_CONFIG, NHL_CONFIG, compute_wp

from live_wp.colors import club_colors, team_color
from live_wp.feeds.espn import (
    espn_scoreboard_event_to_state,
    espn_summary_to_states,
    require_nfl_payload,
    states_from_espn,
)
from live_wp.feeds.espn_basketball import events_from_espn_basketball
from live_wp.replay import (
    config_for_state,
    dump_replay,
    format_clock,
    format_line,
    load_replay,
    render_widget_script,
)

ROOT = Path(__file__).resolve().parents[1]
SNIPPET = ROOT / "tests" / "fixtures" / "espn_nfl_summary_snippet.json"
NCAAF_SNIPPET = ROOT / "tests" / "fixtures" / "espn_ncaaf_summary_snippet.json"
NHL_SNIPPET = ROOT / "tests" / "fixtures" / "espn_nhl_summary_snippet.json"
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


def test_college_football_maps_and_other_leagues_are_refused():
    college = json.loads(json.dumps(_summary()).replace("l:28", "l:23"))
    college["header"]["league"] = {
        "id": "23",
        "uid": "s:20~l:23",
        "name": "NCAA Football",
        "abbreviation": "NCAAF",
        "slug": "college-football",
    }
    states = espn_summary_to_states(college)
    assert states
    assert {state.sport for state in states} == {"ncaaf"}
    assert states[0].seconds_remaining_period == NCAAF_CONFIG.period_seconds
    assert states[1].seconds_remaining_total == 612 + 3 * NCAAF_CONFIG.period_seconds

    uid_only = _event(uid="s:20~l:23~e:9", team_uid_league="23")
    mapped = espn_scoreboard_event_to_state(uid_only)
    assert mapped.sport == "ncaaf"
    assert mapped.seconds_remaining_period == 6 * 60 + 40
    assert mapped.seconds_remaining_total == mapped.seconds_remaining_period + 2 * NCAAF_CONFIG.period_seconds

    with pytest.raises(ValueError, match="college football"):
        require_nfl_payload(college)

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

    nhl = _event(
        uid="s:70~l:90~e:9",
        team_uid_league="90",
        league={
            "id": "90",
            "slug": "nhl",
            "abbreviation": "NHL",
            "name": "National Hockey League",
        },
    )
    mapped_nhl = espn_scoreboard_event_to_state(nhl)
    assert mapped_nhl.sport == "nhl"
    assert mapped_nhl.seconds_remaining_period == 6 * 60 + 40
    assert mapped_nhl.seconds_remaining_total == (6 * 60 + 40) + NHL_CONFIG.period_seconds
    with pytest.raises(ValueError, match="not NFL"):
        require_nfl_payload(nhl)

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
        for name in ("down", "distance", "yardline", "possession"):
            value = getattr(state, name)
            if value is None:
                assert name not in frame
            else:
                assert frame[name] == value
        assert frame["home_logo"].endswith("logos/nfl/DEN.png")
        assert frame["away_logo"].endswith("logos/nfl/JAX.png")
    assert (ROOT / "widget" / frames[0]["home_logo"]).is_file()
    assert (ROOT / "widget" / frames[0]["away_logo"]).is_file()


def test_colo_at_gt_is_the_ncaaf_widget_replay():
    states = load_replay(ROOT / "examples" / "ncaaf_cu_gt.json")
    assert len(states) >= 100
    assert {state.sport for state in states} == {"ncaaf"}
    assert {state.home for state in states} == {"GT"}
    assert {state.away for state in states} == {"COLO"}
    assert {state.game_id for state in states} == {"401856776"}
    assert all(state.period <= 4 for state in states)
    priors = {state.prior_home for state in states}
    assert len(priors) == 1
    prior = priors.pop()
    # Home moneyline -238. Not a value copied from ESPN winprobability.
    assert prior == pytest.approx(238 / 338)
    assert prior > 0.5
    live = [state for state in states if state.status == "live"]
    assert len(live) >= 100
    assert sum(
        1
        for state in live
        if state.possession in {"home", "away"}
        and state.down in {1, 2, 3, 4}
        and state.distance is not None
        and state.yardline is not None
    ) >= 100
    assert any(state.home_score > state.away_score for state in live)
    leaders = []
    for state in states:
        if state.home_score > state.away_score:
            leaders.append("home")
        elif state.away_score > state.home_score:
            leaders.append("away")
    assert "home" in leaders and leaders[-1] == "away"
    assert any(leaders[index] != leaders[index - 1] for index in range(1, len(leaders)))
    final = states[-1]
    assert final.status == "final"
    assert final.home_score == 13
    assert final.away_score == 14
    assert compute_wp(final, final.prior_home, NCAAF_CONFIG) == 0.0
    assert team_color("GT", "ncaaf") == "#B3A369"
    assert team_color("COLO", "ncaaf") == "#CFB87C"
    assert team_color("CU", "ncaaf") == "#CFB87C"

    script_path = ROOT / "widget" / "ncaaf_cu_gt.js"
    script = script_path.read_text(encoding="utf-8")
    assert "window.NCAAF_REPLAY = " in script
    lowered = script.lower()
    assert "espn" not in lowered
    assert "https://" not in script and "http://" not in script
    assert "fetch(" not in script
    assert "logos/nfl/" not in script
    assert "logos/nhl/" not in script
    frames = json.loads(script[script.index("[") : script.rindex("]") + 1])
    assert len(frames) == len(states)
    for frame, state in zip(frames, states, strict=True):
        assert frame["home"] == "GT"
        assert frame["away"] == "COLO"
        assert frame["home_color"] == "#B3A369"
        assert frame["away_color"] == "#CFB87C"
        assert frame["wp"] == compute_wp(state, state.prior_home, NCAAF_CONFIG)
        assert frame["home_logo"] == "logos/ncaaf/GT.png"
        assert frame["away_logo"] == "logos/ncaaf/COLO.png"
        assert frame["period"] <= 4
    assert (ROOT / "widget" / frames[0]["home_logo"]).is_file()
    assert (ROOT / "widget" / frames[0]["away_logo"]).is_file()
    assert frames[-1]["status"] == "final"
    assert frames[-1]["home_score"] == 13
    assert frames[-1]["away_score"] == 14
    assert frames[-1]["wp"] == 0.0
    ncaaf_logos = ROOT / "widget" / "logos" / "ncaaf"
    assert sorted(path.name for path in ncaaf_logos.iterdir()) == ["COLO.png", "GT.png", "TTU.png"]


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
        if state.down is None:
            assert "down" not in frame
        else:
            assert frame["down"] == state.down
        if state.yardline is None:
            assert "yardline" not in frame
        else:
            assert frame["yardline"] == state.yardline
        if state.timeouts is None:
            assert "timeouts" not in frame
        else:
            assert frame["timeouts"] == {
                state.away: int(state.timeouts["away"]),
                state.home: int(state.timeouts["home"]),
            }
        assert "home_logo" not in frame
        assert "away_logo" not in frame

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

    ingested_ncaaf = tmp_path / "ncaaf.json"
    completed_ncaaf = subprocess.run(
        [
            sys.executable,
            "-m",
            "live_wp",
            "ingest-espn",
            str(NCAAF_SNIPPET),
            str(ingested_ncaaf),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed_ncaaf.stdout == ""
    ncaaf_states = load_replay(ingested_ncaaf)
    assert ncaaf_states == espn_summary_to_states(json.loads(NCAAF_SNIPPET.read_text(encoding="utf-8")))
    assert {state.sport for state in ncaaf_states} == {"ncaaf"}
    overtime = next(state for state in ncaaf_states if state.period == 5 and state.home_score == 21)
    assert overtime.seconds_remaining_period == 12 * 60
    assert all(
        state.seconds_remaining_period != 10 * 60
        for state in ncaaf_states
        if state.period > 4
    )
    assert compute_wp(ncaaf_states[-1], ncaaf_states[-1].prior_home, NCAAF_CONFIG) == 1.0


def _nhl_summary() -> dict:
    return json.loads(NHL_SNIPPET.read_text(encoding="utf-8"))


def test_nhl_summary_converts_elapsed_clocks_and_samples_situation():
    summary = _nhl_summary()
    scoring = espn_summary_to_states(summary, density="scoring")
    situation = espn_summary_to_states(summary, density="situation")
    everything = espn_summary_to_states(summary, density="all")
    assert scoring[0].status == "pre"
    assert scoring[0].sport == "nhl"
    assert scoring[0].seconds_remaining_period == 20 * 60
    assert scoring[0].seconds_remaining_total == 3 * 20 * 60
    assert scoring[0].prior_home == pytest.approx(0.6)
    assert scoring[0].prior_home != pytest.approx(0.11)
    goal = next(
        state
        for state in scoring
        if state.period == 1 and state.home_score == 0 and state.away_score == 1
    )
    assert goal.seconds_remaining_period == 20 * 60 - 70
    assert goal.strength is None
    assert goal.down is None
    assert goal.extra_attacker is None
    assert all(state.seconds_remaining_period != 900 for state in scoring)
    assert any(
        state.period == 2 and state.seconds_remaining_period == 900 for state in situation
    )
    assert all(state.seconds_remaining_period != 1100 for state in situation)
    assert any(
        state.period == 1 and state.seconds_remaining_period == 1100 for state in everything
    )
    tied = next(
        state
        for state in situation
        if state.period == 3
        and state.seconds_remaining_period == 0
        and state.home_score == state.away_score
        and state.status == "live"
    )
    tied_wp = compute_wp(tied, tied.prior_home, NHL_CONFIG)
    assert tied_wp not in (0.0, 1.0)
    overtime = [
        state for state in scoring if state.period == 4 and state.status == "live"
    ]
    assert overtime
    assert overtime[-1].seconds_remaining_period == 20 * 60 - 2 * 60
    assert overtime[-1].home_score == 2 and overtime[-1].away_score == 1
    final = scoring[-1]
    assert final.status == "final"
    assert final.period == 4
    assert final.home_score == 2 and final.away_score == 1
    assert final.seconds_remaining_period == overtime[-1].seconds_remaining_period
    assert compute_wp(final, final.prior_home, NHL_CONFIG) == 1.0
    assert all(state.strength is None and state.down is None for state in everything)


def test_min_at_col_is_the_nhl_widget_replay():
    path = ROOT / "examples" / "nhl_col_min_g5.json"
    states = load_replay(path)
    assert states
    assert {state.sport for state in states} == {"nhl"}
    assert {state.home for state in states} == {"COL"}
    assert {state.away for state in states} == {"MIN"}
    assert {state.game_id for state in states} == {"401871420"}
    assert states[0].status == "pre"
    assert states[0].home_score == 0 and states[0].away_score == 0
    priors = {state.prior_home for state in states}
    assert len(priors) == 1
    prior = priors.pop()
    assert prior == pytest.approx(230 / 330)
    assert prior != 0.5
    assert any(
        state.status == "live" and state.away_score == 3 and state.home_score in {0, 1}
        for state in states
    )
    overtime = [state for state in states if state.period > 3 and state.status == "live"]
    assert overtime
    final = states[-1]
    assert final.status == "final"
    assert final.home_score == 4
    assert final.away_score == 3
    assert final.period > 3
    assert compute_wp(final, final.prior_home, NHL_CONFIG) == 1.0
    assert any(format_clock(state).startswith("P1 ") for state in states)
    assert any(format_clock(state).startswith("OT ") for state in states)
    assert all(not format_clock(state).startswith("Q") for state in states)
    assert team_color("COL", "nhl") == "#6F263D"
    assert team_color("MIN", "nhl") == "#154734"
    assert team_color("MIN", "nfl") != team_color("MIN", "nhl")

    script_path = ROOT / "widget" / "nhl_col_min_g5.js"
    script = script_path.read_text(encoding="utf-8")
    assert "window.NHL_REPLAY = " in script
    lowered = script.lower()
    assert "espn" not in lowered
    assert "https://" not in script and "http://" not in script
    assert "fetch(" not in script
    frames = json.loads(script[script.index("[") : script.rindex("]") + 1])
    assert len(frames) == len(states)
    for frame, state in zip(frames, states, strict=True):
        assert frame["home"] == "COL"
        assert frame["away"] == "MIN"
        assert frame["home_color"] == "#6F263D"
        assert frame["away_color"] == "#154734"
        assert frame["wp"] == compute_wp(state, state.prior_home, NHL_CONFIG)
        assert frame["clock"] == format_clock(state)
        assert frame["home_logo"] == "logos/nhl/COL.png"
        assert frame["away_logo"] == "logos/nhl/MIN.png"
        assert "strength" not in frame
    assert (ROOT / "widget" / frames[0]["home_logo"]).is_file()
    assert (ROOT / "widget" / frames[0]["away_logo"]).is_file()
    assert frames[-1]["status"] == "final"
    assert frames[-1]["home_score"] == 4
    assert frames[-1]["away_score"] == 3
    assert frames[-1]["wp"] == 1.0


def test_ingest_still_accepts_nfl_ncaaf_and_nhl_snippets(tmp_path: Path) -> None:
    cases = (
        (SNIPPET, "nfl"),
        (NCAAF_SNIPPET, "ncaaf"),
        (NHL_SNIPPET, "nhl"),
    )
    for source, sport in cases:
        dest = tmp_path / f"{sport}.json"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "live_wp",
                "ingest-espn",
                str(source),
                str(dest),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert completed.stdout == ""
        states = load_replay(dest)
        payload = json.loads(source.read_text(encoding="utf-8"))
        assert states == espn_summary_to_states(payload)
        assert {state.sport for state in states} == {sport}


def test_ingest_accepts_nba_and_ncaab_summaries(tmp_path: Path) -> None:
    cases = (
        ("espn_nba_401547684_summary.json", "nba", "401547684", "LAL", "DEN", 111, 113),
        ("espn_ncaab_401638608_summary.json", "ncaab", "401638608", "FLA", "COLO", 100, 102),
    )
    for name, sport, game_id, home, away, home_score, away_score in cases:
        source = ROOT / "tests" / "fixtures" / name
        payload = json.loads(source.read_text(encoding="utf-8"))
        scoring_path = tmp_path / f"{sport}-scoring.json"
        situation_path = tmp_path / f"{sport}-situation.json"
        all_path = tmp_path / f"{sport}-all.json"
        for dest, flag in (
            (scoring_path, None),
            (situation_path, "situation"),
            (all_path, "all"),
        ):
            command = [
                sys.executable,
                "-m",
                "live_wp",
                "ingest-espn",
                str(source),
                str(dest),
            ]
            if flag is not None:
                command.extend(["--density", flag])
            completed = subprocess.run(
                command,
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            assert completed.stdout == ""
        scoring = load_replay(scoring_path)
        situation = load_replay(situation_path)
        everything = load_replay(all_path)
        assert scoring == events_from_espn_basketball(payload, density="scoring")
        assert situation == events_from_espn_basketball(payload, density="situation")
        assert everything == events_from_espn_basketball(payload, density="all")
        assert len(scoring) < len(situation) < len(everything)
        for states in (scoring, situation, everything):
            assert {state.sport for state in states} == {sport}
            assert {state.game_id for state in states} == {game_id}
            assert {state.home for state in states} == {home}
            assert {state.away for state in states} == {away}
            assert states[0].status == "pre"
            assert states[0].home_score == 0 and states[0].away_score == 0
            assert states[-1].status == "final"
            assert states[-1].home_score == home_score
            assert states[-1].away_score == away_score
            assert len({state.prior_home for state in states}) == 1
            assert compute_wp(
                states[-1], states[-1].prior_home, config_for_state(states[-1])
            ) == (1.0 if home_score > away_score else 0.0)
        if sport == "nba":
            assert scoring[0].prior_home == pytest.approx(160 / 260)
        else:
            assert scoring[0].prior_home == 0.5


def test_ingest_refuses_a_league_outside_the_five(tmp_path: Path) -> None:
    source = tmp_path / "mlb.json"
    source.write_text(
        json.dumps(
            {
                "header": {
                    "id": "1",
                    "league": {
                        "id": "10",
                        "slug": "mlb",
                        "abbreviation": "MLB",
                        "name": "Major League Baseball",
                    },
                    "competitions": [],
                },
                "plays": [{"id": "1"}],
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "live_wp",
            "ingest-espn",
            str(source),
            str(tmp_path / "out.json"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "not NFL" in completed.stderr
    assert not (tmp_path / "out.json").exists()


def test_demo_palette_is_sport_specific_and_colorado_gold():
    colo = club_colors("CU", "ncaaf")
    assert colo is not None
    assert colo["primary"] == "#CFB87C"
    assert colo["secondary"] == "#A2A4A3"
    assert colo["white"] == "#FFFFFF"
    assert colo["owns_black"] is True
    assert colo["black"] == "#000000"
    assert club_colors("COLO", "ncaab")["primary"] == "#CFB87C"
    assert club_colors("DEN", "nfl")["primary"] == "#FB4F14"
    assert club_colors("DEN", "nba")["primary"] == "#0E2240"
    assert club_colors("DEN", "ncaah")["primary"] == "#8B2332"
    assert club_colors("COL", "nhl")["primary"] == "#6F263D"
    assert team_color("COLO", "ncaaf") == "#CFB87C"
    assert team_color("JAX") == "#006778"
    assert team_color("MIN", "nfl") != team_color("MIN", "nhl")
    demo = json.loads((ROOT / "data" / "colors" / "demo.json").read_text(encoding="utf-8"))
    script = (ROOT / "widget" / "colors.js").read_text(encoding="utf-8")
    baked = json.loads(script[script.index("[") : script.rindex("]") + 1])
    assert baked == demo
    assert "espn" not in script.lower()
    assert "fetch(" not in script
    assert "https://" not in script and "http://" not in script
