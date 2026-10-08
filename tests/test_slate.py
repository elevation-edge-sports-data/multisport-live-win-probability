"""Scoreboard slate writer. No test in this module opens a socket."""

from __future__ import annotations

import json
import socket
from copy import deepcopy
from pathlib import Path

import pytest

from live_wp.__main__ import main
from live_wp.follow import scoreboard_url, slate_lines, slate_states
from live_wp.slate import (
    DEFAULT_OUT,
    _real_fetch,
    parse_slate_args,
    render_slate_script,
    run_slate,
)

ROOT = Path(__file__).resolve().parents[1]
BOARD_PATH = ROOT / "tests" / "fixtures" / "espn_nfl_scoreboard_snippet.json"
_FIELDS = (
    "sport",
    "game_id",
    "away",
    "home",
    "status",
    "away_score",
    "home_score",
    "prior_home",
)
_LEAGUES = {
    "nfl": {
        "id": "28",
        "uid": "s:20~l:28",
        "slug": "nfl",
        "abbreviation": "NFL",
        "name": "National Football League",
    },
    "nhl": {
        "id": "90",
        "uid": "s:70~l:90",
        "slug": "nhl",
        "abbreviation": "NHL",
        "name": "National Hockey League",
    },
    "nba": {
        "id": "46",
        "uid": "s:40~l:46",
        "slug": "nba",
        "abbreviation": "NBA",
        "name": "National Basketball Association",
    },
}
_COLLEGE_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/"
    "college-football/scoreboard"
)


@pytest.fixture(autouse=True)
def _block_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("test opened a socket")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr("live_wp.follow.urllib.request.urlopen", blocked)


def _nfl_board() -> dict:
    return json.loads(BOARD_PATH.read_text(encoding="utf-8"))


def _empty(sport: str) -> dict:
    return {"leagues": [dict(_LEAGUES[sport])], "events": []}


def _event(
    sport: str,
    event_id: str,
    *,
    home: str,
    away: str,
    home_score: str,
    away_score: str,
    state: str,
    period: int,
    clock: str,
    moneyline: int | None = None,
) -> dict:
    league = "90" if sport == "nhl" else "46"
    series = "70" if sport == "nhl" else "40"
    uid = f"s:{series}~l:{league}~e:{event_id}"
    competition: dict = {
        "id": event_id,
        "uid": uid,
        "date": "2026-05-13T00:00:00Z",
        "competitors": [
            {
                "homeAway": "home",
                "score": home_score,
                "team": {
                    "id": "1",
                    "uid": f"s:{series}~l:{league}~t:1",
                    "abbreviation": home,
                },
            },
            {
                "homeAway": "away",
                "score": away_score,
                "team": {
                    "id": "2",
                    "uid": f"s:{series}~l:{league}~t:2",
                    "abbreviation": away,
                },
            },
        ],
        "status": {
            "displayClock": clock,
            "period": period,
            "type": {"state": state, "name": "STATUS"},
        },
    }
    if moneyline is not None:
        competition["odds"] = [{"homeTeamOdds": {"moneyLine": moneyline}}]
    return {
        "id": event_id,
        "uid": uid,
        "date": "2026-05-13T00:00:00Z",
        "competitions": [competition],
    }


def _pack(sport: str, events: list[dict]) -> dict:
    return {"leagues": [dict(_LEAGUES[sport])], "events": events}


class _Fetch:
    def __init__(self, boards: dict[str, dict]) -> None:
        self._boards = boards
        self.urls: list[str] = []

    def __call__(self, url: str) -> dict:
        self.urls.append(url)
        for sport in ("nfl", "nhl", "nba"):
            root = scoreboard_url(sport=sport)
            if url == root or url.startswith(root + "?"):
                return self._boards[sport]
        raise AssertionError(url)


def _rows(text: str) -> list[dict]:
    prefix = "window.MSWP_SLATE = "
    assert text.startswith(prefix)
    assert text.endswith(";\n")
    assert "\r" not in text
    payload = json.loads(text[len(prefix) : -2])
    assert isinstance(payload, list)
    return payload


def _assert_no_college(urls: list[str]) -> None:
    joined = " ".join(urls).lower()
    for token in (
        "college-football",
        "college-hockey",
        "college-basketball",
        "mens-college",
        "ncaaf",
        "ncaah",
        "ncaab",
    ):
        assert token not in joined


