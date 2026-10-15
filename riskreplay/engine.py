"""Availability-aware state with explicit event-time bounds and provenance."""

from __future__ import annotations

from bisect import bisect_right
from datetime import timedelta
from typing import Any

from .schema import ContractError, Cutoff, Event, iso, timestamp, validate_events

REGIMES = {
    "available": "Original knowledge: event_time <= decision_time and (available_at, delivery_seq) <= recorded cutoff; deduplicated identities.",
    "event_time_only": "Hindsight baseline: event_time <= decision_time, ignoring availability; deduplicated identities. Not deployable historical knowledge.",
    "current_state": "Naive hindsight baseline: latest lists, flags, corrections and outage state; historical event-time velocity window. Not deployable historical knowledge.",
}


def validate_window_seconds(value: Any) -> int:
    """Reject malformed feature configurations before calculating historical state."""
    if type(value) is not int or value <= 0:
        raise ContractError("Feature window_seconds must be a positive integer")
    return value


def _effective_key(event: Event) -> tuple[str, str, int]:
    return event.event_time, event.available_at, event.delivery_seq


class TemporalEngine:
    def __init__(self, events: list[Event]):
        self.events = validate_events(events)
        self.keys = [event.delivery_key for event in self.events]
        self.by_id: dict[str, Event] = {}
        self.transactions: dict[str, list[Event]] = {}
        for event in self.events:
            self.by_id.setdefault(event.event_id, event)
            if event.event_type == "transaction":
                self.transactions.setdefault(event.transaction_id, []).append(event)

    def visible(self, cutoff: Cutoff, regime: str = "available") -> list[Event]:
        if regime not in REGIMES:
            raise ValueError(f"Unknown information regime {regime}")
        candidates = (
            self.events[: bisect_right(self.keys, cutoff.key)]
            if regime == "available"
            else self.events
        )
        unique: dict[str, Event] = {}
        for event in candidates:
            if regime != "current_state" and event.event_time > cutoff.time:
                continue
            unique.setdefault(event.event_id, event)
        superseded = {e.supersedes for e in unique.values() if e.supersedes}
        return [e for eid, e in unique.items() if eid not in superseded]

    def build(
        self, transaction_id: str, cutoff: Cutoff, feature_spec: dict, regime: str = "available"
    ) -> dict[str, Any]:
        window_seconds = validate_window_seconds(feature_spec.get("window_seconds"))
        visible = self.visible(cutoff, regime)
        tx = next(
            (
                e
                for e in visible
                if e.event_type == "transaction" and e.transaction_id == transaction_id
            ),
            None,
        )
        if tx is None:
            return {
                "missing": [f"Transaction {transaction_id} is unavailable at the recorded cutoff"],
                "features": {},
                "provenance": {},
                "visible_ids": [],
            }
        account = tx.payload["account_id"]
        checkpoint: dict[str, Event] = {}
        gaps: dict[str, Event] = {}
        latest: dict[str, Event] = {}
        window_start = iso(timestamp(cutoff.time) - timedelta(seconds=window_seconds))
        history: list[Event] = []
        for event in sorted(visible, key=_effective_key):
            if event.event_type == "checkpoint":
                scope = event.payload["scope"]
                if not event.payload["complete"]:
                    gaps[scope] = event
                old = checkpoint.get(scope)
                # A refresh cannot move the origin of uninterrupted coverage.
                if not (old and old.payload["complete"] and event.payload["complete"]):
                    checkpoint[scope] = event
            elif (
                event.event_type in {"blocklist", "flag"} and event.payload["account_id"] == account
            ):
                latest[event.event_type] = event
            elif event.event_type == "outage":
                latest["outage"] = event
            elif (
                event.event_type == "transaction"
                and event.payload["account_id"] == account
                and event.transaction_id != transaction_id
                and window_start < event.event_time <= cutoff.time
            ):
                history.append(event)
        missing = []
        for scope in ("blocklist", "flags", "velocity"):
            state = checkpoint.get(scope)
            if state is None or not state.payload["complete"]:
                missing.append(
                    f"Missing historical {scope} state: no complete checkpoint available at cutoff"
                )
            elif scope == "velocity" and state.event_time > window_start:
                missing.append(
                    "Missing velocity history: checkpoint starts inside the requested window"
                )
            elif scope in gaps and scope != "velocity":
                kind = "blocklist" if scope == "blocklist" else "flag"
                account_state = latest.get(kind)
                if account_state is None or _effective_key(account_state) <= _effective_key(state):
                    missing.append(
                        f"Missing historical {scope} state for account {account}: coverage resumed "
                        f"at {state.event_id}, but no account state is effective after that checkpoint"
                    )
        outage = bool(latest.get("outage") and latest["outage"].payload["active"])
        features = {
            "amount": float(tx.payload["amount"]),
            "velocity_1h": -1.0 if outage else float(len(history)),
            "velocity_amount_1h": -1.0
            if outage
            else round(sum(e.payload["amount"] for e in history), 2),
            "blocked": float(
                bool(latest.get("blocklist") and latest["blocklist"].payload["blocked"])
            ),
            "flagged": float(bool(latest.get("flag") and latest["flag"].payload["flagged"])),
            "outage": float(outage),
        }
        provenance = {
            "amount": [tx.event_id],
            "blocked": ([checkpoint["blocklist"].event_id] if "blocklist" in checkpoint else [])
            + ([latest["blocklist"].event_id] if "blocklist" in latest else []),
            "flagged": ([checkpoint["flags"].event_id] if "flags" in checkpoint else [])
            + ([latest["flag"].event_id] if "flag" in latest else []),
            "velocity_1h": ([checkpoint["velocity"].event_id] if "velocity" in checkpoint else [])
            + ([] if outage else [e.event_id for e in history]),
            "velocity_amount_1h": (
                [checkpoint["velocity"].event_id] if "velocity" in checkpoint else []
            )
            + ([] if outage else [e.event_id for e in history]),
            "outage": [latest["outage"].event_id]
            if "outage" in latest
            else ([checkpoint["velocity"].event_id] if "velocity" in checkpoint else []),
        }
        if outage:
            provenance["velocity_1h"].append(latest["outage"].event_id)
            provenance["velocity_amount_1h"].append(latest["outage"].event_id)
        for scope, feature in (("blocklist", "blocked"), ("flags", "flagged")):
            if scope in gaps and gaps[scope].event_id not in provenance[feature]:
                provenance[feature].insert(0, gaps[scope].event_id)
        return {
            "missing": missing,
            "features": features,
            "provenance": provenance,
            "visible_ids": [e.event_id for e in visible],
            "transaction": tx.to_dict(),
            "window": {"start_exclusive": window_start, "end_inclusive": cutoff.time},
            "information_regime": REGIMES[regime],
        }

    def timeline(self, transaction_id: str, cutoff: Cutoff, provenance: dict) -> list[dict]:
        txs = self.transactions.get(transaction_id, [])
        accounts = {e.payload["account_id"] for e in txs}
        contributors = {eid for ids in provenance.values() for eid in ids}
        visible = {e.event_id for e in self.visible(cutoff)}
        seen: set[str] = set()
        timeline = []
        lower = iso(timestamp(cutoff.time) - timedelta(hours=2))
        upper = iso(timestamp(cutoff.time) + timedelta(days=3))
        for event in self.events:
            relevant = (
                event.transaction_id == transaction_id
                or event.event_id in contributors
                or (
                    event.event_type in {"blocklist", "flag"}
                    and event.payload.get("account_id") in accounts
                )
                or (
                    event.event_type == "transaction"
                    and event.payload.get("account_id") in accounts
                    and lower <= event.event_time <= cutoff.time
                )
                or (event.event_type == "outage" and lower <= event.event_time <= upper)
            )
            if not relevant:
                continue
            included = (
                event.event_id in contributors
                and event.delivery_key <= cutoff.key
                and event.event_id not in seen
            )
            if event.delivery_key > cutoff.key:
                reason = "Unavailable at decision cutoff"
            elif event.event_id in seen:
                reason = "Duplicate delivery; retained for audit, not counted"
            elif event.event_type == "outcome":
                reason = "Outcome evidence; never an input feature"
            elif event.event_id not in visible:
                reason = "Superseded by a correction available at cutoff"
            elif included:
                reason = "Contributed to historical features"
            else:
                reason = "Outside the feature window or not the latest state"
            timeline.append({**event.to_dict(), "included": included, "reason": reason})
            seen.add(event.event_id)
        return timeline

    def label(self, transaction_id: str, action: str, evaluation_cutoff: Cutoff) -> dict:
        if action == "decline":
            return {
                "label": None,
                "label_available_at": None,
                "label_status": "declined_unobserved",
            }
        available = [
            e
            for e in self.visible(evaluation_cutoff)
            if e.event_type == "outcome" and e.transaction_id == transaction_id
        ]
        if available:
            latest = max(available, key=lambda e: (e.event_time, *e.delivery_key))
            return {
                "label": latest.payload["label"],
                "label_available_at": latest.available_at,
                "label_status": "mature",
            }
        future = [
            e
            for e in self.events
            if e.event_type == "outcome" and e.transaction_id == transaction_id
        ]
        if future:
            earliest = min(future, key=lambda e: e.delivery_key)
            return {
                "label": None,
                "label_available_at": earliest.available_at,
                "label_status": "immature",
            }
        return {"label": None, "label_available_at": None, "label_status": "unobserved"}
