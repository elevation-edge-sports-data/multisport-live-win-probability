"""Local page server and the live replay writer.

Serve tests bind 127.0.0.1 and then stop the server. Every other test
in this module blocks sockets. None of them call ESPN.
"""

from __future__ import annotations

import http.client
import inspect
import json
import socket
import threading
import time
from copy import deepcopy
from pathlib import Path

import pytest

from mswp import compute_wp

from live_wp.__main__ import main
from live_wp.follow import (
    FollowError,
    _with_frozen_prior,
    scoreboard_url,
    slate_states,
    summary_url,
)
from live_wp.slate import render_slate_script, slate_rows
from live_wp.live import (
    DEFAULT_FOLLOW,
    DEFAULT_OUT,
    parse_live_args,
    replay_script,
    run_live,
)
from live_wp.replay import config_for_state, format_line, render_widget_script
from live_wp.serve import (
    _Handler,
    _request_from_localhost,
    _request_path,
    bind_widget_server,
    parse_serve_args,
    run_serve,
)

ROOT = Path(__file__).resolve().parents[1]
BOARD_PATH = ROOT / "tests" / "fixtures" / "espn_nfl_scoreboard_snippet.json"


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("test opened a socket")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr("live_wp.follow.urllib.request.urlopen", blocked)


def _board() -> dict:
    return json.loads(BOARD_PATH.read_text(encoding="utf-8"))


def _live_event() -> dict:
    return deepcopy(_board()["events"][0])


def _pack(event: dict) -> dict:
    board = _board()
    board["events"] = [event]
    return board


def _clock(event: dict, clock: str, *, period: int = 2, state: str = "in") -> dict:
    event["competitions"][0]["status"] = {
        "displayClock": clock,
        "period": period,
        "type": {"state": state, "name": "STATUS"},
    }
    return event


def _score(event: dict, home: int, away: int) -> dict:
    for side in event["competitions"][0]["competitors"]:
        if side["homeAway"] == "home":
            side["score"] = str(home)
        else:
            side["score"] = str(away)
    return event


class _Fetch:
    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = list(payloads)
        self.urls: list[str] = []

    def __call__(self, url: str) -> dict:
        self.urls.append(url)
        if not self._payloads:
            raise AssertionError(f"unexpected fetch {url}")
        return self._payloads.pop(0)


def _get(host: str, port: int, path: str) -> tuple[int, bytes]:
    last: Exception | None = None
    for _ in range(20):
        try:
            with socket.create_connection((host, port), timeout=2) as sock:
                sock.settimeout(2)
                request = (
                    f"GET {path} HTTP/1.0\r\nHost: {host}\r\nConnection: close\r\n\r\n"
                )
                sock.sendall(request.encode("ascii"))
                chunks: list[bytes] = []
                while True:
                    block = sock.recv(8192)
                    if not block:
                        break
                    chunks.append(block)
            data = b"".join(chunks)
            head, _, body = data.partition(b"\r\n\r\n")
            return int(head.split()[1]), body
        except OSError as exc:
            last = exc
            time.sleep(0.05)
    raise AssertionError(last)


class _Running:
    """One local page server. Leaving the block always stops it."""

    def __init__(self) -> None:
        self.server: object = None
        self.code: object = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> _Running:
        ready = threading.Event()

        def on_ready(server: object) -> None:
            self.server = server
            ready.set()

        def runner() -> None:
            self.code = run_serve(["--port", "0"], on_ready=on_ready)

        self.thread = threading.Thread(target=runner, daemon=True)
        self.thread.start()
        if not ready.wait(5):
            self.stop()
            raise AssertionError("server did not start")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def stop(self) -> None:
        server = self.server
        self.server = None
        try:
            if server is not None:
                server.shutdown()  # type: ignore[attr-defined]
        finally:
            if self.thread is not None:
                self.thread.join(5)


def _http_get(host: str, port: int, path: str) -> tuple[int, bytes]:
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _http_post(
    host: str,
    port: int,
    path: str,
    body: bytes,
    *,
    host_header: str | None = None,
) -> tuple[int, bytes]:
    last: Exception | None = None
    headers = {"Content-Type": "application/json"}
    if host_header is not None:
        headers["Host"] = host_header
    for _ in range(20):
        try:
            connection = http.client.HTTPConnection(host, port, timeout=2)
            try:
                connection.request("POST", path, body=body, headers=headers)
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()
        except OSError as exc:
            last = exc
            time.sleep(0.05)
    raise AssertionError(last)


def _selection(sport: str, game_id: str) -> str:
    return json.dumps({"sport": sport, "game_id": game_id}) + "\n"