def test_three_sports_one_pass(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    nfl = _nfl_board()
    nhl = _pack(
        "nhl",
        [
            _event(
                "nhl",
                "77",
                home="COL",
                away="MIN",
                home_score="2",
                away_score="1",
                state="post",
                period=3,
                clock="0:00",
                moneyline=-121,
            )
        ],
    )
    nba = _pack(
        "nba",
        [
            _event(
                "nba",
                "88",
                home="LAL",
                away="DEN",
                home_score="10",
                away_score="8",
                state="in",
                period=2,
                clock="5:00",
            )
        ],
    )
    boards = {"nfl": nfl, "nhl": nhl, "nba": nba}
    fetch = _Fetch(boards)
    sleeps: list[float] = []
    out = tmp_path / "nested" / "slate.js"

    def sleep(_seconds: float) -> None:
        sleeps.append(_seconds)
        raise AssertionError("one pass slept")

    code = run_slate(["--out", str(out)], fetch=fetch, sleep=sleep)
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert sleeps == []
    assert fetch.urls == [
        scoreboard_url(sport="nfl"),
        scoreboard_url(sport="nhl"),
        scoreboard_url(sport="nba"),
    ]
    assert fetch.urls[0] == scoreboard_url()
    _assert_no_college(fetch.urls)
    assert all("summary" not in url for url in fetch.urls)

    states = []
    expected_lines = []
    for sport in ("nfl", "nhl", "nba"):
        states.extend(slate_states(boards[sport], sport=sport))
        expected_lines.extend(
            f"{sport} {line}" for line in slate_lines(boards[sport], sport=sport)
        )
    text = out.read_text(encoding="utf-8")
    assert text == render_slate_script(states)
    assert not out.with_name(out.name + ".tmp").exists()
    assert captured.out.splitlines() == expected_lines
    assert captured.out.endswith("\n")
    rows = _rows(text)
    assert [list(row) for row in rows] == [list(_FIELDS)] * len(states)
    assert [row["sport"] for row in rows] == [state.sport for state in states]
    assert [row["status"] for row in rows] == [state.status for state in states]
    assert set(row["status"] for row in rows) >= {"pre", "live", "final"}
    assert rows[0]["prior_home"] == pytest.approx(states[0].prior_home)
    assert rows[0]["prior_home"] == pytest.approx(0.6)
    assert "0.91" not in text
    bare = next(row for row in rows if row["game_id"] == "56")
    assert bare["prior_home"] == 0.5
    for forbidden in (
        "clock",
        "possession",
        "down",
        "distance",
        "yardline",
        "situation",
        "seconds_remaining",
        "strength",
    ):
        assert forbidden not in text


def test_college_url_is_never_requested(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fetch = _Fetch({sport: _empty(sport) for sport in ("nfl", "nhl", "nba")})
    out = tmp_path / "slate.js"
    assert run_slate(["--out", str(out)], fetch=fetch, sleep=lambda _s: None) == 0
    _assert_no_college(fetch.urls)
    assert fetch.urls == [scoreboard_url(sport=sport) for sport in ("nfl", "nhl", "nba")]

    def refuse(url: str) -> dict:
        raise AssertionError(url)

    for sport in ("ncaaf", "ncaah", "ncaab", "nfl"):
        code = run_slate(["--sport", sport, "--out", str(out)], fetch=refuse)
        captured = capsys.readouterr()
        assert code == 2
        assert captured.out == ""
        assert "unrecognized argument: --sport" in captured.err

    with pytest.raises(ValueError, match="nfl, nhl, and nba"):
        _real_fetch(_COLLEGE_URL)
    with pytest.raises(ValueError, match="nfl, nhl, and nba"):
        _real_fetch(
            "https://site.api.espn.com/apis/site/v2/sports/hockey/"
            "mens-college-hockey/scoreboard"
        )
    with pytest.raises(ValueError, match="nfl, nhl, and nba"):
        _real_fetch(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/"
            "mens-college-basketball/scoreboard"
        )


def test_empty_scoreboard_writes_an_empty_array(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fetch = _Fetch({sport: _empty(sport) for sport in ("nfl", "nhl", "nba")})
    out = tmp_path / "slate.js"
    code = run_slate(["--out", str(out)], fetch=fetch, sleep=lambda _s: None)
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert out.read_text(encoding="utf-8") == "window.MSWP_SLATE = [];\n"
    assert _rows(out.read_text(encoding="utf-8")) == []


def test_missing_moneyline_prior_is_one_half(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    board = _nfl_board()
    event = deepcopy(board["events"][0])
    event["competitions"][0].pop("odds")
    event["winprobability"] = [{"homeWinPercentage": 0.91}]
    boards = {
        "nfl": {"leagues": board["leagues"], "events": [event]},
        "nhl": _empty("nhl"),
        "nba": _empty("nba"),
    }
    fetch = _Fetch(boards)
    out = tmp_path / "slate.js"
    assert run_slate(["--out", str(out)], fetch=fetch, sleep=lambda _s: None) == 0
    text = out.read_text(encoding="utf-8")
    rows = _rows(text)
    assert len(rows) == 1
    assert rows[0]["prior_home"] == 0.5
    assert rows[0]["status"] == "live"
    assert "0.91" not in text
    assert capsys.readouterr().out.splitlines() == [
        f"nfl {line}" for line in slate_lines(boards["nfl"], sport="nfl")
    ]


def test_interval_under_5_is_rejected(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    out = tmp_path / "slate.js"

    def fetch(url: str) -> dict:
        raise AssertionError(url)

    assert main(["slate", "--interval", "4", "--out", str(out)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "interval must be at least 5 seconds" in captured.err
    assert "python -m live_wp slate [--date YYYYMMDD] [--interval 15]" in captured.err
    assert not out.exists()

    assert run_slate(["--interval", "4.9", "--out", str(out)], fetch=fetch) == 2
    assert "interval must be at least 5 seconds" in capsys.readouterr().err
    assert run_slate(["--interval", "abc", "--out", str(out)], fetch=fetch) == 2
    assert "interval must be a number of seconds" in capsys.readouterr().err
    assert run_slate(["--interval=", "--out", str(out)], fetch=fetch) == 2
    assert "--interval needs a value" in capsys.readouterr().err
    assert not out.exists()


def test_date_must_be_yyyymmdd(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    out = tmp_path / "slate.js"

    def fetch(url: str) -> dict:
        raise AssertionError(url)

    assert run_slate(["--date", "2026-09-20", "--out", str(out)], fetch=fetch) == 2
    assert "date must be YYYYMMDD" in capsys.readouterr().err
    assert run_slate(["--date", "20260931", "--out", str(out)], fetch=fetch) == 2
    assert "date must be YYYYMMDD" in capsys.readouterr().err
    assert not out.exists()

    seen = _Fetch({sport: _empty(sport) for sport in ("nfl", "nhl", "nba")})
    assert run_slate(["--date", "20260920", "--out", str(out)], fetch=seen) == 0
    assert seen.urls == [
        scoreboard_url("20260920", sport="nfl"),
        scoreboard_url("20260920", sport="nhl"),
        scoreboard_url("20260920", sport="nba"),
    ]
    _assert_no_college(seen.urls)


def test_interval_polls_until_ctrl_c(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fetch = _Fetch({sport: _empty(sport) for sport in ("nfl", "nhl", "nba")})
    out = tmp_path / "slate.js"
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise KeyboardInterrupt

    assert run_slate(["--interval", "--out", str(out)], fetch=fetch, sleep=sleep) == 0
    assert sleeps == [15.0]
    assert len(fetch.urls) == 3
    assert out.read_text(encoding="utf-8") == "window.MSWP_SLATE = [];\n"
    assert capsys.readouterr().err == ""
    assert not out.with_name(out.name + ".tmp").exists()

    sleeps.clear()
    assert (
        run_slate(["--interval", "5", "--out", str(out)], fetch=fetch, sleep=sleep) == 0
    )
    assert sleeps == [5.0]
    assert parse_slate_args(["--interval"]).interval == 15.0
    assert parse_slate_args([]).interval is None


def test_write_error_keeps_the_old_file(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    out = tmp_path / "slate.js"
    previous = b"previous slate\n"
    out.write_bytes(previous)
    fetch = _Fetch({sport: _empty(sport) for sport in ("nfl", "nhl", "nba")})

    def fail_replace(self: Path, target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)
    code = run_slate(["--out", str(out)], fetch=fetch, sleep=lambda _s: None)
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "replace failed" in captured.err
    assert out.read_bytes() == previous
    assert not out.with_name(out.name + ".tmp").exists()


def test_default_out_is_widget_slate_and_usage_lists_the_command() -> None:
    options = parse_slate_args([])
    assert options.out == DEFAULT_OUT
    assert options.out.name == "slate.js"
    assert options.out.parent.name == "widget"
    assert options.date is None
    source = (ROOT / "src" / "live_wp" / "__main__.py").read_text(encoding="utf-8")
    assert (
        "python -m live_wp slate [--date YYYYMMDD] [--interval 15] "
        "[--out widget/slate.js]"
    ) in source
