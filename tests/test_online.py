"""Independent reference expectations plus streamed simulator/replay agreement."""

from dataclasses import replace

import pytest

from riskreplay.engine import TemporalEngine
from riskreplay.generator import generate
from riskreplay.online import OnlineReference
from riskreplay.schema import ContractError, Cutoff, Event


def event(eid, kind, time, seq, payload, tx=None, available=None, supersedes=None):
    return Event.make(
        event_id=eid,
        event_type=kind,
        event_time=time,
        available_at=available or time,
        delivery_seq=seq,
        payload=payload,
        transaction_id=tx,
        supersedes=supersedes,
        source="independent-online-fixture",
    )


def tx(eid, time, seq, amount, **kwargs):
    return event(
        eid,
        "transaction",
        time,
        seq,
        {"account_id": "alice", "amount": amount},
        tx=kwargs.pop("transaction_id", eid),
        **kwargs,
    )


def checkpoints():
    return [
        event(
            f"checkpoint-{scope}",
            "checkpoint",
            "2026-01-01T00:00:00Z",
            i + 1,
            {"scope": scope, "complete": True},
        )
        for i, scope in enumerate(("blocklist", "flags", "velocity"))
    ]


def reference(events):
    stream = OnlineReference()
    for item in sorted(events, key=lambda item: item.delivery_key):
        stream.observe(item)
    return stream


def test_explicit_stream_handles_ties_late_facts_corrections_and_outcomes():
    lower = tx("lower-boundary", "2026-01-02T11:00:00Z", 4, 100)
    prior = tx("prior", "2026-01-02T11:15:00Z", 5, 30)
    duplicate = replace(prior, available_at="2026-01-02T11:20:00Z", delivery_seq=6)
    block = event(
        "block", "blocklist", "2026-01-02T11:30:00Z", 7, {"account_id": "alice", "blocked": True}
    )
    flag = event(
        "flag", "flag", "2026-01-02T11:30:00Z", 8, {"account_id": "alice", "flagged": True}
    )
    older = event(
        "old-clear",
        "blocklist",
        "2026-01-02T11:00:00Z",
        9,
        {"account_id": "alice", "blocked": False},
        available="2026-01-02T11:40:00Z",
    )
    target = tx("target", "2026-01-02T12:00:00Z", 10, 25)
    online = reference([*checkpoints(), lower, prior, duplicate, block, flag, older, target])
    original = online.features("target", Cutoff(target.available_at, 10))
    assert original == {
        "amount": 25.0,
        "velocity_1h": 1.0,
        "velocity_amount_1h": 30,
        "blocked": 1.0,
        "flagged": 1.0,
        "outage": 0.0,
    }
    clear = event(
        "clear", "blocklist", target.event_time, 11, {"account_id": "alice", "blocked": False}
    )
    online.observe(clear)
    assert online.features("target", Cutoff(target.event_time, 11))["blocked"] == 0
    outage = event(
        "outage", "outage", target.event_time, 12, {"feature": "velocity", "active": True}
    )
    online.observe(outage)
    unavailable = online.features("target", Cutoff(target.event_time, 12))
    assert unavailable["velocity_1h"] == unavailable["velocity_amount_1h"] == -1
    assert unavailable["outage"] == 1
    outcome = event(
        "outcome-prior",
        "outcome",
        "2026-01-02T11:50:00Z",
        13,
        {"label": 1},
        tx="prior",
        available=target.event_time,
    )
    online.observe(outcome)
    assert online.features("target", Cutoff(target.event_time, 13)) == unavailable
    correction = tx(
        "prior-v2",
        prior.event_time,
        14,
        80,
        transaction_id="prior",
        available=target.event_time,
        supersedes=prior.event_id,
    )
    online.observe(correction)
    late = tx("late", "2026-01-02T11:45:00Z", 15, 70, available="2026-01-02T12:01:00Z")
    online.observe(late)
    resume = event(
        "resume", "outage", "2026-01-02T12:02:00Z", 16, {"feature": "velocity", "active": False}
    )
    online.observe(resume)
    current = online.features("target", Cutoff(resume.event_time, 16))
    assert current["velocity_1h"] == 2
    assert current["velocity_amount_1h"] == 150
    assert current["outage"] == 0
    assert original["velocity_amount_1h"] == 30  # Previously returned scalars cannot mutate.
    # A duplicate of the corrected-away original must not resurrect it.
    online.observe(replace(prior, available_at="2026-01-02T12:03:00Z", delivery_seq=17))
    assert (
        online.features("target", Cutoff("2026-01-02T12:03:00Z", 17))["velocity_amount_1h"] == 150
    )


