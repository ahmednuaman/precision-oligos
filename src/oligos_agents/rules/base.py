"""Pluggable rule-pack registry.

Conflict detection is intentionally pure Python: a rule is a callable that maps
an :class:`~oligos_agents.models.OligoRecord` to an optional
:class:`~oligos_agents.models.Conflict`. This keeps the compliance path fully
deterministic and unit-testable - no LLM inference is involved in deciding
whether a conflict exists. New sites can register additional packs without
touching the pipeline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from oligos_agents.models import Conflict, OligoRecord

RuleFn = Callable[[OligoRecord], Conflict | None]


@dataclass(frozen=True)
class RulePack:
    """A named, versioned collection of deterministic conflict rules."""

    code: str
    version: str
    rules: tuple[RuleFn, ...]


_REGISTRY: dict[str, RulePack] = {}


def register_pack(pack: RulePack) -> None:
    """Register (or replace) a rule-pack by its code."""
    _REGISTRY[pack.code] = pack


def get_pack(code: str) -> RulePack:
    return _REGISTRY[code]


def get_packs() -> list[RulePack]:
    """Return all registered rule-packs."""
    return list(_REGISTRY.values())


def run_pack(record: OligoRecord, pack: RulePack) -> list[Conflict]:
    """Apply every rule in *pack* to *record*."""
    conflicts: list[Conflict] = []
    for rule in pack.rules:
        conflict = rule(record)
        if conflict is not None:
            conflicts.append(conflict)
    return conflicts


def run_all(record: OligoRecord, packs: list[RulePack] | None = None) -> list[Conflict]:
    """Apply all rules from the given packs (or every registered pack)."""
    packs = packs if packs is not None else get_packs()
    conflicts: list[Conflict] = []
    for pack in packs:
        conflicts.extend(run_pack(record, pack))
    return conflicts
