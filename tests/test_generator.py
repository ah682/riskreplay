"""The simulator must supply temporal evidence, not leak generation truth."""

import hashlib
import json
from datetime import datetime

import pytest

from riskreplay.generator import generate, logging_action, observe_outcomes
from riskreplay.schema import Event, validate_events


@pytest.fixture(scope="module")
def simulation():
    return generate(seed=17, n_transactions=360)


def _time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_generator_repeats_exactly_without_global_random_state(simulation):
    repeated = generate(seed=17, n_transactions=360)
    assert repeated == simulation
    assert generate(seed=18, n_transactions=360) != simulation
    roots = {
        event["transaction_id"]
        for event in simulation["events"]
        if event["event_type"] == "transaction" and not event["supersedes"]
    }
    assert len(roots) == 360
    assert roots == {row["transaction_id"] for row in simulation["oracle"]}


def test_generated_deliveries_pass_normalized_contract(simulation):
    events = simulation["events"]
    validated = validate_events([Event(**event) for event in events])
    assert len(validated) == len(events)
    assert [event["delivery_seq"] for event in events] == list(range(1, len(events) + 1))
    assert [event["available_at"] for event in events] == sorted(
        event["available_at"] for event in events
    )
    for event in events:
        assert _time(event["available_at"]) >= _time(event["event_time"])
        encoded = json.dumps(event["payload"], sort_keys=True, separators=(",", ":")).encode()
        assert event["payload_hash"] == hashlib.sha256(encoded).hexdigest()


def test_duplicate_has_auditable_deliveries_and_identical_identity(simulation):
    deliveries = [event for event in simulation["events"] if event["event_id"] == "evt-t-duplicate"]
    assert len(deliveries) == 3
    assert len({event["delivery_seq"] for event in deliveries}) == 3
    identities = [
        {key: value for key, value in event.items() if key not in {"available_at", "delivery_seq"}}
        for event in deliveries
    ]
    assert identities[0] == identities[1] == identities[2]
    assert deliveries[0]["available_at"] == deliveries[1]["available_at"]
    assert deliveries[0]["delivery_seq"] < deliveries[1]["delivery_seq"]


def test_fixed_facts_arrive_after_original_sunday_decision(simulation):
    events = {event["event_id"]: event for event in simulation["events"]}
    sunday = events["evt-t-sunday"]
    for identifier in ("block-history-tuesday", "flag-history-backfill", "evt-t-correction-v2"):
        assert events[identifier]["available_at"] > sunday["available_at"]
    late = events["evt-t-late"]
    assert late["event_time"] < sunday["event_time"] < late["available_at"]
    amended = events["evt-t-correction-v2"]
    original = events[amended["supersedes"]]
    assert amended["transaction_id"] == original["transaction_id"]
    assert amended["event_time"] == original["event_time"]
    assert original["payload"]["amount"] == 40
    assert amended["payload"]["amount"] == 740
    assert set(amended["payload"]) == set(original["payload"])


def test_fridays_label_is_unavailable_for_monday_training(simulation):
    events = {event["event_id"]: event for event in simulation["events"]}
    monday = events["evt-t-monday"]
    outcome = events["outcome-t-monday"]
    assert _time(monday["available_at"]).weekday() == 0
    assert _time(outcome["available_at"]).weekday() == 4
    assert outcome["available_at"] > monday["available_at"]
    assert outcome["payload"]["label"] == 1


def test_oracle_is_separate_and_declines_are_not_given_labels(simulation):
    assert "oracle" not in json.dumps(simulation["events"])
    assert "oracle" not in json.dumps(simulation["config"])
    truth = {row["transaction_id"]: row["oracle_label"] for row in simulation["oracle"]}
    outcomes = {
        event["transaction_id"]: event["payload"]["label"]
        for event in simulation["events"]
        if event["event_type"] == "outcome"
    }
    declined = {
        event["transaction_id"]
        for event in simulation["events"]
        if event["event_type"] == "transaction"
        and not event["supersedes"]
        and event["payload"]["logging_declined"]
    }
    assert declined
    assert declined.isdisjoint(outcomes)
    assert all(label == truth[txid] for txid, label in outcomes.items())
    assert len(outcomes) < len(truth)
    final_events = observe_outcomes(simulation["events"], {"t-tuesday", "t-sunday"})
    assert all(
        event["transaction_id"] not in {"t-tuesday", "t-sunday"}
        for event in final_events
        if event["event_type"] == "outcome"
    )
    original_sequences = {event["delivery_seq"] for event in simulation["events"]}
    assert {event["delivery_seq"] for event in final_events} < original_sequences
    validate_events([Event(**event) for event in final_events])
    final_events[0]["payload"]["complete"] = False
    assert simulation["events"][0]["payload"]["complete"] is True


def test_schedule_includes_recoverable_outage_and_policy_shift(simulation):
    events = {event["event_id"]: event for event in simulation["events"]}
    assert events["velocity-outage-20-on"]["available_at"] < events["evt-t-outage"]["available_at"]
    assert events["evt-t-outage"]["available_at"] < events["velocity-outage-20-off"]["available_at"]
    assert (
        events["velocity-outage-20-off"]["available_at"]
        < events["evt-t-after-outage"]["available_at"]
    )
    assert logging_action({"amount": 300}, day=39) == "approve"
    assert logging_action({"amount": 300}, day=40) == "review"
    assert logging_action({"amount": 900}, day=40) == "decline"


@pytest.mark.parametrize("kwargs", [{"seed": True}, {"n_transactions": 7}, {"n_transactions": 8.5}])
def test_invalid_generation_request_is_actionable(kwargs):
    with pytest.raises(ValueError, match="must be an integer"):
        generate(**kwargs)


def test_smallest_supported_fixture_is_complete():
    simulation = generate(n_transactions=8)
    assert len(simulation["oracle"]) == 8
    validate_events([Event(**event) for event in simulation["events"]])