@pytest.mark.parametrize("missing_scope", ["blocklist", "flags", "velocity"])
def test_missing_checkpoint_is_an_explicit_online_failure(missing_scope):
    target = tx("target", "2026-01-02T12:00:00Z", 4, 25)
    online = reference([e for e in checkpoints() if e.payload["scope"] != missing_scope] + [target])
    with pytest.raises(ContractError, match=missing_scope):
        online.features("target", Cutoff(target.available_at, 4))


def test_complete_refresh_preserves_coverage_but_a_false_checkpoint_resets_it():
    target = tx("target", "2026-01-02T12:00:00Z", 4, 25)
    refresh = event(
        "refresh", "checkpoint", "2026-01-02T11:30:00Z", 5, {"scope": "velocity", "complete": True}
    )
    online = reference([*checkpoints(), refresh, target])
    assert online.features("target", Cutoff(target.available_at, 6))["velocity_1h"] == 0
    gap = event(
        "gap", "checkpoint", "2026-01-02T12:01:00Z", 7, {"scope": "velocity", "complete": False}
    )
    online.observe(gap)
    with pytest.raises(ContractError, match="velocity"):
        online.features("target", Cutoff(gap.available_at, 7))
    recovered = event(
        "recovered",
        "checkpoint",
        "2026-01-02T12:02:00Z",
        8,
        {"scope": "velocity", "complete": True},
    )
    online.observe(recovered)
    with pytest.raises(ContractError, match="inside the window"):
        online.features("target", Cutoff(recovered.available_at, 8))
    assert online.features("target", Cutoff("2026-01-02T13:02:00Z", 8))["velocity_1h"] == 0


def test_delivery_order_and_historical_query_guards_prevent_future_state_use():
    target = tx("target", "2026-01-02T12:00:00Z", 4, 25)
    online = reference([*checkpoints(), target])
    with pytest.raises(ContractError, match="strictly ordered"):
        online.observe(checkpoints()[0])
    with pytest.raises(ContractError, match="watermark"):
        online.features("target", Cutoff("2026-01-02T11:59:59Z", 3))
    with pytest.raises(ContractError, match="has not arrived"):
        online.features("unreceived", Cutoff(target.available_at, 4))


def test_conflicting_identity_and_branched_corrections_are_rejected():
    target = tx("target", "2026-01-02T12:00:00Z", 4, 25)
    online = reference([*checkpoints(), target])
    conflict = tx("target", target.event_time, 5, 99, available="2026-01-02T12:01:00Z")
    with pytest.raises(ContractError, match="conflicting online"):
        online.observe(conflict)
    corrected = tx(
        "target-v2",
        target.event_time,
        5,
        50,
        transaction_id="target",
        available="2026-01-02T12:01:00Z",
        supersedes="target",
    )
    online.observe(corrected)
    branch = tx(
        "target-v3",
        target.event_time,
        6,
        70,
        transaction_id="target",
        available="2026-01-02T12:02:00Z",
        supersedes="target",
    )
    with pytest.raises(ContractError, match="branches"):
        online.observe(branch)
    assert online.features("target", Cutoff(corrected.available_at, 5))["amount"] == 50


def test_observation_copies_immutable_received_data_and_returned_features():
    payload = {"account_id": "alice", "amount": 25}
    target = event("target", "transaction", "2026-01-02T12:00:00Z", 4, payload, tx="target")
    online = reference([*checkpoints(), target])
    payload["amount"] = 900
    before = online.features("target", Cutoff(target.event_time, 4))
    before["amount"] = 900
    assert online.features("target", Cutoff(target.event_time, 4))["amount"] == 25


def test_full_generator_stream_matches_offline_reconstruction_at_all_first_arrivals():
    raw = generate(seed=17, n_transactions=1800)
    events = sorted([Event(**row) for row in raw["events"]], key=lambda item: item.delivery_key)
    offline = TemporalEngine(events)
    online = OnlineReference()
    recorded = set()
    outages = 0
    for delivered in events:
        online.observe(delivered)
        if (
            delivered.event_type != "transaction"
            or delivered.supersedes
            or delivered.transaction_id in recorded
        ):
            continue
        cutoff = Cutoff(delivered.available_at, delivered.delivery_seq)
        live = online.features(delivered.transaction_id, cutoff)
        historical = offline.build(delivered.transaction_id, cutoff, {"window_seconds": 3600})
        assert not historical["missing"]
        assert live == historical["features"], delivered.transaction_id
        recorded.add(delivered.transaction_id)
        outages += bool(live["outage"])
    assert len(recorded) == 1800
    assert outages == 30
