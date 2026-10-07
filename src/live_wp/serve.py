"""Serve the static widget on 127.0.0.1.

The process reads files from the widget directory. It does not estimate
win probability and it does not forward a request anywhere else. The page
loads a replay script that render-widget already wrote.
"""

from __future__ import annotations

import sys
import traceback
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

WIDGET_DIR = Path(__file__).resolve().parents[2] / "widget"
DEFAULT_PORT = 8765
_HOST = "127.0.0.1"


class UsageError(Exception):
    """The serve command line itself is wrong."""


class _Handler(SimpleHTTPRequestHandler):
    """Files under the widget directory. No access log and no proxy."""

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_response_only(self, code: int, message: str | None = None) -> None:
        self._started = True
        super().send_response_only(code, message)

    def handle(self) -> None:
        try:
            super().handle()
        except Exception:
            self._fail()

    def _fail(self) -> None:
        """Print the handler error and answer 500 if no status was sent."""
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        self.close_connection = True
        if getattr(self, "_started", False):
            return
        try:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Internal Server Error")
        except Exception:
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()


class _Server(ThreadingHTTPServer):
    # HTTPServer turns address reuse on. On Windows that shares the port,
    # and the client sees a reset instead of this process.
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self) -> None:
        self.allow_reuse_address = False
        super().server_bind()


def bind_widget_server(
    port: int = DEFAULT_PORT, *, directory: Path | None = None
) -> _Server:
    """Bind 127.0.0.1 and the widget directory. The caller serves and stops."""
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("port must be an integer from 0 to 65535")
    root = WIDGET_DIR if directory is None else directory
    if not root.is_dir():
        raise FileNotFoundError(f"widget directory not found: {root}")
    handler = partial(_Handler, directory=str(root))
    return _Server((_HOST, port), handler)


def parse_serve_args(args: list[str]) -> int:
    """Read ``--port``. The default is 8765. The host is not a flag."""
    port: int | None = None
    index = 0
    tokens = list(args)
    while index < len(tokens):
        token = tokens[index]
        if token == "--port" or token.startswith("--port="):
            if port is not None:
                raise UsageError("--port was given twice")
            raw, index = _flag_value("--port", index, tokens)
            port = _parse_port(raw)
            continue
        raise UsageError(f"unrecognized argument: {token}")
    return DEFAULT_PORT if port is None else port


def run_serve(
    args: list[str],
    *,
    on_ready: Callable[[_Server], None] | None = None,
) -> int:
    """Bind localhost and serve until Ctrl+C or ``shutdown``."""
    try:
        port = parse_serve_args(args)
    except UsageError as exc:
        print(exc, file=sys.stderr)
        print("usage: python -m live_wp serve [--port 8765]", file=sys.stderr)
        return 2
    try:
        server = bind_widget_server(port)
    except OSError as exc:
        print(f"could not bind {_HOST}:{port}: {exc}", file=sys.stderr)
        return 1
    except (ValueError, FileNotFoundError) as exc:
        print(exc, file=sys.stderr)
        return 1
    host, bound = server.server_address[:2]
    print(f"Serving widget on {host} port {bound}", flush=True)
    announced = False
    original = server.service_actions

    def service_actions() -> None:
        nonlocal announced
        original()
        if on_ready is None or announced:
            return
        announced = True
        on_ready(server)

    server.service_actions = service_actions  # type: ignore[method-assign]
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def _flag_value(flag: str, index: int, tokens: list[str]) -> tuple[str, int]:
    token = tokens[index]
    prefix = flag + "="
    if token.startswith(prefix):
        value = token[len(prefix) :]
        if not value:
            raise UsageError(f"{flag} needs a value")
        return value, index + 1
    if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
        raise UsageError(f"{flag} needs a value")
    return tokens[index + 1], index + 2


def _parse_port(text: str) -> int:
    if not text.isdigit():
        raise UsageError("port must be an integer from 0 to 65535")
    value = int(text)
    if value > 65535:
        raise UsageError("port must be an integer from 0 to 65535")
    return value
