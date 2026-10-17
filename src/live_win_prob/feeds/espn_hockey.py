"""Map a saved ESPN NHL summary to GameState snapshots.

ESPN hockey clocks on this payload are elapsed period time.
Play ``strength.text`` is Even Strength, Power Play, or Shorthanded
from the play's team, not a skater count. Penalty rows carry the
penalized team and, on current summaries, ``penaltyMinutes``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from live_win_prob.feeds.espn import home_moneyline_prior
from ms_win_prob import DEFAULT_PRIOR_HOME, GameState
from ms_win_prob.hockey.config import NHL_CONFIG


def load_summary(path: Path | str) -> Mapping[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("ESPN summary must be a JSON object")
    return payload


def events_from_espn_hockey(
    payload: Mapping[str, Any],
    *,
    prior_home: float | None = None,
) -> list[GameState]:
    header = payload.get("header")
    if not isinstance(header, Mapping):
        raise ValueError("ESPN hockey summary is missing header")
    competitions = header.get("competitions")
    if not isinstance(competitions, list) or not competitions:
        raise ValueError("ESPN hockey summary is missing competitions")
    competition = competitions[0]
    home, away, home_id, away_id = _teams(competition)
    game_id = str(header.get("id") or "unknown")
    prior = home_moneyline_prior(payload)
    if prior is None:
        prior = prior_home if prior_home is not None else DEFAULT_PRIOR_HOME
    plays = payload.get("plays")
    if not isinstance(plays, list) or not plays:
        raise ValueError("ESPN hockey summary has no plays")

    as_of = datetime(2022, 6, 1, tzinfo=timezone.utc)
    states: list[GameState] = []
    period_len = NHL_CONFIG.period_seconds
    tracker = HockeyStrengthTracker(home_id, away_id)

    for index, raw in enumerate(plays):
        if not isinstance(raw, Mapping):
            continue
        period_block = raw.get("period") if isinstance(raw.get("period"), Mapping) else {}
        period = int(period_block.get("number") or 1)
        clock = raw.get("clock") if isinstance(raw.get("clock"), Mapping) else {}
        elapsed = _parse_clock(str(clock.get("displayValue") or "0:00"))
        elapsed = min(max(elapsed, 0), period_len)
        typ = str((raw.get("type") or {}).get("text") or "")
        strength, extra = tracker.observe(raw)
        period_left = period_len - elapsed
        if period <= 3:
            total_left = (3 - period) * period_len + period_left
        else:
            total_left = period_left
        home_score = int(raw.get("homeScore") or 0)
        away_score = int(raw.get("awayScore") or 0)
        status = "live"
        if index == 0 and home_score == 0 and away_score == 0:
            status = "pre"
        if typ in {"End of Game"} or (
            index == len(plays) - 1 and home_score != away_score
        ):
            status = "final"
        states.append(
            GameState(
                sport="nhl",
                game_id=game_id,
                home=home,
                away=away,
                home_score=home_score,
                away_score=away_score,
                period=max(period, 1),
                seconds_remaining_period=period_left,
                seconds_remaining_total=max(total_left, 0),
                status=status,  # type: ignore[arg-type]
                source="espn-summary",
                as_of=as_of,
                prior_home=prior,
                strength=strength,
                extra_attacker=extra,
            )
        )
    return states


def _teams(competition: Mapping[str, Any]) -> tuple[str, str, str, str]:
    home = away = home_id = away_id = ""
    for row in competition.get("competitors") or []:
        if not isinstance(row, Mapping):
            continue
        team = row.get("team") if isinstance(row.get("team"), Mapping) else {}
        abbr = str(team.get("abbreviation") or "")
        ident = str(team.get("id") or "")
        if row.get("homeAway") == "home":
            home, home_id = abbr, ident
        elif row.get("homeAway") == "away":
            away, away_id = abbr, ident
    return home, away, home_id, away_id


def _parse_clock(display: str) -> int:
    text = display.strip()
    if ":" not in text:
        try:
            return int(float(text))
        except ValueError:
            return 0
    minutes, _, rest = text.partition(":")
    seconds = rest.split(".")[0]
    try:
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        return 0


class _PenaltyBox:
    """One penalty that removes a skater until it expires or a power-play goal."""

    def __init__(
        self,
        side: str,
        start_period: int,
        start_elapsed: int,
        duration: int,
        *,
        ends_on_goal: bool,
        period_seconds: int,
    ) -> None:
        self.side = side
        self.start_period = start_period
        self.start_elapsed = start_elapsed
        self.duration = duration
        self.ends_on_goal = ends_on_goal
        self.period_seconds = period_seconds

    def _global(self, period: int, elapsed: int) -> int:
        return (period - 1) * self.period_seconds + elapsed

    def active(self, period: int, elapsed: int) -> bool:
        now = self._global(period, elapsed)
        start = self._global(self.start_period, self.start_elapsed)
        return start <= now < start + self.duration

    def remaining(self, period: int, elapsed: int) -> int:
        now = self._global(period, elapsed)
        start = self._global(self.start_period, self.start_elapsed)
        return start + self.duration - now

    def end_at(self, period: int, elapsed: int) -> None:
        now = self._global(period, elapsed)
        start = self._global(self.start_period, self.start_elapsed)
        self.duration = max(0, now - start)


class HockeyStrengthTracker:
    """Skater strength implied by penalties and the play's own strength label.

    Coincidental penalties of equal length at the same clock offset, so a
    pair of fighting majors stays 5-on-5. A misconduct does not change the
    count. A power-play goal ends one minor. ``Even Strength`` with no
    empty-net note is 5-on-5 when the box count disagrees with the label.
    A missing label leaves the box count, which is 5-on-5 when nothing is
    active. Empty net is set only when the play text or an empty-net flag
    says so. The team that scored or shot has five; the other team has the
    extra attacker.
    """

    def __init__(self, home_id: str, away_id: str, *, period_seconds: int = 1200) -> None:
        self.home_id = str(home_id)
        self.away_id = str(away_id)
        self.period_seconds = period_seconds
        self._boxes: list[_PenaltyBox] = []
        self._pending: list[Mapping[str, Any]] = []

    def observe(self, play: Mapping[str, Any]) -> tuple[str | None, bool | None]:
        """Situation during this play, then absorb the penalty or goal."""
        if self._pending and not self._continues_batch(play):
            self._commit()
        situation = self._situation(play)
        if _is_penalty_event(play):
            self._pending.append(play)
        elif _is_goal(play):
            self._end_power_play_minor(play)
        return situation

    def at_clock(self, period: int, elapsed: int) -> tuple[str, bool]:
        """Strength at a clock with no play of its own. Pending calls are committed."""
        self._commit()
        home, away = self._counts(period, max(elapsed, 0))
        return f"{home}v{away}", False

    def _continues_batch(self, play: Mapping[str, Any]) -> bool:
        if not self._pending:
            return False
        if _period_elapsed(play) != _period_elapsed(self._pending[-1]):
            return False
        return _is_penalty_event(play) or _type_text(play) == "Stoppage"

    def _commit(self) -> None:
        pending = self._pending
        self._pending = []
        if not pending:
            return
        period, elapsed = _period_elapsed(pending[0])
        specs: list[tuple[str, int, bool]] = []
        for play in pending:
            specs.extend(self._specs(play))
        for side, seconds, ends_on_goal in _cancel_coincidental(specs):
            self._boxes.append(
                _PenaltyBox(
                    side,
                    period,
                    elapsed,
                    seconds,
                    ends_on_goal=ends_on_goal,
                    period_seconds=self.period_seconds,
                )
            )

    def _specs(self, play: Mapping[str, Any]) -> list[tuple[str, int, bool]]:
        typ = _type_map(play)
        text = str(typ.get("text") or "")
        kind = str(typ.get("penaltyType") or "")
        if "misconduct" in kind.lower() or "misconduct" in text.lower():
            return []
        side = self._side(play)
        if side is None:
            return []
        try:
            minutes = int(str(typ.get("penaltyMinutes")))
        except (TypeError, ValueError):
            minutes = 2
        if minutes <= 0:
            return []
        if "double" in kind.lower() or minutes == 4:
            return [(side, 120, True), (side, 120, True)]
        ends_on_goal = "major" not in kind.lower() and minutes < 5
        return [(side, minutes * 60, ends_on_goal)]

    def _side(self, play: Mapping[str, Any]) -> str | None:
        ident = _team_id(play)
        if ident == self.home_id:
            return "home"
        if ident == self.away_id:
            return "away"
        return None

    def _counts(self, period: int, elapsed: int) -> tuple[int, int]:
        home_down = sum(
            1 for box in self._boxes if box.side == "home" and box.active(period, elapsed)
        )
        away_down = sum(
            1 for box in self._boxes if box.side == "away" and box.active(period, elapsed)
        )
        return max(3, 5 - home_down), max(3, 5 - away_down)

    def _situation(self, play: Mapping[str, Any]) -> tuple[str | None, bool | None]:
        period, elapsed = _period_elapsed(play)
        home, away = self._counts(period, elapsed)
        label = _strength_label(play)
        team = _team_id(play)
        if label == "Even Strength" and home != away:
            home, away = 5, 5
        elif (
            label in {"Power Play", "Shorthanded"}
            and team in {self.home_id, self.away_id}
        ):
            advantaged = _advantaged_side(label, team, self.home_id)
            favors = (advantaged == "home" and home > away) or (
                advantaged == "away" and away > home
            )
            if not favors:
                home, away = (5, 4) if advantaged == "home" else (4, 5)
        extra = False
        if _is_empty_net(play):
            extra = True
            if team == self.home_id:
                away = min(6, away + 1)
            elif team == self.away_id:
                home = min(6, home + 1)
        if label in {"Power Play", "Shorthanded"} and home == away and not extra:
            return None, None
        return f"{home}v{away}", extra

    def _end_power_play_minor(self, play: Mapping[str, Any]) -> None:
        if _strength_label(play) != "Power Play":
            return
        team = _team_id(play)
        if team == self.home_id:
            short_side = "away"
        elif team == self.away_id:
            short_side = "home"
        else:
            period, elapsed = _period_elapsed(play)
            home, away = self._counts(period, elapsed)
            if home > away:
                short_side = "away"
            elif away > home:
                short_side = "home"
            else:
                return
        period, elapsed = _period_elapsed(play)
        candidates = [
            box
            for box in self._boxes
            if box.side == short_side and box.ends_on_goal and box.active(period, elapsed)
        ]
        if not candidates:
            return
        min(candidates, key=lambda box: box.remaining(period, elapsed)).end_at(
            period, elapsed
        )


def _cancel_coincidental(
    specs: list[tuple[str, int, bool]],
) -> list[tuple[str, int, bool]]:
    """Drop equal-length penalties assessed on both teams at one stoppage."""
    home = [spec for spec in specs if spec[0] == "home"]
    away = [spec for spec in specs if spec[0] == "away"]
    kept_home: list[tuple[str, int, bool]] = []
    for spec in home:
        match = next((item for item in away if item[1] == spec[1]), None)
        if match is None:
            kept_home.append(spec)
        else:
            away.remove(match)
    return kept_home + away


def _advantaged_side(label: str, team: str, home_id: str) -> str:
    on_home = team == home_id
    if label == "Power Play":
        return "home" if on_home else "away"
    return "away" if on_home else "home"


def _strength_label(play: Mapping[str, Any]) -> str | None:
    raw = play.get("strength")
    if not isinstance(raw, Mapping):
        return None
    text = raw.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


def _team_id(play: Mapping[str, Any]) -> str | None:
    team = play.get("team")
    if isinstance(team, Mapping) and team.get("id") is not None:
        return str(team.get("id"))
    return None


def _type_map(play: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = play.get("type")
    if isinstance(raw, Mapping):
        return raw
    return {}


def _type_text(play: Mapping[str, Any]) -> str:
    return str(_type_map(play).get("text") or "")


def _is_penalty_event(play: Mapping[str, Any]) -> bool:
    typ = _type_map(play)
    text = str(typ.get("text") or "")
    if "shot" in text.lower():
        return False
    if typ.get("penaltyType") not in (None, ""):
        return True
    if typ.get("penaltyMinutes") not in (None, ""):
        return True
    abbreviation = str(typ.get("abbreviation") or "")
    return text == "Penalty" or abbreviation == "penalty"


def _is_goal(play: Mapping[str, Any]) -> bool:
    if _type_text(play) == "Goal":
        return True
    if play.get("scoringPlay") is not True:
        return False
    try:
        return int(play.get("scoreValue") or 0) > 0
    except (TypeError, ValueError):
        return False


def _is_empty_net(play: Mapping[str, Any]) -> bool:
    if play.get("emptyNet") is True or play.get("emptyNetGoal") is True:
        return True
    chunks: list[object] = [play.get("text")]
    shot = play.get("shotInfo")
    if isinstance(shot, Mapping):
        chunks.append(shot.get("text"))
        chunks.append(shot.get("abbreviation"))
    return any(isinstance(chunk, str) and _EMPTY_NET.search(chunk) for chunk in chunks)


def _period_elapsed(play: Mapping[str, Any]) -> tuple[int, int]:
    raw_period = play.get("period")
    number = raw_period.get("number") if isinstance(raw_period, Mapping) else raw_period
    try:
        period = int(number or 1)
    except (TypeError, ValueError):
        period = 1
    clock = play.get("clock")
    if isinstance(clock, Mapping):
        display = str(clock.get("displayValue") or "")
    elif isinstance(clock, str):
        display = clock
    else:
        display = ""
    elapsed = min(max(_parse_clock(display), 0), 20 * 60)
    return max(period, 1), elapsed


_EMPTY_NET = re.compile(r"empty[\s-]*net", re.I)
