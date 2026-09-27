"""ESPN NFL follow command. No test in this module opens a socket."""

from __future__ import annotations

import json
import socket
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from mswp import NFL_CONFIG, compute_wp

from live_wp.__main__ import main
from live_wp.feeds.espn import espn_scoreboard_event_to_state, espn_summary_to_states
from live_wp.follow import (
    fetch_json,
    follow_game,
    scoreboard_url,
    summary_url,
)
from live_wp.follow import run_follow
from live_wp.replay import format_line

ROOT = Path(__file__).resolve().parents[1]
BOARD_PATH = ROOT / "tests" / "fixtures" / "espn_nfl_scoreboard_snippet.json"
SUMMARY_PATH = ROOT / "tests" / "fixtures" / "espn_nfl_summary_snippet.json"


@pytest.fixture(autouse=True)
def _block_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("test opened a socket")

    monkeypatch.setattr(socket, "socket", blocked)


class _Response:
    def __init__(self, payload: object, url: str) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self._url = url
        self.closed = False

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url

    def close(self) -> None:
        self.closed = True


def _board() -> dict:
    return json.loads(BOARD_PATH.read_text(encoding="utf-8"))


def _summary() -> dict:
    return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))


def _pack(event: dict) -> dict:
    board = _board()
    board["events"] = [event]
    return board


def _live() -> dict:
    return deepcopy(_board()["events"][0])


def _clock(event: dict, clock: str, *, period: int = 2, state: str = "in") -> dict:
    event["competitions"][0]["status"] = {
        "displayClock": clock,
        "period": period,
        "type": {"state": state, "name": "STATUS"},
    }
    return event


def _odds(event: dict, moneyline: int | None) -> dict:
    competition = event["competitions"][0]
    if moneyline is None:
        competition.pop("odds", None)
    else:
        competition["odds"] = [{"homeTeamOdds": {"moneyLine": moneyline}}]
    return event


def _score(event: dict, home: int, away: int) -> dict:
    for side in event["competitions"][0]["competitors"]:
        if side["homeAway"] == "home":
            side["score"] = str(home)
        else:
            side["score"] = str(away)
    return event


def _line(event: dict, prior: float | None = None) -> str:
    state = espn_scoreboard_event_to_state(event)
    if prior is not None:
        state = replace(state, prior_home=prior)
    assert state.source == "espn"
    assert state.sport == "nfl"
    return format_line(state, compute_wp(state, state.prior_home, NFL_CONFIG))


class _Fetch:
    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = list(payloads)
        self.urls: list[str] = []

    def __call__(self, url: str) -> dict:
        self.urls.append(url)
        if not self._payloads:
            raise AssertionError(f"unexpected fetch {url}")
        return self._payloads.pop(0)


