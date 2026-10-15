"""Validated version-one records. No wall-clock defaults or inferred labels."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

EVENT_TYPES = {"transaction", "blocklist", "flag", "outage", "checkpoint", "outcome"}
ACTIONS = {"approve", "review", "decline"}


class ContractError(ValueError):
    """An input violates the normalized data contract."""


class FrozenDict(dict):
    """JSON-compatible immutable mapping; constructor aliases are never retained."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("Historical event payloads are immutable; append a correction event")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable

    def __deepcopy__(self, memo):
        return self


def freeze(value):
    if isinstance(value, dict):
        return FrozenDict({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ContractError(f"Invalid ISO timestamp {value!r}; include a UTC offset") from exc
    if result.tzinfo is None:
        raise ContractError(f"Timestamp {value!r} has no timezone; use ISO 8601 UTC")
    return result.astimezone(timezone.utc)


def iso(value: str | datetime) -> str:
    if not isinstance(value, (str, datetime)):
        raise ContractError("Timestamp must be an ISO 8601 string or timezone-aware datetime")
    dt = timestamp(value) if isinstance(value, str) else value
    if dt.tzinfo is None:
        raise ContractError("Datetime must include a timezone")
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Cutoff:
    time: str
    sequence: int

    def __post_init__(self):
        object.__setattr__(self, "time", iso(self.time))
        if type(self.sequence) is not int or self.sequence < 0:
            raise ContractError("cutoff sequence must be a nonnegative integer")

    @property
    def key(self) -> tuple[str, int]:
        return self.time, self.sequence


@dataclass(frozen=True)
class Event:
    event_id: str
    transaction_id: str | None
    event_type: str
    event_time: str
    available_at: str
    delivery_seq: int
    payload: dict[str, Any]
    payload_hash: str
    source: str
    supersedes: str | None = None
    schema_version: int = 1

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ContractError(
                f"{self.event_id}: unsupported schema_version {self.schema_version}; expected 1"
            )
        if (
            not isinstance(self.event_id, str)
            or not self.event_id
            or not isinstance(self.source, str)
            or not self.source
        ):
            raise ContractError("event_id and source must be nonempty strings")
        if self.transaction_id is not None and (
            not isinstance(self.transaction_id, str) or not self.transaction_id
        ):
            raise ContractError(
                f"{self.event_id}: transaction_id must be a nonempty string or null"
            )
        if self.supersedes is not None and (
            not isinstance(self.supersedes, str) or not self.supersedes
        ):
            raise ContractError(f"{self.event_id}: supersedes must be a nonempty event ID or null")
        if not isinstance(self.payload, dict):
            raise ContractError(f"{self.event_id}: payload must be an object")
        object.__setattr__(self, "payload", freeze(self.payload))
        if not isinstance(self.event_type, str) or self.event_type not in EVENT_TYPES:
            raise ContractError(f"{self.event_id}: unknown event_type {self.event_type}")
        if type(self.delivery_seq) is not int or self.delivery_seq <= 0:
            raise ContractError(f"{self.event_id}: delivery_seq must be a positive integer")
        object.__setattr__(self, "event_time", iso(self.event_time))
        object.__setattr__(self, "available_at", iso(self.available_at))
        if self.available_at < self.event_time:
            raise ContractError(
                f"{self.event_id}: available_at precedes event_time; fix ingestion timestamp"
            )
        if self.payload_hash != digest(self.payload):
            raise ContractError(f"{self.event_id}: payload_hash does not match canonical payload")
        if self.event_type in {"transaction", "outcome"} and not self.transaction_id:
            raise ContractError(f"{self.event_id}: {self.event_type} requires transaction_id")
        p = self.payload
        if self.event_type == "transaction":
            if not isinstance(p.get("account_id"), str) or not p["account_id"]:
                raise ContractError(f"{self.event_id}: transaction requires account_id")
            amount = p.get("amount")
            if (
                isinstance(amount, bool)
                or not isinstance(amount, (int, float))
                or not math.isfinite(amount)
                or amount < 0
            ):
                raise ContractError(f"{self.event_id}: amount must be a finite nonnegative number")
        if self.event_type in {"blocklist", "flag"}:
            field_name = "blocked" if self.event_type == "blocklist" else "flagged"
            if (
                not isinstance(p.get("account_id"), str)
                or not p["account_id"]
                or type(p.get(field_name)) is not bool
            ):
                raise ContractError(
                    f"{self.event_id}: requires account_id and boolean {field_name}"
                )
        if self.event_type == "outcome" and (
            type(p.get("label")) is not int or p["label"] not in (0, 1)
        ):
            raise ContractError(f"{self.event_id}: outcome label must be integer 0 or 1")
        if self.event_type == "outage" and (
            p.get("feature") != "velocity" or type(p.get("active")) is not bool
        ):
            raise ContractError(
                f"{self.event_id}: outage requires feature='velocity' and boolean active"
            )
        if self.event_type == "checkpoint" and (
            p.get("scope") not in {"blocklist", "flags", "velocity"}
            or type(p.get("complete")) is not bool
        ):
            raise ContractError(
                f"{self.event_id}: checkpoint requires a known scope and boolean complete"
            )

    @property
    def delivery_key(self) -> tuple[str, int]:
        return self.available_at, self.delivery_seq

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def make(cls, *, payload: dict, **kwargs) -> Event:
        return cls(payload=payload, payload_hash=digest(payload), **kwargs)


@dataclass(frozen=True)
class Decision:
    transaction_id: str
    decision_time: str
    cutoff_seq: int
    policy_hash: str
    original_score: float
    original_action: str
    feature_values: dict[str, float] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self):
        object.__setattr__(self, "decision_time", iso(self.decision_time))
        if not isinstance(self.transaction_id, str) or not self.transaction_id:
            raise ContractError("decision transaction_id must not be empty")
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or not isinstance(self.original_action, str)
            or self.original_action not in ACTIONS
        ):
            raise ContractError(f"{self.transaction_id}: invalid decision schema or action")
        if (
            not isinstance(self.policy_hash, str)
            or len(self.policy_hash) != 64
            or any(c not in "0123456789abcdef" for c in self.policy_hash)
        ):
            raise ContractError(f"{self.transaction_id}: policy_hash must be a SHA256 identifier")
        if (
            isinstance(self.original_score, bool)
            or not isinstance(self.original_score, (int, float))
            or not math.isfinite(self.original_score)
            or not 0 <= self.original_score <= 1
        ):
            raise ContractError(f"{self.transaction_id}: original_score must be in [0,1]")
        Cutoff(self.decision_time, self.cutoff_seq)
        if not isinstance(self.feature_values, dict):
            raise ContractError(f"{self.transaction_id}: feature_values must be an object")
        for name, value in self.feature_values.items():
            if not isinstance(name, str) or not name:
                raise ContractError(
                    f"{self.transaction_id}: feature names must be nonempty strings"
                )
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ContractError(
                    f"{self.transaction_id}: feature_values.{name} must be a finite number"
                )
        object.__setattr__(self, "feature_values", freeze(self.feature_values))

    @property
    def cutoff(self) -> Cutoff:
        return Cutoff(self.decision_time, self.cutoff_seq)

    def to_dict(self) -> dict:
        return asdict(self)


