"""Owned, deterministic sequential payment simulation with a separate oracle.

The ordinary event stream contains only outcomes eligible for observation under
the logging policy.  The returned ``oracle`` is a separate evaluation fixture;
it must never be passed to training, replay, or observational metrics.  Call
``observe_outcomes`` with the actual archived declines before persisting events.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

GENERATOR_VERSION = "owned-sequential-v1"
START = datetime(2025, 1, 5, tzinfo=timezone.utc)
HORIZON_DAYS = 80
POLICY_SHIFT_DAY = 40
MIN_TRANSACTIONS = 8

RawEvent = dict[str, Any]


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode()).hexdigest()


def logging_action(payload: dict[str, Any], day: int = 0) -> str:
    """Observable amount rule used to select potentially observed outcomes.

    The archived policy also has historical blocklist and model/rule decisions;
    ``observe_outcomes`` applies its final declines.  A review is assumed to
    result in eventual fulfillment in this simulation.  The day-40 policy shift
    changes the review threshold without making declined outcomes observable.
    """
    if float(payload["amount"]) >= 900:
        return "decline"
    if float(payload["amount"]) >= (250 if day >= POLICY_SHIFT_DAY else 350):
        return "review"
    return "approve"


def observe_outcomes(
    events: Iterable[RawEvent], declined_transaction_ids: Iterable[str]
) -> list[RawEvent]:
    """Remove outcome events for actual logging-policy declines.

    This is an observation boundary, not a counterfactual estimator.  Delivery
    sequence numbers are retained, including gaps left by omitted deliveries.
    Copies prevent a caller from mutating the source simulation accidentally.
    """
    declined = frozenset(declined_transaction_ids)
    return [
        copy.deepcopy(event)
        for event in events
        if not (event["event_type"] == "outcome" and event["transaction_id"] in declined)
    ]


class _Schedule:
    def __init__(self) -> None:
        self.events: list[RawEvent] = []

    def add(
        self,
        event_id: str,
        event_type: str,
        event_time: datetime,
        payload: dict[str, Any],
        *,
        available_at: datetime | None = None,
        transaction_id: str | None = None,
        supersedes: str | None = None,
    ) -> RawEvent:
        event: RawEvent = {
            "event_id": event_id,
            "transaction_id": transaction_id,
            "event_type": event_type,
            "event_time": _iso(event_time),
            "available_at": _iso(available_at or event_time),
            "delivery_seq": 0,
            "payload": copy.deepcopy(payload),
            "payload_hash": _hash(payload),
            "source": "owned-simulator",
            "supersedes": supersedes,
            "schema_version": 1,
        }
        self.events.append(event)
        return event

    def duplicate(self, event: RawEvent, available_at: datetime) -> None:
        delivery = copy.deepcopy(event)
        delivery["available_at"] = _iso(available_at)
        self.events.append(delivery)

    def finish(self) -> list[RawEvent]:
        # Python's stable sort preserves insertion order for a tied timestamp.
        # The resulting global sequence makes that order part of the contract.
        result = sorted(self.events, key=lambda event: event["available_at"])
        for sequence, event in enumerate(result, start=1):
            event["delivery_seq"] = sequence
        return result


def _payload(
    account_id: str, amount: float, country: str = "GB", device_risk: float = 0.05
) -> dict[str, Any]:
    return {
        "account_id": account_id,
        "amount": round(amount, 2),
        "country": country,
        "cohort": "domestic" if country == "GB" else "cross_border",
        "device_risk": round(device_risk, 4),
        "logging_declined": amount >= 900,
    }


def generate(seed: int = 17, n_transactions: int = 1800) -> dict[str, Any]:
    """Return normalized deliveries, isolated ground truth, and provenance.

    Exactly ``n_transactions`` distinct original transactions are generated.
    Corrections and duplicate deliveries do not count as new transactions.
    Eight fixed acceptance transactions are always included; other transactions
    span 80 chronological days.  No network, wall clock, or global RNG is used.
    """
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if type(n_transactions) is not int or n_transactions < MIN_TRANSACTIONS:
        raise ValueError(f"n_transactions must be an integer >= {MIN_TRANSACTIONS}")
    rng = random.Random(seed)
    schedule = _Schedule()
    oracle: list[dict[str, Any]] = []
    # The simulator owns the entire history from this declared empty snapshot.
    # Removing a checkpoint is an intentional missing-evidence test, not an
    # invitation to infer empty historical membership from absent list events.
    for scope in ("blocklist", "flags", "velocity"):
        schedule.add(
            f"checkpoint-{scope}-start",
            "checkpoint",
            START - timedelta(days=1),
            {"scope": scope, "complete": True},
        )

    schedule.add(
        "block-history-tuesday",
        "blocklist",
        START + timedelta(days=2, hours=8),
        {"account_id": "acct-history", "blocked": True},
        available_at=START + timedelta(days=2, hours=8, minutes=2),
    )
    schedule.add(
        "flag-history-backfill",
        "flag",
        START + timedelta(hours=10),
        {"account_id": "acct-history", "flagged": True},
        available_at=START + timedelta(days=4, hours=9),
    )
    for i, account in enumerate((0, 11, 22, 33, 44, 55)):
        when = START + timedelta(days=5 + i * 3, hours=7)
        schedule.add(
            f"flag-acct-{account:03d}-on",
            "flag",
            when,
            {"account_id": f"acct-{account:03d}", "flagged": True},
            available_at=when + timedelta(minutes=3),
        )
    for i, account in enumerate((11, 33)):
        when = START + timedelta(days=24 + i * 4, hours=8)
        schedule.add(
            f"block-acct-{account:03d}-on",
            "blocklist",
            when,
            {"account_id": f"acct-{account:03d}", "blocked": True},
        )
    schedule.add(
        "flag-acct-022-off",
        "flag",
        START + timedelta(days=52, hours=8),
        {"account_id": "acct-022", "flagged": False},
    )
    schedule.add(
        "block-acct-011-off",
        "blocklist",
        START + timedelta(days=53, hours=8),
        {"account_id": "acct-011", "blocked": False},
    )
    for day in (20, 56):
        for active, hour in ((True, 10), (False, 16)):
            schedule.add(
                f"velocity-outage-{day}-{'on' if active else 'off'}",
                "outage",
                START + timedelta(days=day, hours=hour),
                {"feature": "velocity", "active": active},
            )

    def transaction(
        transaction_id: str,
        when: datetime,
        payload: dict[str, Any],
        label: int,
        *,
        available_at: datetime | None = None,
        outcome_time: datetime | None = None,
        label_available_at: datetime | None = None,
    ) -> RawEvent:
        event = schedule.add(
            f"evt-{transaction_id}",
            "transaction",
            when,
            payload,
            transaction_id=transaction_id,
            available_at=available_at,
        )
        oracle.append({"transaction_id": transaction_id, "oracle_label": label})
        day = (when - START).days
        if logging_action(payload, day) != "decline":
            # Fraud is reported later on average.  Neither a positive nor a
            # negative label exists in the observable stream before arrival.
            outcome_when = outcome_time or when + timedelta(
                days=rng.randint(2, 10) if label else rng.randint(1, 4)
            )
            arrived = label_available_at or outcome_when + timedelta(
                days=rng.randint(1, 6) if label else rng.randint(0, 3),
                hours=rng.randint(0, 12),
            )
            arrived = max(arrived, available_at or when)
            schedule.add(
                f"outcome-{transaction_id}",
                "outcome",
                outcome_when,
                {"label": label},
                transaction_id=transaction_id,
                available_at=arrived,
            )
        return event

    correction = transaction(
        "t-correction",
        START + timedelta(hours=11, minutes=45),
        _payload("acct-history", 40),
        0,
    )
    duplicate = transaction(
        "t-duplicate",
        START + timedelta(hours=11, minutes=50),
        _payload("acct-history", 25),
        0,
    )
    schedule.duplicate(duplicate, START + timedelta(hours=11, minutes=50))
    schedule.duplicate(duplicate, START + timedelta(hours=11, minutes=51))
    transaction(
        "t-late",
        START + timedelta(hours=11, minutes=55),
        _payload("acct-history", 45),
        0,
        available_at=START + timedelta(days=1, hours=12),
    )
    transaction(
        "t-sunday",
        START + timedelta(hours=12),
        _payload("acct-history", 85),
        0,
    )
    transaction(
        "t-monday",
        START + timedelta(days=1, hours=9),
        _payload("acct-monday", 110, "FR", 0.64),
        1,
        outcome_time=START + timedelta(days=5, hours=9),
        label_available_at=START + timedelta(days=5, hours=12),
    )
    transaction(
        "t-tuesday",
        START + timedelta(days=2, hours=12),
        _payload("acct-history", 85),
        1,
    )
    transaction(
        "t-outage",
        START + timedelta(days=20, hours=12),
        _payload("acct-outage", 180, "FR", 0.3),
        0,
    )
    transaction(
        "t-after-outage",
        START + timedelta(days=21, hours=12),
        _payload("acct-outage", 175, "FR", 0.3),
        0,
    )
    corrected_payload = copy.deepcopy(correction["payload"])
    corrected_payload["amount"] = 740.0
    schedule.add(
        "evt-t-correction-v2",
        "transaction",
        START + timedelta(hours=11, minutes=45),
        corrected_payload,
        transaction_id="t-correction",
        supersedes=correction["event_id"],
        available_at=START + timedelta(days=3, hours=9),
    )

    remaining = n_transactions - MIN_TRANSACTIONS
    day_counts: dict[int, int] = {}
    for i in range(remaining):
        day = (i * HORIZON_DAYS) // max(remaining, 1)
        position = day_counts.get(day, 0)
        day_counts[day] = position + 1
        # Every day includes an account burst.  Other traffic has different
        # accounts and spacing, so a one-hour velocity captures useful signal.
        in_burst = position < 3
        if in_burst:
            account = (day % 6) * 11
            when = START + timedelta(days=day, hours=10, minutes=position)
        else:
            account = rng.randrange(72)
            when = START + timedelta(
                days=day,
                hours=8,
                seconds=(position - 3) * 907 % (12 * 3600),
            )
        account_risk = 0.86 if account % 11 == 0 else (0.4 if account % 7 == 0 else 0.04)
        device_risk = max(0.01, min(0.99, account_risk + rng.gauss(0, 0.13)))
        cross_border = rng.random() < (0.16 + 0.55 * account_risk)
        country = rng.choice(("FR", "DE", "US", "NG")) if cross_border else "GB"
        amount = rng.lognormvariate(4.25 + 0.8 * account_risk, 0.65)
        if account_risk > 0.8 and rng.random() < 0.2:
            amount += rng.uniform(280, 920)
        amount = round(min(amount, 2500), 2)
        log_odds = (
            -4.6
            + 3.4 * device_risk
            + 0.65 * math.log1p(amount / 100)
            + 0.75 * cross_border
            + 0.8 * in_burst
            + (0.25 * cross_border if day >= POLICY_SHIFT_DAY else 0)
        )
        label = int(rng.random() < 1 / (1 + math.exp(-log_odds)))
        payload = _payload(f"acct-{account:03d}", amount, country, device_risk)
        arrived = when + timedelta(seconds=rng.choice((0, 0, 0, 1, 2, 5)))
        if i % 37 == 0:
            arrived += timedelta(hours=rng.randint(2, 72))
        event = transaction(
            f"t-{i:05d}",
            when,
            payload,
            label,
            available_at=arrived,
        )
        if i % 29 == 0:
            schedule.duplicate(event, arrived + timedelta(seconds=1))
        if i % 101 == 0:
            amended = copy.deepcopy(payload)
            amended["amount"] = round(float(payload["amount"]) + 73.25, 2)
            schedule.add(
                f"{event['event_id']}-v2",
                "transaction",
                when,
                amended,
                transaction_id=event["transaction_id"],
                supersedes=event["event_id"],
                available_at=max(arrived, when) + timedelta(days=5, hours=2),
            )

    events = schedule.finish()
    config = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "n_transactions": n_transactions,
        "source": "owned-simulator",
        "provenance": "Owned synthetic simulation; no merchant or public payment records used.",
        "license": "Project-owned generated fixture data; no third-party dataset.",
        "start_time": _iso(START),
        "history_checkpoint_time": _iso(START - timedelta(days=1)),
        "horizon_days": HORIZON_DAYS,
        "policy_shift_day": POLICY_SHIFT_DAY,
        "split_times": {
            "train_end": _iso(START + timedelta(days=40)),
            "validation_end": _iso(START + timedelta(days=60)),
            "test_end": _iso(START + timedelta(days=80)),
        },
        "evaluation_cutoff": _iso(START + timedelta(days=84)),
        "delivery_order": "available_at ascending; stable insertion order breaks ties; positive global delivery_seq",
        "duplicate_identity": "event_id; duplicate deliveries retain identity and distinct sequence numbers",
        "outcome_observation": "amount>=900 declines unobserved; remove actual archived declines before persistence; reviewed transactions assumed fulfilled",
        "label_delay_days": {"fraud": [3, 16.5], "nonfraud": [1, 7.5]},
        "fixture_transaction_ids": {
            "sunday": "t-sunday",
            "monday": "t-monday",
            "tuesday": "t-tuesday",
            "late": "t-late",
            "correction": "t-correction",
            "duplicate": "t-duplicate",
            "outage": "t-outage",
            "after_outage": "t-after-outage",
        },
    }
    return {
        "events": events,
        "oracle": sorted(oracle, key=lambda row: row["transaction_id"]),
        "config": config,
    }
