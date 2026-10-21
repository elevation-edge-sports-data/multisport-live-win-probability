# Unofficial ESPN site data, used only to build local calibration files.
# Not for redistribution. Not affiliated with the NCAA, NFL, NHL, or NBA.

"""Pull completed college games into ``data/calibration/{sport}/``.

Each file is a scoring-density replay list. A home American moneyline wins.
When that line is absent, a college game is written from the earliest
``winprobability`` row with ``prior_source`` ``espn_win_probability``.
That value is ESPN's model at the first play, not a market close. A game
with neither source is not written and is not treated as collected.
College sports do not use the Elo snapshot.

Scoreboard group ids are not stored in this package. Confirm them on the
first dry-run (league id and event count). Defaults: NCAAF ``80`` (FBS;
FCS is ``--group 81``), NCAAB ``50`` (Division I), NCAAH omits ``groups``.
Default ``--limit`` is 1000 for NCAAF and NCAAB, and 400 for NCAAH.

First dry-runs::

    .\\.venv\\Scripts\\python.exe scripts\\collect_college_calibration.py --sport ncaaf --start 20250830 --end 20250901 --dry-run
    .\\.venv\\Scripts\\python.exe scripts\\collect_college_calibration.py --sport ncaah --start 20251003 --end 20251005 --dry-run
    .\\.venv\\Scripts\\python.exe scripts\\collect_college_calibration.py --sport ncaab --start 20251103 --end 20251105 --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
_SCRIPTS = Path(__file__).resolve().parent
for _entry in (_SRC, _SCRIPTS):
    _text = str(_entry)
    if _text not in sys.path:
        sys.path.insert(0, _text)

from collect_calibration import (  # noqa: E402
    _completed_events,
    _event_id,
    _existing_game_ids,
    _file_token,
    _inclusive_days,
    _reject_placeholder,
    _restamp_basketball,
    _write_replay,
)
from live_win_prob.feeds.espn import (  # noqa: E402
    home_moneyline_prior,
    require_ncaaf_payload,
    require_ncaah_payload,
    states_from_espn,
)
from live_win_prob.feeds.espn_basketball import (  # noqa: E402
    events_from_espn_basketball,
    require_ncaab_payload,
)
from live_win_prob.follow import (  # noqa: E402
    FollowError,
    _root,
    fetch_json,
    summary_url,
)
from ms_win_prob import GameState  # noqa: E402

_SPORTS = ("ncaaf", "ncaah", "ncaab")
# Public scoreboard groups. Confirm on the first dry-run before a season pull.
_DEFAULT_GROUPS: dict[str, str | None] = {
    "ncaaf": "80",
    "ncaah": None,
    "ncaab": "50",
}
_DEFAULT_LIMITS = {"ncaaf": 1000, "ncaah": 400, "ncaab": 1000}
_DENSITY = "scoring"
_SUMMARY_PAUSE_SECONDS = 0.25
_RETRY_STATUSES = (429, 503)
_RETRY_ATTEMPTS = 4
_RETRY_BACKOFF_SECONDS = 1.0

_DRY_RUNS = """\
  .\\.venv\\Scripts\\python.exe scripts\\collect_college_calibration.py --sport ncaaf --start 20250830 --end 20250901 --dry-run
  .\\.venv\\Scripts\\python.exe scripts\\collect_college_calibration.py --sport ncaah --start 20251003 --end 20251005 --dry-run
  .\\.venv\\Scripts\\python.exe scripts\\collect_college_calibration.py --sport ncaab --start 20251103 --end 20251105 --dry-run"""


class _NoPrior(Exception):
    """The summary has neither a moneyline nor a usable opening win probability."""


def college_scoreboard_url(
    sport: str,
    date: str,
    *,
    group: str | None,
    limit: int,
) -> str:
    """Scoreboard URL on the sport root, with ``dates``, ``limit``, and optional ``groups``."""
    pairs = [("dates", date), ("limit", str(limit))]
    if group:
        pairs.append(("groups", group))
    return _root(sport) + "scoreboard?" + urlencode(pairs)


def states_for_college_summary(
    summary: Mapping[str, Any],
    sport: str,
    density: str = _DENSITY,
) -> list[GameState]:
    """Map one college summary the way the pro calibration files were built.

    NCAAB uses the basketball adapter, then replaces the ``2024-04-01``
    ``as_of`` placeholder with each play's wallclock. NCAAF and NCAAH stay
    on ``states_from_espn``, which already stores play wallclocks.
    """
    if sport == "ncaab":
        require_ncaab_payload(summary)
        return _restamp_basketball(
            summary,
            events_from_espn_basketball(summary, density=density),
        )
    if sport == "ncaaf":
        require_ncaaf_payload(summary)
    elif sport == "ncaah":
        require_ncaah_payload(summary)
    else:
        raise ValueError(sport)
    return states_from_espn(summary, density=density)


def worth_writing(summary: Mapping[str, Any], states: list[GameState]) -> bool:
    """True when the summary line landed on every snapshot."""
    if home_moneyline_prior(summary) is None:
        return False
    return bool(states) and all(state.prior_source == "moneyline" for state in states)


def opening_espn_win_probability(summary: Mapping[str, Any]) -> float | None:
    """Earliest ``homeWinPercentage``, or None when the list is missing or unusable.

    College summaries from the site API have no American moneyline. This is
    ESPN's model at the first play, not a market close. The earliest row is
    the lowest ``playId``, which matched list order on the sampled games.
    A value of 0 or 1 is refused: the model only accepts a prior in (0, 1).
    NCAAH summaries with no list return None, and the caller does not invent 0.5.
    """
    rows = summary.get("winprobability")
    if not isinstance(rows, list) or not rows:
        return None
    chosen: tuple[str, int, float] | None = None
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        value = row.get("homeWinPercentage")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        play_id = row.get("playId")
        key = "" if play_id is None else str(play_id)
        if chosen is None or (key, index) < (chosen[0], chosen[1]):
            chosen = (key, index, float(value))
    if chosen is None or not 0.0 < chosen[2] < 1.0:
        return None
    return chosen[2]


def main(argv: list[str] | None = None) -> int:
    """Walk the date range and write one JSON file per new moneyline game."""
    args = _parse_args(argv)
    try:
        days = _inclusive_days(args.start, args.end)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    group = _DEFAULT_GROUPS[args.sport] if args.group is None else (args.group or None)
    limit = _DEFAULT_LIMITS[args.sport] if args.limit is None else args.limit
    destination = _ROOT / "data" / "calibration" / args.sport
    sidecar = _sidecar_path(args.sport)
    skip_ids = _existing_game_ids(destination) | _load_sidecar(sidecar)
    failures = 0
    for day in days:
        url = college_scoreboard_url(args.sport, day, group=group, limit=limit)
        try:
            board = _fetch_with_retry(url, args.sport)
        except (FollowError, ValueError, OSError) as exc:
            print(f"{day} scoreboard failed: {exc}", file=sys.stderr)
            failures += 1
            continue
        chosen = [
            event
            for event in _completed_events(board)
            if (game_id := _event_id(event)) is not None and game_id not in skip_ids
        ]
        if args.dry_run:
            if not chosen:
                print(day)
            for event in chosen:
                print(f"{day} {_event_id(event)}")
            continue
        for index, event in enumerate(chosen):
            if index:
                time.sleep(_SUMMARY_PAUSE_SECONDS)
            game_id = _event_id(event)
            assert game_id is not None
            try:
                path, count = _collect_game(
                    args.sport,
                    game_id,
                    destination,
                )
            except _NoPrior:
                print(f"{day} {game_id} no prior")
                continue
            except (FollowError, ValueError, TypeError, OSError) as exc:
                print(f"{day} {game_id} failed: {exc}", file=sys.stderr)
                failures += 1
                continue
            skip_ids.add(game_id)
            print(
                f"{day} {game_id} wrote {path.relative_to(_ROOT).as_posix()} "
                f"snapshots={count}"
            )
    return 1 if failures else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download completed ESPN college games into data/calibration/{sport}/. "
            "Unofficial ESPN data. Not for redistribution."
        ),
        epilog="First dry-runs:\n" + _DRY_RUNS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--sport", required=True, choices=_SPORTS)
    parser.add_argument("--start", required=True, type=_ymd, help="YYYYMMDD, inclusive")
    parser.add_argument("--end", required=True, type=_ymd, help="YYYYMMDD, inclusive")
    parser.add_argument(
        "--group",
        default=None,
        help=(
            "ESPN scoreboard groups value. "
            "Default: 80 for ncaaf, 50 for ncaab, omitted for ncaah. "
            "Pass an empty string to omit groups."
        ),
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        help="Scoreboard limit. Default: 1000 for ncaaf and ncaab, 400 for ncaah.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print dates and new game ids; write nothing",
    )
    return parser.parse_args(argv)


def _ymd(text: str) -> str:
    from datetime import datetime

    try:
        parsed = datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYYMMDD") from exc
    return parsed.strftime("%Y%m%d")


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be an integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("limit must be >= 1")
    return value


def _sidecar_path(sport: str) -> Path:
    return _ROOT / "artifacts" / f"college_no_moneyline_{sport}.txt"


def _load_sidecar(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    found: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        token = line.strip()
        if token.isdigit():
            found.add(token)
    return found


def _append_sidecar(path: Path, game_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(game_id + "\n")


def _collect_game(
    sport: str,
    game_id: str,
    destination: Path,
) -> tuple[Path, int]:
    summary = _fetch_with_retry(summary_url(game_id, sport=sport), sport)
    states = states_for_college_summary(summary, sport)
    if not states:
        raise ValueError("summary produced no snapshots")
    _reject_placeholder(states)
    if not worth_writing(summary, states):
        if home_moneyline_prior(summary) is not None:
            raise ValueError("summary moneyline did not land on every snapshot")
        opened = opening_espn_win_probability(summary)
        if opened is None:
            raise _NoPrior()
        states = [
            replace(state, prior_home=opened, prior_source="espn_win_probability")
            for state in states
        ]
    path = destination / (
        f"{game_id}_{_file_token(states[0].away)}_at_{_file_token(states[0].home)}.json"
    )
    _write_replay(path, states)
    return path, len(states)


def _fetch_with_retry(url: str, sport: str) -> Any:
    """GET one ESPN URL. Retry HTTP 429 and 503 with exponential backoff."""
    delay = _RETRY_BACKOFF_SECONDS
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return fetch_json(url, sport=sport)
        except FollowError as exc:
            status = _http_status(exc)
            if status not in _RETRY_STATUSES or attempt + 1 == _RETRY_ATTEMPTS:
                raise
            time.sleep(delay)
            delay *= 2
    raise FollowError("ESPN request failed")


def _http_status(exc: FollowError) -> int | None:
    marker = "HTTP "
    text = str(exc)
    if marker not in text:
        return None
    tail = text.rsplit(marker, 1)[1].strip()
    digits: list[str] = []
    for character in tail:
        if not character.isdigit():
            break
        digits.append(character)
    if not digits:
        return None
    return int("".join(digits))


if __name__ == "__main__":
    raise SystemExit(main())
