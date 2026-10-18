# Unofficial ESPN site data, used only to build local calibration files.
# Not for redistribution. Not affiliated with the NFL, NHL, or NBA.

"""Pull completed games into ``data/calibration/{sport}/``.

The scoreboard and summary readers live in ``live_win_prob.follow``. NFL and
NHL snapshots come from ``states_from_espn``. NBA summaries are refused by
that function, so they use the basketball summary path and then replace the
adapter's ``2024-04-01`` ``as_of`` placeholder with each play's wallclock.

Suggested regular-season windows are ``SEASON_WINDOWS``. Confirm the last
date still falls before the playoffs before copying one into ``--start``
and ``--end``.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from live_win_prob.feeds.espn import (  # noqa: E402
    DENSITIES,
    _parse_time,
    require_nfl_payload,
    require_nhl_payload,
    states_from_espn,
)
from live_win_prob.feeds.espn_basketball import (  # noqa: E402
    _basketball_plays,
    _parse_clock,
    _play_clock_display,
    _play_period_number,
    events_from_espn_basketball,
    require_nba_payload,
)
from live_win_prob.follow import (  # noqa: E402
    FollowError,
    fetch_json,
    scoreboard_url,
    summary_url,
)
from live_win_prob.replay import dump_replay  # noqa: E402
from ms_win_prob import GameState  # noqa: E402

# Copy into --start / --end. These are regular-season sketches.
# NFL 2025: Thursday 4 Sep 2025 through week 18 (4 Jan 2026).
# NBA 2025-26 and NHL 2025-26 run from opening week into mid-April.
SEASON_WINDOWS: dict[str, tuple[str, str]] = {
    "nfl": ("20250904", "20260104"),
    "nba": ("20251022", "20260412"),
    "nhl": ("20251007", "20260416"),
}

_SPORTS = ("nfl", "nba", "nhl")
_PLACEHOLDER = datetime(2024, 4, 1, tzinfo=timezone.utc)
_SKIPPED_STATUS = {
    "STATUS_POSTPONED",
    "STATUS_CANCELED",
    "STATUS_CANCELLED",
    "STATUS_SUSPENDED",
    "STATUS_DELAYED",
    "STATUS_FORFEIT",
}


def main(argv: list[str] | None = None) -> int:
    """Walk the date range and write one JSON file per new completed game."""
    args = _parse_args(argv)
    try:
        days = _inclusive_days(args.start, args.end)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    destination = _ROOT / "data" / "calibration" / args.sport
    known = _existing_game_ids(destination)
    failures = 0
    for day in days:
        try:
            board = fetch_json(scoreboard_url(day, sport=args.sport), sport=args.sport)
        except (FollowError, ValueError, OSError) as exc:
            print(f"{day} scoreboard failed: {exc}", file=sys.stderr)
            failures += 1
            continue
        chosen = [
            event
            for event in _completed_events(board)
            if (game_id := _event_id(event)) is not None and game_id not in known
        ]
        if args.dry_run:
            if not chosen:
                print(day)
            for event in chosen:
                print(f"{day} {_event_id(event)}")
            continue
        for event in chosen:
            game_id = _event_id(event)
            assert game_id is not None
            try:
                path, count = _collect_game(
                    args.sport,
                    game_id,
                    destination,
                    density=args.density,
                )
            except (FollowError, ValueError, OSError, TypeError) as exc:
                print(f"{day} {game_id} failed: {exc}", file=sys.stderr)
                failures += 1
                continue
            known.add(game_id)
            print(f"{day} {game_id} wrote {path.relative_to(_ROOT).as_posix()} snapshots={count}")
    return 1 if failures else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    windows = "\n".join(
        f"  {sport}  {start}  {end}    python scripts/collect_calibration.py "
        f"--sport {sport} --start {start} --end {end}"
        for sport, (start, end) in SEASON_WINDOWS.items()
    )
    parser = argparse.ArgumentParser(
        description=(
            "Download completed ESPN games into data/calibration/{sport}/. "
            "Unofficial ESPN data. Not for redistribution."
        ),
        epilog="Suggested regular-season windows:\n" + windows,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--sport", required=True, choices=_SPORTS)
    parser.add_argument("--start", required=True, type=_ymd, help="YYYYMMDD, inclusive")
    parser.add_argument("--end", required=True, type=_ymd, help="YYYYMMDD, inclusive")
    parser.add_argument("--density", default="scoring", choices=DENSITIES)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print dates and game ids that would be fetched; write nothing",
    )
    return parser.parse_args(argv)


def _ymd(text: str) -> str:
    try:
        parsed = datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYYMMDD") from exc
    return parsed.strftime("%Y%m%d")


def _inclusive_days(start: str, end: str) -> list[str]:
    first = datetime.strptime(start, "%Y%m%d")
    last = datetime.strptime(end, "%Y%m%d")
    if last < first:
        raise ValueError("end is before start")
    days: list[str] = []
    day = first
    while day <= last:
        days.append(day.strftime("%Y%m%d"))
        day += timedelta(days=1)
    return days


def _existing_game_ids(directory: Path) -> set[str]:
    found: set[str] = set()
    if not directory.is_dir():
        return found
    for path in directory.glob("*.json"):
        token = path.name.split("_", 1)[0]
        if token.isdigit():
            found.add(token)
    return found


def _completed_events(board: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = board.get("events")
    if not isinstance(raw, list):
        return []
    return [event for event in raw if isinstance(event, Mapping) and _is_completed(event)]


def _is_completed(event: Mapping[str, Any]) -> bool:
    kind = _status_type(event)
    name = str(kind.get("name") or "")
    if name in _SKIPPED_STATUS:
        return False
    if kind.get("completed") is True:
        return True
    return str(kind.get("state") or "").lower() == "post" and name.startswith("STATUS_FINAL")


def _status_type(event: Mapping[str, Any]) -> Mapping[str, Any]:
    competitions = event.get("competitions")
    if not isinstance(competitions, list) or not competitions:
        header = event.get("header")
        competitions = header.get("competitions") if isinstance(header, Mapping) else None
    if not isinstance(competitions, list) or not competitions:
        return {}
    competition = competitions[0]
    if not isinstance(competition, Mapping):
        return {}
    status = competition.get("status")
    if not isinstance(status, Mapping):
        return {}
    kind = status.get("type")
    return kind if isinstance(kind, Mapping) else {}


def _event_id(event: Mapping[str, Any]) -> str | None:
    raw = event.get("id")
    if raw is None:
        return None
    text = str(raw).strip()
    if text.isdigit():
        return text
    return None


def _collect_game(
    sport: str,
    game_id: str,
    destination: Path,
    *,
    density: str,
) -> tuple[Path, int]:
    summary = fetch_json(summary_url(game_id, sport=sport), sport=sport)
    states = _states_from_summary(summary, sport, density)
    if not states:
        raise ValueError("summary produced no snapshots")
    _reject_placeholder(states)
    away = _file_token(states[0].away)
    home = _file_token(states[0].home)
    path = destination / f"{game_id}_{away}_at_{home}.json"
    _write_replay(path, states)
    return path, len(states)


def _states_from_summary(
    summary: Mapping[str, Any],
    sport: str,
    density: str,
) -> list[GameState]:
    """Map one summary the same way the calibration files were built.

    NFL and NHL stay on ``states_from_espn``, which already stores play
    wallclocks. NBA uses the basketball summary adapter, whose ``as_of``
    is the ``2024-04-01`` placeholder, and those stamps are replaced here.
    """
    if sport == "nba":
        require_nba_payload(summary)
        states = events_from_espn_basketball(summary, density=density)
        return _restamp_basketball(summary, states)
    if sport == "nfl":
        require_nfl_payload(summary)
    else:
        require_nhl_payload(summary)
    return states_from_espn(summary, density=density)


def _restamp_basketball(
    summary: Mapping[str, Any],
    states: list[GameState],
) -> list[GameState]:
    """Pair each NBA snapshot with the play wallclock the adapter ignored."""
    plays = _play_stamps(summary)
    game_date = _summary_date(summary) or next(
        (when for _period, _clock, _home, _away, when in plays if when is not None),
        None,
    )
    cursor = 0
    previous: datetime | None = None
    matched = 0
    stamped: list[GameState] = []
    opening = _is_synthetic_opening(states, plays)
    for index, state in enumerate(states):
        when: datetime | None = None
        if index == 0 and opening:
            when = game_date
        else:
            while cursor < len(plays):
                period, clock, home_score, away_score, wall = plays[cursor]
                cursor += 1
                if (
                    period == state.period
                    and clock == state.seconds_remaining_period
                    and home_score == state.home_score
                    and away_score == state.away_score
                ):
                    when = wall
                    if wall is not None:
                        matched += 1
                    break
        if when is None:
            if previous is None and game_date is None:
                raise ValueError("NBA summary has no play wallclock to use as as_of")
            when = game_date if previous is None else previous + timedelta(seconds=1)
        if when is None:
            raise ValueError("NBA summary has no play wallclock to use as as_of")
        if previous is not None and when <= previous:
            when = previous + timedelta(seconds=1)
        previous = when
        stamped.append(replace(state, as_of=when))
    if matched == 0:
        raise ValueError("NBA summary has no play wallclock to use as as_of")
    return stamped


def _play_stamps(
    summary: Mapping[str, Any],
) -> list[tuple[int, int, int, int, datetime | None]]:
    stamps: list[tuple[int, int, int, int, datetime | None]] = []
    for raw in _basketball_plays(summary):
        try:
            home_score = int(raw.get("homeScore") or 0)
            away_score = int(raw.get("awayScore") or 0)
        except (TypeError, ValueError):
            continue
        stamps.append(
            (
                _play_period_number(raw),
                _parse_clock(_play_clock_display(raw)),
                home_score,
                away_score,
                _parse_time(raw.get("wallclock") or raw.get("modified")),
            )
        )
    return stamps


def _is_synthetic_opening(
    states: list[GameState],
    plays: list[tuple[int, int, int, int, datetime | None]],
) -> bool:
    if not states or states[0].status != "pre":
        return False
    if states[0].home_score != 0 or states[0].away_score != 0:
        return False
    if not plays:
        return True
    return (plays[0][2], plays[0][3]) != (0, 0)


def _summary_date(summary: Mapping[str, Any]) -> datetime | None:
    header = summary.get("header")
    if not isinstance(header, Mapping):
        return None
    competitions = header.get("competitions")
    if isinstance(competitions, list) and competitions and isinstance(competitions[0], Mapping):
        parsed = _parse_time(competitions[0].get("date"))
        if parsed is not None:
            return parsed
    return _parse_time(header.get("date"))


def _reject_placeholder(states: list[GameState]) -> None:
    for state in states:
        stamp = state.as_of
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        else:
            stamp = stamp.astimezone(timezone.utc)
        if stamp.replace(microsecond=0) == _PLACEHOLDER:
            raise ValueError("refusing to write the 2024-04-01 as_of placeholder")


def _file_token(text: str) -> str:
    cleaned = "".join(ch for ch in text if ch.isalnum())
    if not cleaned:
        raise ValueError(f"team abbreviation {text!r} cannot be used in a file name")
    return cleaned


def _write_replay(path: Path, states: list[GameState]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(dump_replay(states), encoding="utf-8", newline="\n")
    try:
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