def validate_events(events: list[Event]) -> list[Event]:
    """Dedup identity is event_id; deliveries retain unique sequence numbers."""
    sequences: set[int] = set()
    identities: dict[str, Event] = {}
    transaction_roots: dict[str, str] = {}
    for event in sorted(events, key=lambda e: e.delivery_key):
        if digest(event.payload) != event.payload_hash:
            raise ContractError(f"{event.event_id}: historical payload was modified")
        if event.delivery_seq in sequences:
            raise ContractError(f"{event.event_id}: reused delivery_seq {event.delivery_seq}")
        sequences.add(event.delivery_seq)
        previous = identities.get(event.event_id)
        if previous:
            fields = (
                "payload_hash",
                "source",
                "event_type",
                "event_time",
                "transaction_id",
                "supersedes",
            )
            if any(getattr(previous, k) != getattr(event, k) for k in fields):
                raise ContractError(
                    f"{event.event_id}: conflicting identity; create a new correction event with supersedes"
                )
        else:
            identities[event.event_id] = event
            if event.event_type == "transaction" and not event.supersedes:
                if event.transaction_id in transaction_roots:
                    raise ContractError(
                        f"{event.transaction_id}: multiple transaction identities; use supersedes for corrections"
                    )
                transaction_roots[event.transaction_id] = event.event_id
    corrections: dict[str, str] = {}
    for event in identities.values():
        if event.event_type == "outcome":
            root_id = transaction_roots.get(event.transaction_id)
            if root_id is None:
                raise ContractError(
                    f"{event.event_id}: outcome references unknown transaction {event.transaction_id}"
                )
            if event.event_time < identities[root_id].event_time:
                raise ContractError(f"{event.event_id}: outcome event precedes its transaction")
        if event.supersedes:
            old = identities.get(event.supersedes)
            if old is None:
                raise ContractError(
                    f"{event.event_id}: supersedes unknown event {event.supersedes}"
                )
            if old.event_type != event.event_type or old.transaction_id != event.transaction_id:
                raise ContractError(
                    f"{event.event_id}: correction changes event type or transaction identity"
                )
            if event.delivery_key <= old.delivery_key:
                raise ContractError(
                    f"{event.event_id}: correction must arrive after its predecessor"
                )
            if event.supersedes in corrections:
                raise ContractError(
                    f"{event.event_id}: ambiguous correction branch for {event.supersedes}; supersede the latest correction"
                )
            corrections[event.supersedes] = event.event_id
    return sorted(events, key=lambda e: e.delivery_key)


def validate_decisions(decisions: list[Decision], events: list[Event]) -> list[Decision]:
    seen: set[str] = set()
    tx_events: dict[str, list[Event]] = {}
    for event in events:
        if event.event_type == "transaction":
            tx_events.setdefault(event.transaction_id, []).append(event)
    for decision in decisions:
        if decision.transaction_id in seen:
            raise ContractError(f"{decision.transaction_id}: duplicate recorded decision")
        seen.add(decision.transaction_id)
        txs = tx_events.get(decision.transaction_id, [])
        if not txs:
            raise ContractError(f"{decision.transaction_id}: decision references no transaction")
        if not any(
            e.delivery_key <= decision.cutoff.key and e.event_time <= decision.decision_time
            for e in txs
        ):
            raise ContractError(
                f"{decision.transaction_id}: decision precedes transaction availability"
            )
    return sorted(decisions, key=lambda d: (*d.cutoff.key, d.transaction_id))
