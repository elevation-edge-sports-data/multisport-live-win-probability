"""Canonical game snapshot shared by every sport."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal, Mapping

Status = Literal["pre", "live", "final", "stale"]

STATUSES: tuple[Status, ...] = ("pre", "live", "final", "stale")

# Used when no prior file is loaded. A later JSON prior may override it.
DEFAULT_PRIOR_HOME = 0.5


def _require_int(name: str, value: int) -> int:
    # bool is a subclass of int and is never a legal score, period, or clock.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class GameState:
    """One clock-and-score snapshot for any sport.

    ``seconds_remaining_total`` is the clock the model reads. In regulation it
    is seconds until the end of regulation, not merely the current period. In
    overtime it is seconds left in the current overtime period.
    ``seconds_remaining_period`` is the period clock, kept for display and for
    adapters.

    Football and hockey details are optional. A missing ``down`` (or distance,
    yard line, possession, timeouts, strength, extra attacker) still leaves a
    complete state. The v0 win-probability model does not read those fields.
    """

    sport: str
    game_id: str
    home: str
    away: str
    home_score: int
    away_score: int
    period: int
    seconds_remaining_period: int
    seconds_remaining_total: int
    status: Status
    source: str
    as_of: datetime
    prior_home: float = DEFAULT_PRIOR_HOME
    possession: str | None = None
    down: int | None = None
    distance: int | None = None
    yardline: int | None = None
    timeouts: Mapping[str, int] | None = None
    strength: str | None = None
    extra_attacker: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.sport, str) or not self.sport:
            raise ValueError("sport is required")
        if not isinstance(self.game_id, str) or not self.game_id:
            raise ValueError("game_id is required")
        if not isinstance(self.home, str) or not self.home:
            raise ValueError("home is required")
        if not isinstance(self.away, str) or not self.away:
            raise ValueError("away is required")
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("source is required")
        if not isinstance(self.as_of, datetime):
            raise TypeError("as_of must be a datetime")
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")

        home_score = _require_int("home_score", self.home_score)
        away_score = _require_int("away_score", self.away_score)
        period = _require_int("period", self.period)
        period_clock = _require_int(
            "seconds_remaining_period", self.seconds_remaining_period
        )
        total_clock = _require_int(
            "seconds_remaining_total", self.seconds_remaining_total
        )
        if home_score < 0 or away_score < 0:
            raise ValueError("scores must be >= 0")
        if period < 1:
            raise ValueError("period must be >= 1")
        if period_clock < 0 or total_clock < 0:
            raise ValueError("seconds remaining must be >= 0")

        prior = float(self.prior_home)
        if prior != prior or not 0.0 < prior < 1.0:
            raise ValueError("prior_home must be in (0, 1)")

        object.__setattr__(self, "home_score", home_score)
        object.__setattr__(self, "away_score", away_score)
        object.__setattr__(self, "period", period)
        object.__setattr__(self, "seconds_remaining_period", period_clock)
        object.__setattr__(self, "seconds_remaining_total", total_clock)
        object.__setattr__(self, "prior_home", prior)
        if self.timeouts is not None:
            object.__setattr__(
                self, "timeouts", MappingProxyType(dict(self.timeouts))
            )
