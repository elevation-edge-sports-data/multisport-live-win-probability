"""Elo fallback when a home American moneyline is absent.

No test in this module opens a socket. The snapshot on disk is the
copied export. These tests do not import the playoff-lab package.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from live_win_prob.feeds.espn import espn_scoreboard_event_to_state, espn_summary_to_states
from live_win_prob.feeds.espn_basketball import (
    events_from_espn_basketball,
    scoreboard_event_to_state,
)
from live_win_prob.feeds.espn_hockey import events_from_espn_hockey
from live_win_prob.priors import elo_prior_home, load_snapshot
from live_win_prob.replay import game_state_from_row, render_widget_script, state_to_row
from live_win_prob.slate import render_slate_script

ROOT = Path(__file__).resolve().parents[1]
SNIPPET = ROOT / "tests" / "fixtures" / "espn_nfl_summary_snippet.json"


def _expected(sport: str, home: str, away: str) -> float:
    block = load_snapshot()["sports"][sport]
    home_elo = float(block["teams"][home]) + float(block["home_advantage"])
    away_elo = float(block["teams"][away])
    return 1.0 / (1.0 + 10.0 ** ((away_elo - home_elo) / 400.0))


def _board(
    *,
    sport: str,
    league_id: str,
    series: str,
    home: str,
    away: str,
    moneyline: int | None = None,
) -> dict:
    uid = f"s:{series}~l:{league_id}~e:55"
    competition: dict = {
        "id": "55",
        "uid": uid,
        "date": "2026-10-19T17:00:00Z",
        "competitors": [
            {
                "homeAway": "home",
                "score": "0",
                "team": {
                    "id": "1",
                    "uid": f"s:{series}~l:{league_id}~t:1",
                    "abbreviation": home,
                },
            },
            {
                "homeAway": "away",
                "score": "0",
                "team": {
                    "id": "2",
                    "uid": f"s:{series}~l:{league_id}~t:2",
                    "abbreviation": away,
                },
            },
        ],
        "status": {
            "displayClock": "15:00",
            "period": 1,
            "type": {"state": "pre", "name": "STATUS_SCHEDULED"},
        },
    }
    if moneyline is not None:
        competition["odds"] = [{"homeTeamOdds": {"moneyLine": moneyline}}]
    return {
        "id": "55",
        "uid": uid,
        "date": "2026-10-19T17:00:00Z",
        "competitions": [competition],
    }


def _nba_summary(*, moneyline: int | None = None) -> dict:
    competition: dict = {
        "id": "88",
        "date": "2026-04-05T00:00:00Z",
        "competitors": [
            {
                "homeAway": "home",
                "score": "0",
                "team": {"id": "13", "abbreviation": "LAL"},
            },
            {
                "homeAway": "away",
                "score": "0",
                "team": {"id": "7", "abbreviation": "DEN"},
            },
        ],
        "status": {
            "displayClock": "12:00",
            "period": 1,
            "type": {"state": "pre", "name": "STATUS_SCHEDULED"},
        },
    }
    if moneyline is not None:
        competition["odds"] = [{"homeTeamOdds": {"moneyLine": moneyline}}]
    header = {
        "id": "88",
        "uid": "s:40~l:46~e:88",
        "league": {"id": "46", "slug": "nba", "abbreviation": "NBA"},
        "competitions": [competition],
    }
    return {
        "header": header,
        "plays": [
            {
                "homeScore": 0,
                "awayScore": 0,
                "period": {"number": 1},
                "clock": {"displayValue": "12:00"},
                "text": "Jump ball",
            }
        ],
    }


def _nhl_summary(*, moneyline: int | None = None) -> dict:
    competition: dict = {
        "competitors": [
            {
                "homeAway": "home",
                "team": {"id": "1", "abbreviation": "COL"},
            },
            {
                "homeAway": "away",
                "team": {"id": "2", "abbreviation": "EDM"},
            },
        ]
    }
    if moneyline is not None:
        competition["odds"] = [{"homeTeamOdds": {"moneyLine": moneyline}}]
    return {
        "header": {"id": "77", "competitions": [competition]},
        "plays": [
            {
                "period": {"number": 1},
                "clock": {"displayValue": "0:00"},
                "homeScore": 0,
                "awayScore": 0,
                "type": {"text": "Period Start"},
            }
        ],
    }


def _nfl_summary(*, home: str, away: str, drop_odds: bool) -> dict:
    payload = json.loads(SNIPPET.read_text(encoding="utf-8"))
    competition = payload["header"]["competitions"][0]
    if drop_odds:
        competition.pop("odds", None)
    for side in competition["competitors"]:
        if side["homeAway"] == "home":
            side["team"]["abbreviation"] = home
        else:
            side["team"]["abbreviation"] = away
    return payload


def test_snapshot_home_advantage_is_applied_with_no_extra_boost() -> None:
    snapshot = load_snapshot()
    assert snapshot["sports"]["nfl"]["home_advantage"] == 0.0
    assert snapshot["sports"]["nhl"]["home_advantage"] == 0.0
    assert snapshot["sports"]["nba"]["home_advantage"] == 0.0
    assert load_snapshot() is snapshot
    for sport, home, away in (
        ("nfl", "DEN", "NYG"),
        ("nhl", "COL", "EDM"),
        ("nba", "LAL", "DEN"),
    ):
        found = elo_prior_home(sport, home, away)
        assert found == pytest.approx(_expected(sport, home, away))
        assert found != pytest.approx(0.5)
    assert elo_prior_home("NFL", "DEN", "NYG") == pytest.approx(_expected("nfl", "DEN", "NYG"))


def test_home_advantage_comes_from_the_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "live_win_prob.priors.load_snapshot",
        lambda: {
            "sports": {
                "nfl": {
                    "home_advantage": 100.0,
                    "teams": {"DEN": 1500.0, "NYG": 1500.0},
                }
            }
        },
    )
    boosted = 1.0 / (1.0 + 10.0 ** ((1500.0 - 1600.0) / 400.0))
    assert elo_prior_home("nfl", "DEN", "NYG") == pytest.approx(boosted)
    assert elo_prior_home("nfl", "DEN", "NYG") != pytest.approx(0.5)
    monkeypatch.setattr(
        "live_win_prob.priors.load_snapshot",
        lambda: {"sports": {}},
    )
    assert elo_prior_home("nfl", "DEN", "NYG") is None


def test_priors_module_does_not_import_playoff_lab() -> None:
    source = (ROOT / "src" / "live_win_prob" / "priors.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            assert "playoff" not in stripped


def test_missing_moneyline_uses_elo_for_nfl_nhl_and_nba() -> None:
    nfl = espn_scoreboard_event_to_state(
        _board(sport="nfl", league_id="28", series="20", home="DEN", away="NYG")
    )
    assert nfl.prior_source == "elo"
    assert nfl.prior_home == pytest.approx(_expected("nfl", "DEN", "NYG"))
    assert nfl.prior_home == pytest.approx(
        elo_prior_home("nfl", "DEN", "NYG")
    )

    summarized = espn_summary_to_states(
        _nfl_summary(home="DEN", away="NYG", drop_odds=True)
    )
    assert summarized
    assert {state.prior_source for state in summarized} == {"elo"}
    assert summarized[0].prior_home == pytest.approx(nfl.prior_home)

    nhl_board = espn_scoreboard_event_to_state(
        _board(sport="nhl", league_id="90", series="70", home="COL", away="EDM")
    )
    assert nhl_board.sport == "nhl"
    assert nhl_board.prior_source == "elo"
    assert nhl_board.prior_home == pytest.approx(_expected("nhl", "COL", "EDM"))

    nhl_plays = events_from_espn_hockey(_nhl_summary())
    assert nhl_plays
    assert {state.prior_source for state in nhl_plays} == {"elo"}
    assert nhl_plays[0].prior_home == pytest.approx(nhl_board.prior_home)

    nba_board = scoreboard_event_to_state(
        {
            "id": "88",
            "uid": "s:40~l:46~e:88",
            "date": "2026-04-05T00:00:00Z",
            "league": {"id": "46", "slug": "nba", "abbreviation": "NBA"},
            "competitions": _nba_summary()["header"]["competitions"],
        }
    )
    assert nba_board.sport == "nba"
    assert nba_board.prior_source == "elo"
    assert nba_board.prior_home == pytest.approx(_expected("nba", "LAL", "DEN"))

    nba_plays = events_from_espn_basketball(_nba_summary())
    assert nba_plays
    assert {state.prior_source for state in nba_plays} == {"elo"}
    assert nba_plays[0].prior_home == pytest.approx(nba_board.prior_home)

    # A caller prior does not outrank Elo when both clubs are in the snapshot.
    passed_over = espn_scoreboard_event_to_state(
        _board(sport="nfl", league_id="28", series="20", home="DEN", away="NYG"),
        prior_home=0.62,
    )
    assert passed_over.prior_source == "elo"
    assert passed_over.prior_home == pytest.approx(nfl.prior_home)
    assert passed_over.prior_home != pytest.approx(0.62)


def test_moneyline_wins_and_elo_is_ignored() -> None:
    cases = (
        (
            espn_scoreboard_event_to_state(
                _board(
                    sport="nfl",
                    league_id="28",
                    series="20",
                    home="DEN",
                    away="NYG",
                    moneyline=-150,
                )
            ),
            _expected("nfl", "DEN", "NYG"),
        ),
        (
            espn_scoreboard_event_to_state(
                _board(
                    sport="nhl",
                    league_id="90",
                    series="70",
                    home="COL",
                    away="EDM",
                    moneyline=-150,
                )
            ),
            _expected("nhl", "COL", "EDM"),
        ),
        (
            scoreboard_event_to_state(
                {
                    "id": "88",
                    "uid": "s:40~l:46~e:88",
                    "date": "2026-04-05T00:00:00Z",
                    "league": {"id": "46", "slug": "nba", "abbreviation": "NBA"},
                    "competitions": _nba_summary(moneyline=-150)["header"]["competitions"],
                }
            ),
            _expected("nba", "LAL", "DEN"),
        ),
    )
    for state, elo in cases:
        assert state.prior_source == "moneyline"
        assert state.prior_home == pytest.approx(0.6)
        assert state.prior_home != pytest.approx(elo)

    kept = espn_summary_to_states(
        _nfl_summary(home="DEN", away="NYG", drop_odds=False)
    )
    assert {state.prior_source for state in kept} == {"moneyline"}
    assert kept[0].prior_home == pytest.approx(0.6)

    hockey = events_from_espn_hockey(_nhl_summary(moneyline=-150))
    assert hockey[0].prior_source == "moneyline"
    assert hockey[0].prior_home == pytest.approx(0.6)
    basketball = events_from_espn_basketball(_nba_summary(moneyline=-150))
    assert basketball[0].prior_source == "moneyline"
    assert basketball[0].prior_home == pytest.approx(0.6)


def test_unknown_team_or_college_sport_stays_at_one_half() -> None:
    unknown = espn_scoreboard_event_to_state(
        _board(sport="nfl", league_id="28", series="20", home="HBR", away="ROK")
    )
    assert unknown.prior_home == 0.5
    assert unknown.prior_source == "default"
    assert elo_prior_home("nfl", "HBR", "ROK") is None

    college = espn_scoreboard_event_to_state(
        _board(sport="ncaaf", league_id="23", series="20", home="DEN", away="NYG")
    )
    assert college.sport == "ncaaf"
    assert college.prior_home == 0.5
    assert college.prior_source == "default"
    assert elo_prior_home("ncaaf", "DEN", "NYG") is None
    assert elo_prior_home("ncaah", "DEN", "MICH") is None
    assert elo_prior_home("ncaab", "COLO", "FLA") is None

    passed = espn_scoreboard_event_to_state(
        _board(sport="nfl", league_id="28", series="20", home="HBR", away="ROK"),
        prior_home=0.62,
    )
    assert passed.prior_home == 0.62
    assert passed.prior_source == "passed"


def test_prior_source_is_in_the_serialized_json() -> None:
    state = espn_scoreboard_event_to_state(
        _board(sport="nfl", league_id="28", series="20", home="DEN", away="NYG")
    )
    row = state_to_row(state)
    assert row["prior_source"] == "elo"
    assert list(row).index("prior_source") == list(row).index("prior_home") + 1
    restored = game_state_from_row(row)
    assert restored.prior_source == "elo"
    assert restored.prior_home == pytest.approx(state.prior_home)

    bare = dict(row)
    del bare["prior_source"]
    assert game_state_from_row(bare).prior_source == "default"

    script = render_widget_script([state])
    assert '"prior_source": "elo"' in script
    slate = render_slate_script([state])
    assert '"prior_source": "elo"' in slate
