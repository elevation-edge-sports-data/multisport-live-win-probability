"""Copy a playoff-lab Elo snapshot onto ``data/elo_snapshot.json``.

The source is the first positional argument, then the ``ELO_SNAPSHOT_SOURCE``
environment variable, then ``../multisport-playoff-lab/outputs/elo_snapshot.json``
relative to this repository. The destination is replaced only after the file
parses and NFL, NHL, and NBA each have a numeric ``home_advantage``.

After a successful copy, ``check_elo_snapshot`` reads that file again. It
warns when the file is missing, when ``as_of`` is older than 7 days, or when
NFL, NHL, or NBA lacks a numeric ``home_advantage``. ``--check`` runs only
that read.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_DEST = _REPO / "data" / "elo_snapshot.json"
_ENV = "ELO_SNAPSHOT_SOURCE"
_DEFAULT_RELATIVE = (
    Path("..") / "multisport-playoff-lab" / "outputs" / "elo_snapshot.json"
)
_DEFAULT_SOURCE = (_REPO / _DEFAULT_RELATIVE).resolve()
_SPORTS = ("nfl", "nhl", "nba")
_LABELS = {"nfl": "NFL", "nhl": "NHL", "nba": "NBA"}
_MAX_AGE_DAYS = 7


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Copy a fresh Elo snapshot onto data/elo_snapshot.json\n"
            "and print as_of plus the NFL, NHL, and NBA home_advantage values.\n"
            "\n"
            f"Source order: positional argument, {_ENV},\n"
            f"{_DEFAULT_RELATIVE.as_posix()}\n"
            "relative to the repository root.\n"
            "\n"
            "After a copy, the destination is checked. --check only reads\n"
            "data/elo_snapshot.json and does not copy."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="elo_snapshot.json to copy",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check data/elo_snapshot.json. Do not copy.",
    )
    return parser


def _resolve_source(cli: str | None) -> Path:
    if cli is not None:
        text = cli.strip()
        if not text:
            raise ValueError("source path is empty")
        return Path(text).expanduser().resolve()
    env = os.environ.get(_ENV, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return _DEFAULT_SOURCE


def _numeric_home_advantage(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("not numeric")
    return number


def _read_report(payload: object) -> tuple[str, dict[str, float]]:
    if not isinstance(payload, dict):
        raise ValueError("elo snapshot must be a JSON object")
    as_of = payload.get("as_of")
    if not isinstance(as_of, str) or not as_of.strip():
        raise ValueError("elo snapshot is missing as_of")
    sports = payload.get("sports")
    if not isinstance(sports, dict):
        raise ValueError("elo snapshot is missing sports")
    advantages: dict[str, float] = {}
    for sport in _SPORTS:
        block = sports.get(sport)
        label = _LABELS[sport]
        if not isinstance(block, dict):
            raise ValueError(f"{label} block lacks a numeric home_advantage")
        try:
            advantages[sport] = _numeric_home_advantage(block.get("home_advantage"))
        except ValueError:
            raise ValueError(
                f"{label} block lacks a numeric home_advantage"
            ) from None
    return as_of.strip(), advantages


def _install(dest: Path, payload: bytes) -> None:
    """Replace ``dest`` only after ``payload`` is fully written beside it."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(dest.suffix + ".tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(dest)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    if temporary.exists():
        temporary.unlink()


def _format_advantage(value: float) -> str:
    if value.is_integer():
        return f"{value:.1f}"
    return f"{value:g}"


def _summary(as_of: str, advantages: dict[str, float]) -> str:
    parts = " | ".join(
        f"{_LABELS[sport]} home_advantage {_format_advantage(advantages[sport])}"
        for sport in _SPORTS
    )
    return f"as_of {as_of} | {parts}"


def _report(as_of: str, advantages: dict[str, float]) -> None:
    print(_summary(as_of, advantages))


def _as_of_date(value: str) -> date:
    head = value.strip().split("T", 1)[0].split(" ", 1)[0]
    try:
        return date.fromisoformat(head)
    except ValueError:
        raise ValueError(f"elo snapshot as_of is not a date: {value}") from None


def check_elo_snapshot(
    path: Path | None = None,
    *,
    today: date | None = None,
    max_age_days: int = _MAX_AGE_DAYS,
) -> int:
    """Read an Elo snapshot and report whether it is fresh.

    Age is the calendar-day gap from ``as_of`` to ``today`` (local today
    when omitted). A file older than ``max_age_days`` is not fresh. The
    filesystem modified time is not used. Prints an OK line and returns 0
    when the snapshot is fresh. Prints a warning and returns 1 otherwise.
    """
    target = _DEST if path is None else path
    if not target.is_file():
        print(f"warning: elo snapshot is missing: {target}", file=sys.stderr)
        return 1
    try:
        payload = json.loads(target.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(
            f"warning: elo snapshot is not valid JSON: {target} ({exc})",
            file=sys.stderr,
        )
        return 1
    try:
        as_of_text, advantages = _read_report(payload)
        as_of = _as_of_date(as_of_text)
    except ValueError as exc:
        print(f"warning: {exc}", file=sys.stderr)
        return 1
    current = date.today() if today is None else today
    age_days = (current - as_of).days
    if age_days > max_age_days:
        print(
            f"warning: elo snapshot as_of {as_of.isoformat()} "
            f"is older than {max_age_days} days",
            file=sys.stderr,
        )
        return 1
    print(f"OK elo snapshot {_summary(as_of.isoformat(), advantages)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.check:
        return check_elo_snapshot(_DEST)
    try:
        source = _resolve_source(args.source)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if not source.exists():
        print(f"elo snapshot source not found: {source}", file=sys.stderr)
        return 1
    if not source.is_file():
        print(f"elo snapshot source is not a file: {source}", file=sys.stderr)
        return 1
    try:
        payload = source.read_bytes()
    except OSError as exc:
        print(f"elo snapshot source not found: {source} ({exc})", file=sys.stderr)
        return 1
    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        print(f"elo snapshot is not valid JSON: {source}", file=sys.stderr)
        return 1
    try:
        as_of, advantages = _read_report(parsed)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    try:
        _install(_DEST, payload)
    except OSError as exc:
        print(f"could not write {_DEST}: {exc}", file=sys.stderr)
        return 1
    _report(as_of, advantages)
    return check_elo_snapshot(_DEST)


if __name__ == "__main__":
    raise SystemExit(main())