def test_list_date_uses_urllib_and_exits(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    board = _board()
    opened: list[str] = []

    def opener(request: object, timeout: float = 0) -> _Response:
        opened.append(request.full_url)  # type: ignore[attr-defined]
        assert timeout == 20
        return _Response(board, request.full_url)  # type: ignore[attr-defined]

    monkeypatch.setattr("live_wp.follow.urllib.request.urlopen", opener)
    assert main(["follow", "--date", "20260920"]) == 0
    captured = capsys.readouterr()
    assert opened == [scoreboard_url("20260920")]
    assert captured.out.splitlines() == [
        "55 ROK @ HBR live 3-7",
        "56 PINE @ BAY pre 0-0",
    ]
    assert captured.err == ""


def test_listing_the_current_slate_does_not_poll(capsys: pytest.CaptureFixture[str]) -> None:
    fetch = _Fetch([_board()])
    sleeps: list[float] = []
    assert run_follow([], fetch=fetch, sleep=lambda seconds: sleeps.append(seconds)) == 0
    assert fetch.urls == [scoreboard_url()]
    assert sleeps == []
    assert capsys.readouterr().out.splitlines() == [
        "55 ROK @ HBR live 3-7",
        "56 PINE @ BAY pre 0-0",
    ]


def test_follow_until_final_skips_unchanged_polls(capsys: pytest.CaptureFixture[str]) -> None:
    first = _live()
    same = deepcopy(first)
    same["winprobability"] = [{"homeWinPercentage": 0.11}]
    moved = deepcopy(first)
    moved["competitions"][0]["situation"]["down"] = 3
    repeat = deepcopy(moved)
    timeouts = deepcopy(moved)
    timeouts["competitions"][0]["situation"]["homeTimeouts"] = 0
    final = deepcopy(first)
    _clock(final, "0:00", period=4, state="post")
    _score(final, 14, 10)

    fetch = _Fetch([_pack(event) for event in (first, same, moved, repeat, timeouts, final)])
    sleeps: list[float] = []
    code = run_follow(["--game", "55"], fetch=fetch, sleep=lambda seconds: sleeps.append(seconds))
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert sleeps == [15, 15, 15, 15, 15]
    assert fetch.urls == [scoreboard_url()] * 6
    assert captured.out.splitlines() == [
        _line(first),
        _line(moved),
        _line(timeouts),
        _line(final),
    ]
    assert "0.910" not in captured.out
    assert "0.110" not in captured.out
    assert captured.out.splitlines()[-1].startswith("FINAL ")
    assert captured.out.splitlines()[-1].endswith("| 1.000")


def test_first_moneyline_is_frozen_and_a_missing_line_stays_one_half(
    capsys: pytest.CaptureFixture[str],
) -> None:
    bare = _odds(_clock(_live(), "10:00"), None)
    priced = _odds(_clock(deepcopy(_live()), "9:00"), -150)
    moved = _odds(_clock(deepcopy(_live()), "8:00"), 130)
    final = _odds(_clock(deepcopy(_live()), "0:00", period=4, state="post"), 130)
    _score(final, 21, 17)
    fetch = _Fetch([_pack(event) for event in (bare, priced, moved, final)])
    assert run_follow(["--game", "55", "--interval", "5"], fetch=fetch, sleep=lambda _s: None) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        _line(bare, 0.5),
        _line(priced, 0.6),
        _line(moved, 0.6),
        _line(final, 0.6),
    ]
    assert lines[2] != _line(moved)
    assert lines[0] != _line(priced, 0.6)


def test_even_money_is_frozen_at_one_half(capsys: pytest.CaptureFixture[str]) -> None:
    even = _odds(_clock(_live(), "10:00"), 100)
    later = _odds(_clock(deepcopy(_live()), "9:00"), -150)
    final = _odds(_clock(deepcopy(_live()), "0:00", period=4, state="post"), -150)
    _score(final, 21, 17)
    fetch = _Fetch([_pack(event) for event in (even, later, final)])
    assert run_follow(["--game", "55"], fetch=fetch, sleep=lambda _s: None) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == _line(even, 0.5)
    assert lines[1] == _line(later, 0.5)
    assert lines[1] != _line(later)
    assert lines[2].endswith("| 1.000")


def test_missing_event_uses_the_summary_once(capsys: pytest.CaptureFixture[str]) -> None:
    fetch = _Fetch([_board(), _summary()])
    sleeps: list[float] = []
    code = run_follow(
        ["--date", "20260920", "--game", "9001001"],
        fetch=fetch,
        sleep=lambda seconds: sleeps.append(seconds),
    )
    captured = capsys.readouterr()
    final = espn_summary_to_states(_summary(), density="all")[-1]
    assert code == 0
    assert sleeps == []
    assert fetch.urls == [scoreboard_url("20260920"), summary_url("9001001")]
    assert final.status == "final"
    assert final.source == "espn"
    assert captured.out.splitlines() == [
        format_line(final, compute_wp(final, final.prior_home, NFL_CONFIG))
    ]
    assert captured.out.endswith("| 1.000\n")
    assert "0.910" not in captured.out
    assert len(espn_summary_to_states(_summary(), density="all")) > 1


def test_follow_rejects_a_college_football_summary(capsys: pytest.CaptureFixture[str]) -> None:
    payload = json.loads(
        (ROOT / "tests" / "fixtures" / "espn_cfb_summary_snippet.json").read_text(encoding="utf-8")
    )
    code = run_follow(["--game", "88001"], fetch=lambda _url: payload, sleep=lambda _s: None)
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "college football" in captured.err.lower()


