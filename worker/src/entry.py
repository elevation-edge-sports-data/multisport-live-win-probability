"""Cloudflare Worker for the dated slate and replay routes.

GET /slate and GET /replay call the same helpers as the local page server.
ESPN is read with the Workers fetch API. urllib cannot complete that
connection inside the isolate. Every response allows any origin. Any
other path is 404. A handler error is 502.
"""

import json
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from js import Object
from js import fetch as js_fetch
from pyodide.ffi import run_sync, to_js

from club_colors import CLUB_COLOR_FILES
from live_win_prob import colors as club_colors
from live_win_prob.live import replay_script
from live_win_prob.slate import slate_rows
from workers import Response, WorkerEntrypoint

# Browser-like headers on every ESPN request, scoreboard and summary.
_ESPN_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Present on every response, including errors and the preflight.
_CORS = {"Access-Control-Allow-Origin": "*"}
_PREFLIGHT = {
    **_CORS,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}


def _response(body=None, status=200, content_type=None):
    """Build a response that browsers on another origin can read."""
    headers = dict(_CORS)
    if content_type:
        headers["Content-Type"] = content_type
    return Response(body, status=status, headers=headers)


def _path(url: str) -> str:
    """Route path without the query. A trailing slash does not change it."""
    path = urlparse(url).path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    return path or "/"


def _query(url: str) -> dict[str, str]:
    """Last value of each query key. ``+`` is a space."""
    parsed = parse_qs(urlparse(url).query, keep_blank_values=True)
    return {key: values[-1].strip() for key, values in parsed.items()}


def _day(text: str) -> str:
    """YYYYMMDD, or ValueError before either helper fetches."""
    if len(text) != 8 or not text.isdigit():
        raise ValueError("date must be YYYYMMDD")
    datetime.strptime(text, "%Y%m%d")
    return text


async def fetch_espn(url: str) -> dict:
    """GET one ESPN URL with the Workers fetch API and return a JSON object."""
    # A Python dict as headers= crashes the isolate. Fetch wants a JS options object.
    response = await js_fetch(
        url,
        to_js({"headers": _ESPN_HEADERS}, dict_converter=Object.fromEntries),
    )
    status = int(response.status)
    if status < 200 or status >= 300:
        raise RuntimeError(f"ESPN request failed: HTTP {status} {url}")
    text = await response.text()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ESPN response was not JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("ESPN response was not a JSON object")
    return payload


def _espn_fetch(url: str) -> dict:
    """Sync fetch(url) for slate_rows and replay_script."""
    return run_sync(fetch_espn(url))


def _install_colors() -> None:
    """Fill the palette cache. The isolate cannot read assets/colors."""
    if club_colors._CLUBS is not None:
        return
    loaded: dict[str, list[dict[str, object]]] = {}
    for name, text in CLUB_COLOR_FILES.items():
        sport = name.removesuffix(".json")
        payload = json.loads(text)
        rows: list[dict[str, object]] = []
        if isinstance(payload, list):
            for row in payload:
                if isinstance(row, dict):
                    club = club_colors._normalize(row, sport)
                    if club is not None:
                        rows.append(club)
        loaded[sport] = rows
    club_colors._CLUBS = loaded


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        # Preflight is not a route. Answer it before the path check.
        if request.method == "OPTIONS":
            return Response(None, status=204, headers=_PREFLIGHT)
        try:
            if request.method != "GET":
                return _response("Not Found", status=404)
            url = str(request.url)
            path = _path(url)
            if path == "/slate":
                return self._slate(url)
            if path == "/replay":
                return self._replay(url)
            return _response("Not Found", status=404)
        except Exception as exc:
            # Debug body: the status stays 502, and the text is the failure.
            cause = exc.__cause__
            detail = f"{type(exc).__name__}: {exc}"
            if cause is not None:
                detail += f" | cause {type(cause).__name__}: {cause}"
            return _response(detail, status=502)

    def _slate(self, url: str) -> Response:
        """JSON rows for one sport and day."""
        params = _query(url)
        rows = slate_rows(
            date=_day(params.get("date", "")),
            sport=params.get("sport", "").lower(),
            fetch=_espn_fetch,
        )
        return Response.json(rows, headers=_CORS)

    def _replay(self, url: str) -> Response:
        """JavaScript replay, or 204 when the game has no snapshots."""
        _install_colors()
        params = _query(url)
        script = replay_script(
            params.get("sport", ""),
            params.get("game_id", ""),
            date=_day(params.get("date", "")),
            fetch=_espn_fetch,
        )
        if not script:
            return _response(None, status=204)
        return _response(script, content_type="text/javascript; charset=utf-8")
