"""Local widget server and the live replay writer.

Serve tests bind 127.0.0.1 and then stop the server. Every other test
in this module blocks sockets. None of them call ESPN.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from copy import deepcopy
from pathlib import Path

import pytest

from mswp import compute_wp

from live_wp.__main__ import main
from live_wp.follow import _with_frozen_prior, scoreboard_url
from live_wp.live import DEFAULT_OUT, parse_live_args, run_live
from live_wp.replay import config_for_state, format_line, render_widget_script
from live_wp.serve import bind_widget_server, parse_serve_args, run_serve

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
    """One local widget server. Leaving the block always stops it."""

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
        assert b"live_replay.js" not in body
        assert b"espn" not in body.lower()
        live_status, live_body = _get(host, port, "/live_replay.js")
        assert live_status == 200
        assert b"window." not in live_body
        bust_status, bust_body = _get(host, port, "/live_replay.js?t=1")
        assert bust_status == 200
        assert bust_body == live_body
        css_status, css = _get(host, port, "/widget.css")
        assert css_status == 200
        assert b"text-align: right" in css
        missing, missing_body = _get(
            host, port, "/apis/site/v2/sports/football/nfl/scoreboard"
        )
        assert missing == 404
        assert b"events" not in missing_body
        _escape_status, escape_body = _get(host, port, "/../pyproject.toml")
        assert b"setuptools" not in escape_body
        assert b"[project]" not in escape_body
    assert running.thread is not None
    assert not running.thread.is_alive()
    assert running.code == 0
    with pytest.raises(OSError):
        connection = socket.create_connection((host, port), timeout=1)
        connection.close()


def test_local_http_get_returns_the_widget_then_stops() -> None:
    with _Running() as running:
        server = running.server
        host, port = server.server_address[:2]  # type: ignore[attr-defined]
        for path in ("/", "/index.html"):
            status, body = _http_get(host, port, path)
            assert status == 200
            assert b"<!DOCTYPE html>" in body
            assert b"Multisport live win probability" in body
        missing, missing_body = _http_get(host, port, "/no-such-widget-file")
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
    assert main(["serve", "--port", "70000"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "port" in captured.err


def test_page_points_at_the_local_replay_and_does_not_fetch() -> None:
    html = (ROOT / "widget" / "index.html").read_text(encoding="utf-8")
    lowered = html.lower()
    assert 'src="live_replay.js"' not in html
    assert "live_replay.js" not in lowered
    assert "fetch(" not in lowered
    assert "espn" not in lowered
    assert "http://" not in lowered and "https://" not in lowered
    script = (ROOT / "widget" / "widget.js").read_text(encoding="utf-8")
    assert script.count("fetch(") == 1
    assert "live_replay.js?" in script
    assert "127.0.0.1" in script
    assert "localhost" in script
    assert "MSWP_LIVE" in script
    assert "XMLHttpRequest" not in script
    assert "WebSocket" not in script
    assert "espn" not in script.lower()
    stub = (ROOT / "widget" / "live_replay.js").read_text(encoding="utf-8")
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


def test_live_default_out_is_the_widget_replay() -> None:
    options = parse_live_args(["--game", "55"])
    assert options.out == DEFAULT_OUT
    assert options.out.name == "live_replay.js"
    assert options.out.parent.name == "widget"
    assert options.interval == 15.0
    assert options.sport == "nfl"
