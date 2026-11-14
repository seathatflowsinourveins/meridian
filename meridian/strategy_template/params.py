"""The template's parameters: every threshold named, none with a value in this repository.

The values a strategy trades with come from its configuration. Calibrated values go to the
private `meridian-evidence` repository, never here (AGENTS.md). Tests and the simulation pass
their own values and label them synthetic and uncalibrated in `provenance`.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
from typing import Any

BPS = Decimal(10_000)


@dataclass(frozen=True, kw_only=True, slots=True)
class TemplateParams:
    """No field has a default: a missing one is a refusal, never a fallback."""

    # Where the values came from; the simulation and tests say "synthetic, uncalibrated".
    provenance: str
    # The trail distance: trail_atr_multiple x ATR over atr_period quotes, at least
    # trail_floor_bps of the mid (see TrailingTemplate's docstring).
    atr_period: int
    trail_atr_multiple: Decimal
    trail_floor_bps: Decimal
    # Marketable prices: an entry buys up to entry_limit_buffer_bps above the ask; an exit
    # sells down to exit_limit_buffer_bps under its trigger, or under the bid when re-priced.
    entry_limit_buffer_bps: Decimal
    exit_limit_buffer_bps: Decimal
    # An entry not final by then is cancelled (quote-driven, no timer).
    entry_timeout_seconds: Decimal
    base_quantity: int
    # Re-entry, the handbook's "Re-entry and rotation" (R1, R2, R3a, R5, confidence and size).
    reentry_enabled: bool
    cooldown_seconds: Decimal
    retry_rank_band: int
    reentry_min_confidence: Decimal
    confidence_size_floor: Decimal
    whipsaw_stopouts_max: int

    def __post_init__(self) -> None:
        problems = []
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            problems.append("provenance must say where the values came from")
        for f in fields(self):
            value = getattr(self, f.name)
            if f.type == "int" and (type(value) is not int or value < 1):
                problems.append(f"{f.name} must be a positive int")
            if f.type == "bool" and type(value) is not bool:
                problems.append(f"{f.name} must be a bool")
            if f.type == "Decimal" and (
                not isinstance(value, Decimal) or not value.is_finite() or value < 0
            ):
                problems.append(f"{f.name} must be a finite Decimal, not negative")
        if not problems:
            if self.trail_atr_multiple <= 0 and self.trail_floor_bps <= 0:
                problems.append("the trail needs a positive ATR multiple or floor")
            if not self.trail_floor_bps < BPS or not self.exit_limit_buffer_bps < BPS:
                problems.append("a bps value must be under 10,000")
            if self.exit_limit_buffer_bps <= 0:
                problems.append("exit_limit_buffer_bps must be positive, or no exit is marketable")
            for name in ("reentry_min_confidence", "confidence_size_floor"):
                if getattr(self, name) > 1:
                    problems.append(f"{name} must be within [0, 1]")
        if problems:
            raise ValueError("TemplateParams refused: " + "; ".join(problems))

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> TemplateParams:
        """From a configuration mapping; refuses missing and unknown names."""
        names = {f.name: f.type for f in fields(cls)}
        missing = sorted(set(names) - set(config))
        unknown = sorted(set(config) - set(names))
        if missing or unknown:
            raise ValueError(f"TemplateParams refused: missing {missing}, unknown {unknown}")
        values: dict[str, Any] = {}
        for name, kind in names.items():
            value = config[name]
            if kind == "Decimal" and not isinstance(value, bool):
                with suppress(InvalidOperation):  # left as is, then refused by type
                    value = Decimal(str(value))
            values[name] = value
        return cls(**values)