def test_college_football_url_does_not_open_a_socket() -> None:
    def opener(request: object, timeout: float = 0) -> _Response:
        raise AssertionError(f"opened {request!r}")

    with pytest.raises(ValueError, match="college football"):
        fetch_json(
            "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
            opener=opener,
        )
    with pytest.raises(ValueError, match="college football"):
        fetch_json(
            "https://site.api.espn.com/apis/site/v2/sports/football/ncaaf/summary?event=9",
            opener=opener,
        )


def test_redirect_to_college_football_is_refused() -> None:
    class _Redirect:
        def __init__(self) -> None:
            self.closed = False

        def geturl(self) -> str:
            return (
                "https://site.api.espn.com/apis/site/v2/sports/football/"
                "college-football/scoreboard"
            )

        def read(self) -> bytes:
            raise AssertionError("read a college football body")

        def close(self) -> None:
            self.closed = True

    response = _Redirect()

    def opener(request: object, timeout: float = 0) -> _Redirect:
        assert "football/nfl/" in request.full_url  # type: ignore[attr-defined]
        return response

    with pytest.raises(ValueError, match="college football"):
        fetch_json(scoreboard_url(), opener=opener)
    assert response.closed


def test_college_and_other_leagues_are_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    college = {
        "leagues": [
            {
                "id": "23",
                "slug": "college-football",
                "abbreviation": "NCAAF",
                "name": "NCAA Football",
            }
        ],
        "events": [],
    }
    nba = {
        "leagues": [
            {
                "id": "46",
                "slug": "nba",
                "abbreviation": "NBA",
                "name": "National Basketball Association",
            }
        ],
        "events": [],
    }
    listed = run_follow(["--date", "20260920"], fetch=lambda _url: college, sleep=lambda _s: None)
    listed_err = capsys.readouterr()
    assert listed == 1
    assert listed_err.out == ""
    assert "college football" in listed_err.err.lower()

    followed = run_follow(["--game", "55"], fetch=lambda _url: nba, sleep=lambda _s: None)
    followed_err = capsys.readouterr()
    assert followed == 1
    assert followed_err.out == ""
    assert "not NFL" in followed_err.err

    event = json.loads(json.dumps(_live()).replace("l:28", "l:23"))
    mixed = _board()
    mixed["events"] = [event]
    urls: list[str] = []

    def fetch(url: str) -> dict:
        urls.append(url)
        return mixed

    mixed_code = run_follow(["--game", "55"], fetch=fetch, sleep=lambda _s: None)
    mixed_err = capsys.readouterr()
    assert mixed_code == 1
    assert mixed_err.out == ""
    assert "college football" in mixed_err.err.lower()
    assert urls == [scoreboard_url()]


def test_college_game_url_is_rejected_before_fetch(capsys: pytest.CaptureFixture[str]) -> None:
    def fetch(url: str) -> dict:
        raise AssertionError(url)

    code = run_follow(
        [
            "--game",
            "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event=9",
        ],
        fetch=fetch,
    )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "college football" in captured.err.lower()


def test_bad_interval_and_date_do_not_fetch(capsys: pytest.CaptureFixture[str]) -> None:
    urls: list[str] = []

    def fetch(url: str) -> dict:
        urls.append(url)
        return _board()

    assert run_follow(["--interval", "4"], fetch=fetch) == 2
    assert "at least 5" in capsys.readouterr().err
    assert run_follow(["--date", "2026-09-20"], fetch=fetch) == 2
    assert "YYYYMMDD" in capsys.readouterr().err
    assert run_follow(["--date", "20260931"], fetch=fetch) == 2
    assert urls == []


def test_keyboard_interrupt_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    def sleep(_seconds: float) -> None:
        raise KeyboardInterrupt

    code = run_follow(
        ["--game", "55", "--interval", "5"],
        fetch=lambda _url: _pack(_live()),
        sleep=sleep,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out.splitlines() == [_line(_live())]


def test_direct_follow_rejects_a_short_interval() -> None:
    with pytest.raises(ValueError, match="at least 5"):
        follow_game("55", interval=4, fetch=lambda _url: _board(), sleep=lambda _s: None)


def test_network_import_stays_in_the_follow_command() -> None:
    hits: list[str] = []
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "urllib" in text or "urlopen" in text:
            hits.append(path.relative_to(ROOT / "src").as_posix())
    assert hits == ["live_wp/follow.py"]