_PRO_LEAGUES = {
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


def _pro_event(
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
) -> dict:
    league = "90" if sport == "nhl" else "46"
    series = "70" if sport == "nhl" else "40"
    uid = f"s:{series}~l:{league}~e:{event_id}"
    return {
        "id": event_id,
        "uid": uid,
        "date": "2026-05-13T00:00:00Z",
        "competitions": [
            {
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
        ],
    }


def _pro_board(sport: str, events: list[dict]) -> dict:
    return {"leagues": [dict(_PRO_LEAGUES[sport])], "events": events}


def _nfl_board_of(events: list[dict]) -> dict:
    board = _board()
    board["events"] = events
    return board


def _slate_script(boards: dict[str, dict]) -> str:
    states = []
    for sport in ("nfl", "nhl", "nba"):
        states.extend(slate_states(boards[sport], sport=sport))
    return render_slate_script(states)


def _scoreboard_cycle() -> list[str]:
    return [scoreboard_url(sport=sport) for sport in ("nfl", "nhl", "nba")]


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


def _real_slate_bytes() -> bytes | None:
    path = ROOT / "slate.js"
    if not path.is_file():
        return None
    return path.read_bytes()


def test_serve_binds_localhost_and_stops() -> None:
    with _Running() as running:
        server = running.server
        host, port = server.server_address[:2]  # type: ignore[attr-defined]
        assert host == "127.0.0.1"
        assert server.socket.family == socket.AF_INET  # type: ignore[attr-defined]
        assert server.socket.getsockname()[0] == "127.0.0.1"  # type: ignore[attr-defined]
        reuse = server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR)  # type: ignore[attr-defined]
        assert reuse == 0
        status, body = _get(host, port, "/")
        assert status == 200
        assert b"Multisport live win probability" in body
        assert b'id="slate-date"' in body
        assert b'type="date"' in body
        assert b"slate-date-row" in body
        assert b"live_replay.js" not in body
        assert b"espn" not in body.lower()
        live_status, live_body = _get(host, port, "/replays/live_replay.js")
        assert live_status == 200
        assert b"window." not in live_body
        bust_status, bust_body = _get(host, port, "/replays/live_replay.js?t=1")
        assert bust_status == 200
        assert bust_body == live_body
        css_status, css = _get(host, port, "/styles.css")
        assert css_status == 200
        assert b"text-align: right" in css
        missing, missing_body = _get(
            host, port, "/apis/site/v2/sports/football/nfl/scoreboard"
        )
        assert missing == 404
        assert b"events" not in missing_body
        colors_status, colors_body = _get(host, port, "/assets/colors/nfl.json")
        assert colors_status == 200
        assert b'"id": "DEN"' in colors_body
        logo_status, logo_body = _get(host, port, "/assets/logos/nfl/DEN.png")
        assert logo_status == 200
        assert logo_body.startswith(b"\x89PNG\r\n\x1a\n")
        _escape_status, escape_body = _get(host, port, "/../pyproject.toml")
        assert b"setuptools" not in escape_body
        assert b"[project]" not in escape_body
        assets_escape, assets_escape_body = _get(host, port, "/assets/../pyproject.toml")
        assert assets_escape != 200 or b"setuptools" not in assets_escape_body
        assert b"[project]" not in assets_escape_body
    assert running.thread is not None
    assert not running.thread.is_alive()
    assert running.code == 0
    with pytest.raises(OSError):
        connection = socket.create_connection((host, port), timeout=1)
        connection.close()


def test_local_http_get_returns_the_page_then_stops() -> None:
    with _Running() as running:
        server = running.server
        host, port = server.server_address[:2]  # type: ignore[attr-defined]
        for path in ("/", "/index.html"):
            status, body = _http_get(host, port, path)
            assert status == 200
            assert b"<!DOCTYPE html>" in body
            assert b"Multisport live win probability" in body
        missing, missing_body = _http_get(host, port, "/no-such-file")
        assert missing == 404
        assert b"Multisport live win probability" not in missing_body
    assert running.thread is not None
    assert not running.thread.is_alive()
    assert running.code == 0
    with pytest.raises(OSError):
        connection = socket.create_connection((host, port), timeout=1)
        connection.close()


def test_handler_exception_is_printed_as_500(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(_self: object) -> None:
        raise RuntimeError("handler failed")

    monkeypatch.setattr("live_wp.serve._Handler.do_GET", explode)
    with _Running() as running:
        server = running.server
        host, port = server.server_address[:2]  # type: ignore[attr-defined]
        status, body = _http_get(host, port, "/")
        assert status == 500
        assert b"Internal Server Error" in body
    captured = capsys.readouterr()
    assert "handler failed" in captured.err
    assert "Traceback" in captured.err
    assert running.code == 0


def test_serve_exits_when_the_port_is_taken(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with bind_widget_server(0) as holder:
        port = holder.server_address[1]
        assert holder.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 0
        box: dict[str, object] = {}

        def runner() -> None:
            box["code"] = run_serve(["--port", str(port)])

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join(3)
        if thread.is_alive():
            raise AssertionError("serve kept running on a taken port")
    assert box["code"] == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert str(port) in captured.err


def test_serve_post_follow_writes_follow_json_and_keeps_a_bad_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path
    index = root / "index.html"
    index.write_text(
        "<!DOCTYPE html><title>Multisport live win probability</title>\n",
        encoding="utf-8",
        newline="\n",
    )
    follow = root / "follow.json"
    follow.write_text(_selection("nba", "11"), encoding="utf-8", newline="\n")
    original = follow.read_bytes()
    kept_index = index.read_bytes()
    server = bind_widget_server(0, directory=root)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        status, _body = _http_post(host, port, "/follow", b"not-json")
        assert status == 400
        assert follow.read_bytes() == original
        status, _body = _http_post(
            host, port, "/follow", b'{"sport":"ncaaf","game_id":"55"}'
        )
        assert status == 400
        assert follow.read_bytes() == original
        status, _body = _http_post(
            host, port, "/follow", b'{"sport":"nfl","game_id":"55","extra":1}'
        )
        assert status == 400
        assert follow.read_bytes() == original
        status, body = _http_post(
            host, port, "/follow", b'{"sport":"nfl","game_id":"55"}'
        )
        assert status == 204
        assert body == b""
        text = follow.read_text(encoding="utf-8")
        assert "\r" not in text
        assert json.loads(text) == {"sport": "nfl", "game_id": "55"}
        assert text.index('"sport"') < text.index('"game_id"')
        assert not follow.with_name(follow.name + ".tmp").exists()
        good = follow.read_bytes()
        status, _body = _http_post(host, port, "/follow", b'{"sport":"nfl"}')
        assert status == 400
        assert follow.read_bytes() == good
        status, _body = _http_post(
            host,
            port,
            "/follow",
            b'{"sport":"nhl","game_id":"77"}',
            host_header="example.com",
        )
        assert status == 403
        assert follow.read_bytes() == good
        status, page = _http_get(host, port, "/index.html")
        assert status == 200
        assert page == kept_index
        status, _body = _http_post(
            host, port, "/index.html", b'{"sport":"nba","game_id":"99"}'
        )
        assert status == 404
        assert follow.read_bytes() == good
        assert index.read_bytes() == kept_index
        status, _body = _http_post(
            host,
            port,
            "/follow",
            b'{"sport":"nhl","game_id":"77"}',
            host_header="localhost",
        )
        assert status == 204
        assert json.loads(follow.read_text(encoding="utf-8")) == {
            "sport": "nhl",
            "game_id": "77",
        }
        kept = follow.read_bytes()

        def fail_replace(self: Path, target: Path) -> None:
            raise OSError("replace failed")

        monkeypatch.setattr(Path, "replace", fail_replace)
        status, failed = _http_post(
            host, port, "/follow", b'{"sport":"nba","game_id":"88"}'
        )
        assert status == 500
        assert b"Internal Server Error" in failed
        assert follow.read_bytes() == kept
        assert not follow.with_name(follow.name + ".tmp").exists()
        names = sorted(path.name for path in root.iterdir())
        assert names == ["follow.json", "index.html"]
        assert index.is_file()
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()
    assert not thread.is_alive()


_FEED_LEAGUES = {
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
    "ncaaf": {
        "id": "23",
        "uid": "s:20~l:23",
        "slug": "college-football",
        "abbreviation": "NCAAF",
        "name": "NCAA Football",
    },
    "ncaah": {
        "id": "91",
        "uid": "s:70~l:91",
        "slug": "mens-college-hockey",
        "abbreviation": "NCAAH",
        "name": "NCAA Men's Ice Hockey",
    },
    "ncaab": {
        "id": "41",
        "uid": "s:40~l:41",
        "slug": "mens-college-basketball",
        "abbreviation": "NCAAB",
        "name": "NCAA Men's Basketball",
    },
}
_FEED_SERIES = {
    "nfl": ("20", "28"),
    "nhl": ("70", "90"),
    "nba": ("40", "46"),
    "ncaaf": ("20", "23"),
    "ncaah": ("70", "91"),
    "ncaab": ("40", "41"),
}
_SLATE_FIELDS = (
    "sport",
    "game_id",
    "away",
    "home",
    "status",
    "away_score",
    "home_score",
    "prior_home",
)


def _feed_event(
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
    series, league = _FEED_SERIES[sport]
    uid = f"s:{series}~l:{league}~e:{event_id}"
    competition: dict = {
        "id": event_id,
        "uid": uid,
        "date": "2026-09-20T00:00:00Z",
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
        "date": "2026-09-20T00:00:00Z",
        "competitions": [competition],
    }


def _feed_board(sport: str, events: list[dict]) -> dict:
    return {"leagues": [dict(_FEED_LEAGUES[sport])], "events": events}


class _SlateFetch:
    def __init__(self, boards: dict[str, dict], empty: dict[str, dict]) -> None:
        self.urls: list[str] = []
        self._boards = boards
        self._empty = empty

    def __call__(self, url: str) -> dict:
        self.urls.append(url)
        if "dates=20260101" in url:
            return self._board_for(url, self._empty)
        return self._board_for(url, self._boards)

    def _board_for(self, url: str, boards: dict[str, dict]) -> dict:
        for sport, board in boards.items():
            root = scoreboard_url(sport=sport)
            if url == root or url.startswith(root + "?"):
                return board
        raise AssertionError(url)


def _http_request_target(host: str, port: int, target: str) -> tuple[int, bytes]:
    """Send one origin-form or absolute-form GET. Returns status and body."""
    request = (
        f"GET {target} HTTP/1.0\r\n"
        f"Host: {host}:{port}\r\n"
        "Connection: close\r\n\r\n"
    )
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.settimeout(5)
        sock.sendall(request.encode("ascii"))
        chunks: list[bytes] = []
        while True:
            block = sock.recv(8192)
            if not block:
                break
            chunks.append(block)
    data = b"".join(chunks)
    head, _, body = data.partition(b"\r\n\r\n")
    return int(head.split()[1]), body


def _http_get_meta(
    host: str,
    port: int,
    path: str,
    *,
    host_header: str | None = None,
) -> tuple[int, str, str, bytes]:
    last: Exception | None = None
    headers: dict[str, str] = {}
    if host_header is not None:
        headers["Host"] = host_header
    for _ in range(20):
        try:
            connection = http.client.HTTPConnection(host, port, timeout=2)
            try:
                connection.request("GET", path, headers=headers)
                response = connection.getresponse()
                content_type = response.getheader("Content-Type") or ""
                cache = response.getheader("Cache-Control") or ""
                return response.status, content_type, cache, response.read()
            finally:
                connection.close()
        except OSError as exc:
            last = exc
            time.sleep(0.05)
    raise AssertionError(last)


def test_get_slate_returns_one_sport_for_the_requested_day(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("slate route opened a network request")

    monkeypatch.setattr("live_wp.follow.urllib.request.urlopen", blocked)
    real_before = _real_slate_bytes()
    boards = {
        "nfl": _board(),
        "nhl": _feed_board(
            "nhl",
            [
                _feed_event(
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
        ),
        "nba": _feed_board(
            "nba",
            [
                _feed_event(
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
        ),
        "ncaaf": _feed_board(
            "ncaaf",
            [
                _feed_event(
                    "ncaaf",
                    "88001",
                    home="TEX",
                    away="OU",
                    home_score="21",
                    away_score="14",
                    state="post",
                    period=4,
                    clock="0:00",
                    moneyline=-150,
                )
            ],
        ),
        "ncaah": _feed_board(
            "ncaah",
            [
                _feed_event(
                    "ncaah",
                    "91001",
                    home="DEN",
                    away="MICH",
                    home_score="3",
                    away_score="2",
                    state="post",
                    period=3,
                    clock="0:00",
                )
            ],
        ),
        "ncaab": _feed_board(
            "ncaab",
            [
                _feed_event(
                    "ncaab",
                    "401638608",
                    home="COLO",
                    away="FLA",
                    home_score="102",
                    away_score="100",
                    state="in",
                    period=2,
                    clock="5:00",
                )
            ],
        ),
    }
    empty = {sport: _feed_board(sport, []) for sport in boards}
    reader = _SlateFetch(boards, empty)
    expected = {
        sport: slate_rows(date="20260920", sport=sport, fetch=reader)
        for sport in boards
    }
    assert reader.urls == [
        scoreboard_url("20260920", sport=sport) for sport in boards
    ]
    assert all(row for row in expected.values())
    server_reader = _SlateFetch(boards, empty)
    root = tmp_path
    marker = "window.MSWP_SLATE = [];\n"
    (root / "slate.js").write_text(marker, encoding="utf-8", newline="\n")
    (root / "index.html").write_text(
        "<!DOCTYPE html><title>Multisport live win probability</title>\n",
        encoding="utf-8",
        newline="\n",
    )
    server = bind_widget_server(0, directory=root)
    server.slate_fetch = server_reader
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        for sport in boards:
            before = len(server_reader.urls)
            status, content_type, cache, body = _http_get_meta(
                host, port, f"/slate?sport={sport}&date=20260920"
            )
            assert status == 200
            assert content_type.startswith("application/json")
            assert cache == "no-store"
            rows = json.loads(body)
            assert rows == expected[sport]
            assert rows
            assert list(rows[0]) == list(_SLATE_FIELDS)
            text = body.decode("utf-8")
            assert "window.MSWP_SLATE" not in text
            for forbidden in ("clock", "possession", "win_prob", '"wp"'):
                assert forbidden not in text
            assert server_reader.urls[before:] == [
                scoreboard_url("20260920", sport=sport)
            ]
            assert "summary" not in server_reader.urls[-1]
        status, content_type, _cache, body = _http_get_meta(
            host, port, "/slate?sport=NCAAF&date=20260920"
        )
        assert status == 200
        assert content_type.startswith("application/json")
        assert json.loads(body) == expected["ncaaf"]
        status, content_type, _cache, body = _http_get_meta(
            host, port, "/slate?date=20260101&sport=nba"
        )
        assert status == 200
        assert json.loads(body) == []
        assert server_reader.urls[-1] == scoreboard_url("20260101", sport="nba")
        for path in (
            "/slate",
            "/slate?sport=nfl",
            "/slate?date=20260920",
            "/slate?sport=mlb&date=20260920",
            "/slate?sport=ncaaf&date=2026-09-20",
            "/slate?sport=ncaah&date=20260931",
            "/slate?sport=nba&date=20260230",
        ):
            before = len(server_reader.urls)
            status, _content_type, _cache, _body = _http_get_meta(host, port, path)
            assert status == 400, path
            assert len(server_reader.urls) == before
        before = len(server_reader.urls)
        status, _content_type, _cache, _body = _http_get_meta(
            host,
            port,
            "/slate?sport=nhl&date=20260920",
            host_header="example.com",
        )
        assert status == 403
        assert len(server_reader.urls) == before
        for target in (
            "/slate?sport=ncaaf&date=20261011",
            "/slate/?sport=ncaaf&date=20261011",
            f"http://{host}:{port}/slate?sport=ncaaf&date=20261011",
        ):
            status, body = _http_request_target(host, port, target)
            assert status != 404, target
            assert b"File not found" not in body
            assert status == 200
            assert json.loads(body) == expected["ncaaf"]
        status, page = _http_get(host, port, "/slate.js")
        assert status == 200
        assert page.decode("utf-8") == marker
        status, page = _http_get(host, port, "/index.html")
        assert status == 200
        assert b"Multisport live win probability" in page
        def fail(_url: str) -> dict:
            raise FollowError("scoreboard failed")

        server.slate_fetch = fail
        status, _content_type, _cache, failed = _http_get_meta(
            host, port, "/slate?sport=nfl&date=20260920"
        )
        assert status == 502
        assert b"Bad Gateway" in failed
        server.slate_fetch = server_reader
        status, _content_type, _cache, body = _http_get_meta(
            host, port, "/slate?sport=nhl&date=20260920"
        )
        assert status == 200
        assert json.loads(body) == expected["nhl"]
        status, posted = _http_post(
            host, port, "/follow", b'{"sport":"nfl","game_id":"55"}'
        )
        assert status == 204
        assert posted == b""
        assert (root / "slate.js").read_text(encoding="utf-8") == marker
        assert not (root / "slate.js.tmp").exists()
        names = sorted(path.name for path in root.iterdir())
        assert "slate.js.tmp" not in names
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()
    assert not thread.is_alive()
    assert _real_slate_bytes() == real_before


def test_cli_serve_reaches_get_slate_before_the_file_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """python -m live_wp serve must answer /slate, not a missing file."""

    def blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("slate route opened a network request")

    monkeypatch.setattr("live_wp.follow.urllib.request.urlopen", blocked)
    assert _request_path("/slate?sport=ncaaf&date=20261011") == "/slate"
    assert _request_path("/slate/?sport=ncaaf&date=20261011") == "/slate"
    assert (
        _request_path("http://127.0.0.1:8765/slate?sport=ncaaf&date=20261011")
        == "/slate"
    )
    source = inspect.getsource(_Handler.do_GET)
    assert source.index('"/slate"') < source.index("super().do_GET")
    assert source.index('"/replay"') < source.index("super().do_GET")
    board = _feed_board(
        "ncaaf",
        [
            _feed_event(
                "ncaaf",
                "88001",
                home="TEX",
                away="OU",
                home_score="21",
                away_score="14",
                state="post",
                period=4,
                clock="0:00",
            )
        ],
    )
    fetch = _SlateFetch({"ncaaf": board}, {})
    ready = threading.Event()
    box: dict[str, object] = {}

    def on_ready(server: object) -> None:
        server.slate_fetch = fetch  # type: ignore[attr-defined]
        box["server"] = server
        ready.set()

    def runner() -> None:
        box["code"] = run_serve(["--port", "0"], on_ready=on_ready)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    assert ready.wait(5)
    server = box["server"]
    assert server.RequestHandlerClass.func is _Handler  # type: ignore[attr-defined]
    host, port = server.server_address[:2]  # type: ignore[attr-defined]
    try:
        status, body = _http_request_target(
            host, port, "/slate?sport=ncaaf&date=20261011"
        )
        assert status != 404
        assert b"File not found" not in body
        assert status == 200
        rows = json.loads(body)
        assert rows[0]["sport"] == "ncaaf"
        assert rows[0]["game_id"] == "88001"
        assert fetch.urls == [scoreboard_url("20261011", sport="ncaaf")]
    finally:
        server.shutdown()  # type: ignore[attr-defined]
        thread.join(5)
        server.server_close()  # type: ignore[attr-defined]
    assert not thread.is_alive()


def test_follow_route_accepts_only_a_loopback_host() -> None:
    assert _request_from_localhost("127.0.0.1", "127.0.0.1:8765")
    assert _request_from_localhost("127.0.0.1", "localhost:8765")
    assert _request_from_localhost("::1", "[::1]:8765")
    assert not _request_from_localhost("127.0.0.1", "example.com")
    assert not _request_from_localhost("10.0.0.8", "127.0.0.1:8765")
    assert not _request_from_localhost("127.0.0.1", "")


def test_serve_defaults_to_8765_and_rejects_a_bad_port(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert parse_serve_args([]) == 8765
    assert parse_serve_args(["--port", "9001"]) == 9001
    source = (ROOT / "src" / "live_wp" / "serve.py").read_text(encoding="utf-8")
    assert "compute_wp" not in source
    assert "urlopen" not in source
    assert "urllib" not in source
    assert "espn" not in source.lower()
    assert '"/slate"' in source
    assert '"/replay"' in source
    assert main(["serve", "--port", "70000"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "port" in captured.err


def test_page_points_at_the_local_replay_and_does_not_fetch() -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    lowered = html.lower()
    assert 'src="live_replay.js"' not in html
    assert "live_replay.js" not in lowered
    assert "fetch(" not in lowered
    assert "espn" not in lowered
    assert "http://" not in lowered and "https://" not in lowered
    assert 'src="manifest.js"' in html
    assert 'src="colors.js"' in html
    assert 'src="app.js"' in html
    script = (ROOT / "app.js").read_text(encoding="utf-8")
    assert script.count("fetch(") == 6
    assert 'fetch("/follow"' in script
    assert 'fetch("follow.json"' in script
    assert '"/slate?sport="' in script
    assert '"/replay?sport="' in script
    assert "replays/live_replay.js?" in script
    assert "127.0.0.1" in script
    assert "localhost" in script
    assert "MSWP_LIVE" in script
    assert "XMLHttpRequest" not in script
    assert "WebSocket" not in script
    assert "espn" not in script.lower()
    stub = (ROOT / "replays" / "live_replay.js").read_text(encoding="utf-8")
    assert "window." not in stub
    assert "fetch(" not in stub
    assert "espn" not in stub.lower()


def test_live_rejects_interval_4_and_sport_ncaaf(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _block_network(monkeypatch)
    out = tmp_path / "live_replay.js"
    assert main(["live", "--game", "55", "--interval", "4", "--out", str(out)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "at least 5" in captured.err
    assert not out.exists()

    assert main(["live", "--game", "55", "--sport", "ncaaf", "--out", str(out)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ncaaf" in captured.err.lower()
    assert "college football" in captured.err.lower()
    assert not out.exists()

    assert main(["live", "--interval", "4", "--out", str(out)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "at least 5" in captured.err
    assert not out.exists()

    assert main(["live", "--sport", "ncaaf", "--out", str(out)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ncaaf" in captured.err.lower()
    assert not out.exists()

    for sport, label in (
        ("ncaah", "college hockey"),
        ("ncaab", "college basketball"),
    ):
        code = main(["live", "--sport", sport, "--game", "55", "--out", str(out)])
        refused = capsys.readouterr()
        assert code == 2
        assert refused.out == ""
        assert label in refused.err.lower()
        assert not out.exists()


def test_fake_follow_payload_rewrites_the_replay_without_a_socket(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _block_network(monkeypatch)
    first = _live_event()
    same = deepcopy(first)
    same["winprobability"] = [{"homeWinPercentage": 0.11}]
    final = deepcopy(first)
    _clock(final, "0:00", period=4, state="post")
    _score(final, 14, 10)
    fetch = _Fetch([_pack(event) for event in (first, same, final)])
    out = tmp_path / "nested" / "live_replay.js"
    seen: list[str] = []

    def sleep(_seconds: float) -> None:
        seen.append(out.read_text(encoding="utf-8"))

    code = run_live(
        ["--game", "55", "--out", str(out)],
        fetch=fetch,
        sleep=sleep,
    )
    captured = capsys.readouterr()
    frozen = None
    expected = []
    for event in (first, final):
        state, frozen = _with_frozen_prior(event, frozen, "nfl")
        expected.append(state)
    assert code == 0
    assert captured.err == ""
    assert fetch.urls == [scoreboard_url()] * 3
    assert seen[0] == seen[1] == render_widget_script([expected[0]], live=True)
    text = out.read_text(encoding="utf-8")
    assert "\r" not in text
    assert text == render_widget_script(expected, live=True)
    assert "window.NFL_REPLAY = " in text
    assert "window.MSWP_LIVE = window.NFL_REPLAY;" in text
    assert '"sport": "nfl"' in text
    plain = render_widget_script(expected)
    assert "window.MSWP_LIVE" not in plain
    assert '"sport":' not in plain
    assert "espn" not in text.lower()
    assert "http://" not in text and "https://" not in text
    assert not out.with_name(out.name + ".tmp").exists()
    lines = [
        format_line(
            state, compute_wp(state, state.prior_home, config_for_state(state))
        )
        for state in expected
    ]
    assert captured.out.splitlines() == lines
    assert captured.out.splitlines()[-1].endswith("| 1.000")
    assert "0.110" not in captured.out


def test_ctrl_c_stops_and_leaves_the_last_replay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _block_network(monkeypatch)
    out = tmp_path / "live_replay.js"
    previous = "// previous\n"
    out.write_text(previous, encoding="utf-8", newline="\n")

    def fetch(_url: str) -> dict:
        raise KeyboardInterrupt

    assert run_live(["--game", "55", "--out", str(out)], fetch=fetch, sleep=lambda _s: None) == 0
    assert out.read_text(encoding="utf-8") == previous

    def sleep(_seconds: float) -> None:
        raise KeyboardInterrupt

    assert (
        run_live(
            ["--game", "55", "--out", str(out)],
            fetch=lambda _url: _pack(_live_event()),
            sleep=sleep,
        )
        == 0
    )
    text = out.read_text(encoding="utf-8")
    assert text != previous
    assert "window.NFL_REPLAY = " in text
    assert not out.with_name(out.name + ".tmp").exists()


def test_live_default_out_is_the_live_replay() -> None:
    options = parse_live_args(["--game", "55"])
    assert options.out == DEFAULT_OUT
    assert options.out.name == "live_replay.js"
    assert options.out == ROOT / "replays" / "live_replay.js"
    assert options.interval == 15.0
    assert options.sport == "nfl"
    assert options.game == "55"
    watched = parse_live_args([])
    assert watched.game is None
    assert watched.out == DEFAULT_OUT
    assert watched.interval == 15.0
    assert DEFAULT_FOLLOW == ROOT / "follow.json"


def _with_id(event: dict, game_id: str) -> dict:
    cloned = deepcopy(event)
    cloned["id"] = game_id
    cloned["uid"] = "s:20~l:28~e:" + game_id
    competition = cloned["competitions"][0]
    competition["id"] = game_id
    competition["uid"] = cloned["uid"]
    return cloned


def test_game_flag_ignores_follow_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _block_network(monkeypatch)
    follow = tmp_path / "follow.json"
    follow.write_text(_selection("nba", "77"), encoding="utf-8", newline="\n")
    original = follow.read_bytes()
    out = tmp_path / "live_replay.js"
    slate = tmp_path / "slate.js"
    marker = "previous slate\n"
    slate.write_text(marker, encoding="utf-8", newline="\n")
    real_before = _real_slate_bytes()
    urls: list[str] = []

    def fetch(url: str) -> dict:
        urls.append(url)
        return _pack(_live_event())

    def sleep(_seconds: float) -> None:
        raise KeyboardInterrupt

    code = run_live(
        ["--game", "55", "--out", str(out)],
        fetch=fetch,
        sleep=sleep,
        follow_path=follow,
        slate_path=slate,
    )
    assert code == 0
    assert urls == [scoreboard_url()]
    assert scoreboard_url(sport="nhl") not in urls
    assert scoreboard_url(sport="nba") not in urls
    _assert_no_college(urls)
    assert all("summary" not in url for url in urls)
    assert follow.read_bytes() == original
    assert slate.read_text(encoding="utf-8") == marker
    assert _real_slate_bytes() == real_before
    text = out.read_text(encoding="utf-8")
    assert '"game_id": "55"' in text
    assert '"game_id": "77"' not in text
    assert "nba" not in text


def test_live_without_game_writes_the_slate_then_switches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _block_network(monkeypatch)
    follow = tmp_path / "follow.json"
    out = tmp_path / "live_replay.js"
    slate = tmp_path / "slate.js"
    marker = "previous slate\n"
    slate.write_text(marker, encoding="utf-8", newline="\n")
    real_before = _real_slate_bytes()
    first = _live_event()
    second = _clock(
        _score(_with_id(first, "77"), 21, 14),
        "1:00",
        period=4,
        state="in",
    )
    boards = {
        "nfl": _nfl_board_of([first, second]),
        "nhl": _pro_board(
            "nhl",
            [
                _pro_event(
                    "nhl",
                    "80",
                    home="COL",
                    away="MIN",
                    home_score="2",
                    away_score="1",
                    state="post",
                    period=3,
                    clock="0:00",
                )
            ],
        ),
        "nba": _pro_board(
            "nba",
            [
                _pro_event(
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
        ),
    }
    initial = _slate_script(boards)
    urls: list[str] = []
    nfl_slates: list[str] = []
    scripts: dict[str, str] = {}

    def fetch(url: str) -> dict:
        assert "summary" not in url
        assert "college" not in url.lower()
        if url == scoreboard_url(sport="nfl"):
            nfl_slates.append(slate.read_text(encoding="utf-8"))
        urls.append(url)
        for sport in ("nfl", "nhl", "nba"):
            root = scoreboard_url(sport=sport)
            if url == root or url.startswith(root + "?"):
                return deepcopy(boards[sport])
        raise AssertionError(url)

    def sleep(seconds: float) -> None:
        assert seconds == 15.0
        step = len(urls)
        if step == 3:
            assert not follow.exists()
            assert not out.exists()
            scripts["waiting"] = slate.read_text(encoding="utf-8")
            follow.write_text(_selection("nfl", "55"), encoding="utf-8", newline="\n")
            return
        if step == 7:
            scripts["first"] = out.read_text(encoding="utf-8")
            _score(boards["nhl"]["events"][0], 2, 9)
            follow.write_text(_selection("nfl", "77"), encoding="utf-8", newline="\n")
            return
        scripts["second"] = out.read_text(encoding="utf-8")
        scripts["slate"] = slate.read_text(encoding="utf-8")
        raise KeyboardInterrupt

    code = run_live(
        ["--out", str(out)],
        fetch=fetch,
        sleep=sleep,
        follow_path=follow,
        slate_path=slate,
    )
    captured = capsys.readouterr()
    updated = _slate_script(boards)
    state_55, _frozen = _with_frozen_prior(first, None, "nfl")
    state_77, _frozen = _with_frozen_prior(second, None, "nfl")
    cycle = _scoreboard_cycle()
    assert code == 0
    assert captured.err == ""
    assert urls == cycle + cycle + [scoreboard_url()] + cycle + [scoreboard_url()]
    _assert_no_college(urls)
    assert all("summary" not in url for url in urls)
    assert scripts["waiting"] == initial
    assert initial != marker
    assert "previous slate" not in initial
    assert "\r" not in initial
    assert nfl_slates == [marker, initial, initial, initial, updated]
    assert updated != initial
    assert '"away_score": 9' in updated
    assert '"away_score": 9' not in initial
    assert scripts["first"] == render_widget_script([state_55], live=True)
    assert scripts["second"] == render_widget_script([state_77], live=True)
    assert scripts["slate"] == updated
    assert out.read_text(encoding="utf-8") == scripts["second"]
    assert slate.read_text(encoding="utf-8") == updated
    assert '"game_id": "55"' not in scripts["second"]
    assert '"game_id": "77"' not in scripts["first"]
    assert "window.MSWP_SLATE" not in scripts["second"]
    assert not out.with_name(out.name + ".tmp").exists()
    assert not slate.with_name(slate.name + ".tmp").exists()
    assert _real_slate_bytes() == real_before
    lines = [
        format_line(
            state, compute_wp(state, state.prior_home, config_for_state(state))
        )
        for state in (state_55, state_77)
    ]
    assert captured.out.splitlines() == lines


def test_final_follow_keeps_rewriting_the_slate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _block_network(monkeypatch)
    follow = tmp_path / "follow.json"
    follow.write_text(_selection("nfl", "55"), encoding="utf-8", newline="\n")
    out = tmp_path / "live_replay.js"
    slate = tmp_path / "slate.js"
    final = _clock(_score(_live_event(), 14, 10), "0:00", period=4, state="post")
    boards = {
        "nfl": _nfl_board_of([final]),
        "nhl": _pro_board("nhl", []),
        "nba": _pro_board("nba", []),
    }
    urls: list[str] = []
    sleeps: list[float] = []

    def fetch(url: str) -> dict:
        assert "summary" not in url
        assert "college" not in url.lower()
        urls.append(url)
        for sport in ("nfl", "nhl", "nba"):
            root = scoreboard_url(sport=sport)
            if url == root or url.startswith(root + "?"):
                return deepcopy(boards[sport])
        raise AssertionError(url)

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise KeyboardInterrupt

    code = run_live(
        ["--out", str(out)],
        fetch=fetch,
        sleep=sleep,
        follow_path=follow,
        slate_path=slate,
    )
    assert code == 0
    assert sleeps == [15.0]
    cycle = _scoreboard_cycle()
    assert urls == cycle + [scoreboard_url()] + cycle
    _assert_no_college(urls)
    text = slate.read_text(encoding="utf-8")
    assert text == _slate_script(boards)
    assert "\r" not in text
    assert '"game_id": "55"' in text
    replay = out.read_text(encoding="utf-8")
    assert '"game_id": "55"' in replay
    assert "window.MSWP_LIVE" in replay
    assert not slate.with_name(slate.name + ".tmp").exists()


def test_follow_file_college_does_not_fetch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _block_network(monkeypatch)
    follow = tmp_path / "follow.json"
    follow.write_text(_selection("ncaaf", "55"), encoding="utf-8", newline="\n")
    out = tmp_path / "live_replay.js"
    slate = tmp_path / "slate.js"

    def fetch(_url: str) -> dict:
        raise AssertionError("college file was fetched")

    def sleep(_seconds: float) -> None:
        raise AssertionError("college file waited")

    code = run_live(
        ["--out", str(out)],
        fetch=fetch,
        sleep=sleep,
        follow_path=follow,
        slate_path=slate,
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "ncaaf" in captured.err.lower()
    assert "college football" in captured.err.lower()
    assert not out.exists()
    assert not slate.exists()


_REPLAY_SIDES = {
    "nfl": ("JAX", "DEN"),
    "nhl": ("MIN", "COL"),
    "nba": ("BOS", "NYK"),
    "ncaaf": ("COLO", "GT"),
    "ncaah": ("MICH", "DEN"),
    "ncaab": ("COLO", "FLA"),
}


def _replay_event(sport: str, event_id: str, state: str) -> dict:
    away, home = _REPLAY_SIDES[sport]
    return _feed_event(
        sport,
        event_id,
        home=home,
        away=away,
        home_score="0" if state == "pre" else "20",
        away_score="0" if state == "pre" else "13",
        state=state,
        period=1 if state == "pre" else 4,
        clock="15:00" if state == "pre" else "0:00",
        moneyline=-150,
    )


def _replay_fetch(sport: str, event: dict, summary: dict | None = None):
    urls: list[str] = []

    def fetch(url: str) -> dict:
        urls.append(url)
        if "summary?" in url:
            if summary is None:
                raise FollowError("summary has no snapshots")
            return summary
        return _feed_board(sport, [event])

    return urls, fetch


def test_replay_script_charts_started_games_for_every_sport() -> None:
    summary = json.loads(
        (ROOT / "tests" / "fixtures" / "espn_nfl_summary_snippet.json").read_text(
            encoding="utf-8"
        )
    )
    urls, fetch = _replay_fetch(
        "nfl", _replay_event("nfl", "9001001", "post"), summary
    )
    script = replay_script("nfl", "9001001", date="20260920", fetch=fetch)
    assert script is not None
    assert "\r" not in script
    assert "window.MSWP_LIVE" in script
    assert script.count('"win_prob"') > 1
    assert '"game_id": "9001001"' in script
    assert urls == [
        scoreboard_url("20260920", sport="nfl"),
        summary_url("9001001", sport="nfl"),
    ]

    for sport in _REPLAY_SIDES:
        called, getter = _replay_fetch(sport, _replay_event(sport, "55", "post"))
        rendered = replay_script(sport, "55", date="20260920", fetch=getter)
        assert rendered is not None
        assert "window.MSWP_LIVE" in rendered
        assert f'"sport": "{sport}"' in rendered
        away, home = _REPLAY_SIDES[sport]
        assert f'"away": "{away}"' in rendered
        assert f'"home": "{home}"' in rendered
        assert called[0] == scoreboard_url("20260920", sport=sport)
        assert summary_url("55", sport=sport) in called


def test_replay_script_skips_a_pre_game_and_a_feed_failure() -> None:
    urls, fetch = _replay_fetch("ncaaf", _replay_event("ncaaf", "880", "pre"))
    assert replay_script("ncaaf", "880", date="20260920", fetch=fetch) is None
    assert urls == [scoreboard_url("20260920", sport="ncaaf")]

    def down(_url: str) -> dict:
        raise FollowError("scoreboard unavailable")

    assert replay_script("nba", "55", date="20260920", fetch=down) is None


def test_get_replay_returns_a_temporary_script_or_no_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("replay route opened a network request")

    monkeypatch.setattr("live_wp.follow.urllib.request.urlopen", blocked)
    summary = json.loads(
        (ROOT / "tests" / "fixtures" / "espn_nfl_summary_snippet.json").read_text(
            encoding="utf-8"
        )
    )
    urls, fetch = _replay_fetch(
        "nfl", _replay_event("nfl", "9001001", "post"), summary
    )
    index = tmp_path / "index.html"
    index.write_text("<!DOCTYPE html><title>page</title>\n", encoding="utf-8", newline="\n")
    server = bind_widget_server(0, directory=tmp_path)
    server.replay_fetch = fetch  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        status, content_type, cache, body = _http_get_meta(
            host, port, "/replay?sport=nfl&game_id=9001001&date=20260920"
        )
        assert status == 200
        assert content_type.startswith("text/javascript")
        assert cache == "no-store"
        script = body.decode("utf-8")
        assert "\r" not in script
        assert "window.MSWP_LIVE" in script
        assert script.count('"win_prob"') > 1
        assert not (tmp_path / "follow.json").exists()
        assert not (tmp_path / "replays" / "live_replay.js").exists()
        assert urls == [
            scoreboard_url("20260920", sport="nfl"),
            summary_url("9001001", sport="nfl"),
        ]

        pre_urls, pre_fetch = _replay_fetch("nhl", _replay_event("nhl", "77", "pre"))
        server.replay_fetch = pre_fetch  # type: ignore[attr-defined]
        status, content_type, _cache, body = _http_get_meta(
            host, port, "/replay?sport=nhl&game_id=77&date=20260920"
        )
        assert status == 204
        assert body == b""
        assert pre_urls == [scoreboard_url("20260920", sport="nhl")]

        quiet: list[str] = []

        def refuse(url: str) -> dict:
            quiet.append(url)
            raise AssertionError(url)

        server.replay_fetch = refuse  # type: ignore[attr-defined]
        for path in (
            "/replay?sport=mlb&game_id=55&date=20260920",
            "/replay?sport=ncaab&game_id=abc&date=20260920",
            "/replay?sport=ncaah&date=20260920",
            "/replay?sport=nba&game_id=55&date=2026-09-20",
            "/replay?sport=nfl&game_id=55&date=20260230",
        ):
            status, _body = _http_get(host, port, path)
            assert status == 400
        assert quiet == []
        status, _body = _http_get_meta(
            host,
            port,
            "/replay?sport=ncaaf&game_id=880&date=20260920",
            host_header="example.com",
        )[:2]
        assert status == 403
        assert quiet == []
        college_urls, college_fetch = _replay_fetch(
            "ncaaf", _replay_event("ncaaf", "880", "post")
        )
        server.replay_fetch = college_fetch  # type: ignore[attr-defined]
        status, body = _http_request_target(
            host,
            port,
            f"http://{host}:{port}/replay?sport=ncaaf&game_id=880&date=20260920",
        )
        assert status == 200
        assert b"window.MSWP_LIVE" in body
        assert b'"sport": "ncaaf"' in body
        assert college_urls[0] == scoreboard_url("20260920", sport="ncaaf")
        names = sorted(path.name for path in tmp_path.iterdir())
        assert names == ["index.html"]
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()
    assert not thread.is_alive()
