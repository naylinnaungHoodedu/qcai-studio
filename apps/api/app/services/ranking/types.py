"""The ranking controller's runtime types (spec 3.2): frozen dataclasses, standard library only."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class Context:
    """c = (k, t, r): topic cluster, task type, tier (paper Sec. VII-A)."""

    cluster: str
    task_type: str
    tier: int

    def key(self) -> str:
        return f"{self.cluster}|{self.task_type}|{self.tier}"

    @classmethod
    def from_key(cls, key: str) -> "Context":
        cluster, task_type, tier = key.split("|")
        return cls(cluster, task_type, int(tier))


@dataclass(frozen=True)
class ModelRef:
    adapter_id: str
    family: str
    provider: str
    model_id: str
    model_version: str
    cost_units_per_call: int

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Signals:
    """Table X's signals, each a Decimal in [0, 1] or None (missing; the weights renormalise over the present ones)."""

    V: Decimal | None
    S: Decimal | None
    K: Decimal | None
    H: Decimal | None
    F: Decimal | None


@dataclass(frozen=True)
class Outcome:
    ledger_seq: int
    created_at: str
    model: str
    context: Context
    y: int
    signals: Signals
    cost_units: int
    latency_ms: int | None
    tier_source: str


@dataclass(frozen=True)
class Skip:
    ledger_seq: int
    reason: str
    model: str | None


@dataclass(frozen=True)
class Decision:
    kind: Literal["incumbent", "fallback"]
    model: str | None                          # None iff kind == "fallback"
    eligible: tuple[str, ...]
    explore: str | None
    action: Literal["generate", "abstain"]     # "abstain" iff fallback; no field can carry text

    def __post_init__(self) -> None:
        if (self.kind == "fallback") != (self.model is None) or (self.kind == "fallback") != (self.action == "abstain"):
            raise ValueError("a fallback decision, and only one, has no model and abstains")
