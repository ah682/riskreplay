"""Independent, adversarial examples for the historical evidence contract."""

import random
from dataclasses import replace

import pytest

from riskreplay.artifacts import ArtifactStore
from riskreplay.engine import TemporalEngine
from riskreplay.policy import archive_policy, compare, evaluate, replay
from riskreplay.schema import (
    ContractError,
    Cutoff,
    Decision,
    Event,
    validate_decisions,
    validate_events,
)

SUNDAY = "2025-01-05T12:00:00Z"
WEDNESDAY = "2025-01-08T12:00:00Z"


def event(eid, kind, when, seq, payload, tx=None, available=None, supersedes=None):
    return Event.make(
        event_id=eid,
        transaction_id=tx,
        event_type=kind,
        event_time=when,
        available_at=available or when,
        delivery_seq=seq,
        payload=payload,
        source="independent-acceptance",
        supersedes=supersedes,
    )


def transaction(eid="target", when=SUNDAY, seq=5, amount=75, tx=None, **kwargs):
    return event(
        eid,
        "transaction",
        when,
        seq,
        {"account_id": "alice", "amount": amount},
        tx=tx or eid,
        **kwargs,
    )


def checkpoints():
    return [
        event(
            f"checkpoint-{scope}",
            "checkpoint",
            "2025-01-04T00:00:00Z",
            i + 1,
            {"scope": scope, "complete": True},
        )
        for i, scope in enumerate(("blocklist", "flags", "velocity"))
    ]


def recorded(engine, store, policy_hash, cutoff=None, transaction_id="target"):
    cutoff = cutoff or Cutoff(SUNDAY, 5)
    result = evaluate(engine, store, transaction_id, cutoff, policy_hash)
    assert result["missing"] == []
    return Decision(
        transaction_id=transaction_id,
        decision_time=cutoff.time,
        cutoff_seq=cutoff.sequence,
        policy_hash=policy_hash,
        original_score=result["score"],
        original_action=result["action"],
        feature_values=result["features"],
    )


def test_duplicate_deliveries_count_once_and_remain_auditable(tmp_path):
    prior = transaction("prior", "2025-01-05T11:40:00Z", 4, amount=40)
    duplicate = replace(prior, available_at="2025-01-05T11:45:00Z", delivery_seq=5)
    later_duplicate = replace(prior, available_at="2025-01-05T12:01:00Z", delivery_seq=7)
    engine = TemporalEngine(checkpoints() + [prior, duplicate, transaction(seq=6), later_duplicate])
    store = ArtifactStore(tmp_path)
    result = evaluate(engine, store, "target", Cutoff(SUNDAY, 6), archive_policy(store))
    assert result["features"]["velocity_1h"] == 1
    assert result["features"]["velocity_amount_1h"] == 40
    assert result["provenance"]["velocity_1h"].count("prior") == 1
    deliveries = [
        row
        for row in engine.timeline("target", Cutoff(SUNDAY, 6), result["provenance"])
        if row["event_id"] == "prior"
    ]
    assert len(deliveries) == 3
    assert [row["included"] for row in deliveries] == [True, False, False]
    assert "Duplicate delivery" in deliveries[1]["reason"]
    assert "Unavailable at decision cutoff" in deliveries[2]["reason"]


def test_earlier_event_delivered_late_distinguishes_availability_from_event_time(tmp_path):
    late = transaction(
        "late", "2025-01-05T11:50:00Z", 6, amount=45, available="2025-01-05T12:01:00Z"
    )
    engine = TemporalEngine(checkpoints() + [transaction(), late])
    store = ArtifactStore(tmp_path)
    policy = archive_policy(store)
    cutoff = Cutoff(SUNDAY, 5)
    original = evaluate(engine, store, "target", cutoff, policy)
    hindsight = evaluate(engine, store, "target", cutoff, policy, regime="event_time_only")
    assert original["features"]["velocity_1h"] == 0
    assert hindsight["features"]["velocity_1h"] == 1
    assert "late" not in original["provenance"]["velocity_1h"]
    assert "late" in hindsight["provenance"]["velocity_1h"]
    assert "Not deployable" in hindsight["information_regime"]
    late_row = next(
        row
        for row in engine.timeline("target", cutoff, original["provenance"])
        if row["event_id"] == "late"
    )
    assert not late_row["included"]
    assert late_row["reason"] == "Unavailable at decision cutoff"


def test_correction_and_backfill_change_hindsight_without_rewriting_history(tmp_path):
    prior = transaction("prior", "2025-01-05T11:50:00Z", 4, amount=40)
    amended = transaction(
        "prior-v2",
        prior.event_time,
        6,
        amount=740,
        tx="prior",
        available=WEDNESDAY,
        supersedes="prior",
    )
    backfill = event(
        "late-flag",
        "flag",
        "2025-01-05T09:00:00Z",
        7,
        {"account_id": "alice", "flagged": True},
        available=WEDNESDAY,
    )
    engine = TemporalEngine(checkpoints() + [prior, transaction(), amended, backfill])
    store = ArtifactStore(tmp_path)
    policy = archive_policy(store)
    cutoff = Cutoff(SUNDAY, 5)
    historical = evaluate(engine, store, "target", cutoff, policy)
    current = evaluate(engine, store, "target", cutoff, policy, regime="current_state")
    assert historical["features"]["velocity_amount_1h"] == 40
    assert historical["features"]["flagged"] == 0
    assert current["features"]["velocity_amount_1h"] == 740
    assert current["features"]["flagged"] == 1
    assert "prior" in historical["provenance"]["velocity_amount_1h"]
    assert "prior-v2" not in historical["visible_ids"]
    assert "prior-v2" in current["provenance"]["velocity_amount_1h"]
    assert "prior" not in current["provenance"]["velocity_amount_1h"]
    decision = recorded(engine, store, policy)
    assert replay(engine, store, decision)["status"] == "matched"


def test_cutoff_sequence_orders_tied_deliveries_inclusively(tmp_path):
    block = event(
        "same-time-block", "blocklist", SUNDAY, 6, {"account_id": "alice", "blocked": True}
    )
    engine = TemporalEngine(checkpoints() + [block, transaction()])
    store = ArtifactStore(tmp_path)
    policy = archive_policy(store)
    before = evaluate(engine, store, "target", Cutoff(SUNDAY, 5), policy)
    at = evaluate(engine, store, "target", Cutoff(SUNDAY, 6), policy)
    assert before["action"] == "approve"
    assert at["action"] == "decline"
    assert "same-time-block" not in before["visible_ids"]
    assert "same-time-block" in at["provenance"]["blocked"]
    unavailable = evaluate(engine, store, "target", Cutoff(SUNDAY, 4), policy)
    assert unavailable["action"] is None
    assert any("unavailable" in item for item in unavailable["missing"])


def test_velocity_window_is_open_at_start_and_inclusive_at_end(tmp_path):
    engine = TemporalEngine(
        checkpoints()
        + [
            transaction("at-start", "2025-01-05T11:00:00Z", 4, amount=90),
            transaction("just-inside", "2025-01-05T11:00:00.000001Z", 5, amount=30),
            transaction("at-end", SUNDAY, 6, amount=10),
            transaction(seq=7),
        ]
    )
    store = ArtifactStore(tmp_path)
    result = evaluate(engine, store, "target", Cutoff(SUNDAY, 7), archive_policy(store))
    assert result["features"]["velocity_1h"] == 2
    assert result["features"]["velocity_amount_1h"] == 40
    assert "at-start" not in result["provenance"]["velocity_1h"]


@pytest.mark.parametrize("scope", ["blocklist", "flags", "velocity"])
def test_missing_checkpoint_is_typed_incomplete_not_empty_membership(tmp_path, scope):
    store = ArtifactStore(tmp_path)
    policy = archive_policy(store)
    complete = TemporalEngine(checkpoints() + [transaction()])
    decision = recorded(complete, store, policy)
    missing = TemporalEngine(
        [row for row in checkpoints() if row.payload["scope"] != scope] + [transaction()]
    )
    result = replay(missing, store, decision)
    assert result["status"] == "incomplete"
    assert result["action"] is None and result["score"] is None
    assert any(scope in reason for reason in result["missing"])


def test_checkpoint_inside_requested_lookback_is_incomplete(tmp_path):
    snapshots = checkpoints()
    snapshots[2] = replace(
        snapshots[2], event_time="2025-01-05T11:30:00Z", available_at="2025-01-05T11:30:00Z"
    )
    store = ArtifactStore(tmp_path)
    policy = archive_policy(store)
    complete = TemporalEngine(checkpoints() + [transaction()])
    decision = recorded(complete, store, policy)
    result = replay(TemporalEngine(snapshots + [transaction()]), store, decision)
    assert result["status"] == "incomplete"
    assert any("inside the requested window" in reason for reason in result["missing"])


@pytest.mark.parametrize(
    "kind,policy_field",
    [
        ("models", "model"),
        ("features", "features"),
        ("rules", "rules"),
    ],
)
@pytest.mark.parametrize("failure", ["missing", "corrupt"])
def test_missing_or_corrupt_archived_artifacts_are_typed_incomplete(
    tmp_path,
    kind,
    policy_field,
    failure,
):
    engine = TemporalEngine(checkpoints() + [transaction()])
    store = ArtifactStore(tmp_path)
    policy = archive_policy(store)
    decision = recorded(engine, store, policy)
    artifact = store.get("policies", policy)[policy_field]
    path = tmp_path / kind / f"{artifact}.json"
    if failure == "missing":
        path.unlink()
    else:
        path.write_text("{}", encoding="utf-8")
    result = replay(engine, store, decision)
    assert result["status"] == "incomplete"
    assert result["action"] is None and result["score"] is None
    assert any(kind in reason for reason in result["missing"])


@pytest.mark.parametrize(
    "kind,policy_field,field,value",
    [
        ("features", "features", "code_hash", "unavailable-historical-code"),
        ("rules", "rules", "implementation", "unavailable-historical-rules"),
        ("models", "model", "type", "unavailable-historical-model"),
    ],
)
def test_unavailable_implementation_never_falls_back_to_current_code(
    tmp_path,
    kind,
    policy_field,
    field,
    value,
):
    engine = TemporalEngine(checkpoints() + [transaction()])
    store = ArtifactStore(tmp_path)
    policy_hash = archive_policy(store)
    manifest = store.get("policies", policy_hash)
    artifact = store.get(kind, manifest[policy_field])
    artifact[field] = value
    manifest[policy_field] = store.put(kind, artifact)
    historical_hash = store.put("policies", manifest)
    decision = replace(recorded(engine, store, policy_hash), policy_hash=historical_hash)
    result = replay(engine, store, decision)
    assert result["status"] == "incomplete"
    assert result["action"] is None
    assert any("unavailable" in reason for reason in result["missing"])


@pytest.mark.parametrize("fault", ["action", "score", "features"])
def test_archived_replay_matches_and_detects_recorded_decision_mismatch(tmp_path, fault):
    engine = TemporalEngine(checkpoints() + [transaction()])
    store = ArtifactStore(tmp_path)
    decision = recorded(engine, store, archive_policy(store))
    assert replay(engine, store, decision)["status"] == "matched"
    changes = {
        "action": {"original_action": "decline"},
        "score": {"original_score": 0.75},
        "features": {"feature_values": {**decision.feature_values, "velocity_1h": 999}},
    }
    result = replay(engine, store, replace(decision, **changes[fault]))
    assert result["status"] == "mismatched"
    assert result["missing"] == []


@pytest.mark.parametrize("changed_component", ["feature", "model", "rule"])
def test_candidate_trace_identifies_the_consequential_artifact(tmp_path, changed_component):
    engine = TemporalEngine(
        checkpoints()
        + [
            transaction("older", "2025-01-05T10:30:00Z", 4, amount=10),
            transaction(),
        ]
    )
    store = ArtifactStore(tmp_path)
    original = archive_policy(store, review_velocity=1)
    options = {
        "feature": {"window_seconds": 7200},
        "model": {
            "model": {
                "type": "fixture_logistic",
                "mode": "deterministic_fixture",
                "bias": 6,
                "weights": {},
            }
        },
        "rule": {"review_amount": 50},
    }
    candidate = archive_policy(store, review_velocity=1, **options[changed_component])
    result = compare(engine, store, recorded(engine, store, original), candidate)
    assert result["changed"] is True
    assert result["original"]["action"] == "approve"
    assert result["candidate"]["action"] == "review"
    changed_artifacts = {
        row["kind"] for row in result["explanation"] if "artifact changed" in row["message"]
    }
    assert changed_artifacts == {changed_component}
    assert result["first_divergence"].startswith(changed_component.capitalize() + " stage")
    assert result["original"]["regime"] == result["candidate"]["regime"] == "available"


def test_candidate_approval_of_historical_decline_has_unknown_outcome(tmp_path):
    engine = TemporalEngine(checkpoints() + [transaction()])
    store = ArtifactStore(tmp_path)
    original = archive_policy(store, decline_amount=50)
    candidate = archive_policy(store, decline_amount=900)
    decision = recorded(engine, store, original)
    result = compare(engine, store, decision, candidate)
    assert result["changed"] is True
    assert result["original"]["action"] == "decline"
    assert result["candidate"]["action"] == "approve"
    assert any(
        "Outcome under approval is unknown" in row["message"] for row in result["explanation"]
    )
    status = engine.label("target", decision.original_action, Cutoff(WEDNESDAY, 999))
    assert status["label_status"] == "declined_unobserved"
    assert status["label"] is None


def test_friday_outcome_is_not_a_monday_label_or_feature(tmp_path):
    monday = "2025-01-06T12:00:00Z"
    friday = "2025-01-10T12:00:00Z"
    tx = transaction(when=monday, seq=4)
    outcome = event("friday-outcome", "outcome", friday, 5, {"label": 1}, tx="target")
    engine = TemporalEngine(checkpoints() + [tx, outcome])
    label_before = engine.label("target", "approve", Cutoff(monday, 4))
    assert label_before["label_status"] == "immature"
    assert label_before["label"] is None
    assert engine.label("target", "approve", Cutoff(friday, 4))["label"] is None
    assert engine.label("target", "approve", Cutoff(friday, 5))["label"] == 1
    store = ArtifactStore(tmp_path)
    result = evaluate(engine, store, "target", Cutoff(monday, 4), archive_policy(store))
    assert "friday-outcome" not in result["visible_ids"]
    assert all("friday-outcome" not in ids for ids in result["provenance"].values())
    assert "label" not in result["features"]


def test_outage_uses_recorded_fallback_and_recovers_when_clear_arrives(tmp_path):
    prior = transaction("prior", "2025-01-05T11:40:00Z", 4, amount=40)
    outage = event(
        "outage", "outage", "2025-01-05T11:45:00Z", 5, {"feature": "velocity", "active": True}
    )
    clear = event(
        "clear",
        "outage",
        "2025-01-05T12:05:00Z",
        7,
        {"feature": "velocity", "active": False},
        available="2025-01-05T12:10:00Z",
    )
    engine = TemporalEngine(checkpoints() + [prior, outage, transaction(seq=6), clear])
    store = ArtifactStore(tmp_path)
    policy = archive_policy(store)
    interrupted = evaluate(engine, store, "target", Cutoff(SUNDAY, 6), policy)
    assert interrupted["action"] == "review"
    assert interrupted["features"]["velocity_1h"] == -1
    assert "outage" in interrupted["provenance"]["velocity_1h"]
    assert any(row["rule"] == "feature_outage" and row["selected"] for row in interrupted["trace"])
    recovered = evaluate(engine, store, "target", Cutoff("2025-01-05T12:10:00Z", 7), policy)
    assert recovered["action"] == "approve"
    assert recovered["features"]["velocity_1h"] == 1
    assert recovered["features"]["outage"] == 0


def test_shuffled_input_keeps_features_scores_actions_and_timeline_identical(tmp_path):
    prior = transaction("prior", "2025-01-05T11:40:00Z", 4, amount=40)
    duplicate = replace(prior, available_at="2025-01-05T11:41:00Z", delivery_seq=5)
    flag = event("flag", "flag", SUNDAY, 6, {"account_id": "alice", "flagged": True})
    events = checkpoints() + [prior, duplicate, flag, transaction(seq=7)]
    store = ArtifactStore(tmp_path)
    policy = archive_policy(store)
    cutoff = Cutoff(SUNDAY, 7)
    original_engine = TemporalEngine(events)
    expected = evaluate(original_engine, store, "target", cutoff, policy)
    expected_timeline = original_engine.timeline("target", cutoff, expected["provenance"])
    for seed in range(12):
        shuffled = list(events)
        random.Random(seed).shuffle(shuffled)
        engine = TemporalEngine(shuffled)
        result = evaluate(engine, store, "target", cutoff, policy)
        assert result == expected
        assert engine.timeline("target", cutoff, result["provenance"]) == expected_timeline


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"available_at": "2025-01-05T11:59:59Z"}, "precedes event_time"),
        ({"event_time": "2025-01-05T12:00:00"}, "no timezone"),
        ({"payload_hash": "0" * 64}, "payload_hash"),
        ({"delivery_seq": 0}, "positive integer"),
        ({"transaction_id": None}, "requires transaction_id"),
    ],
)
def test_import_rejects_invalid_timestamp_hash_and_required_identity(changes, error):
    raw = transaction().to_dict()
    raw.update(changes)
    with pytest.raises(ContractError, match=error):
        Event(**raw)


@pytest.mark.parametrize(
    "changes",
    [
        {"payload": {"account_id": "alice", "amount": 999}},
        {"source": "another-system"},
        {"transaction_id": "another-transaction"},
        {"event_time": "2025-01-05T11:59:59Z"},
    ],
)
def test_reused_event_id_cannot_disguise_changed_identity(changes):
    original = transaction()
    raw = original.to_dict()
    raw.update(changes, delivery_seq=6, available_at="2025-01-05T12:01:00Z")
    raw.pop("payload_hash")
    conflicting = Event.make(**raw)
    with pytest.raises(ContractError, match="conflicting identity"):
        validate_events([original, conflicting])


def test_two_roots_for_one_transaction_require_explicit_supersession():
    first = transaction()
    second = transaction("new-id", seq=6, tx="target", available="2025-01-05T12:01:00Z")
    with pytest.raises(ContractError, match="use supersedes"):
        validate_events([first, second])


def test_reused_delivery_sequence_is_rejected():
    with pytest.raises(ContractError, match="reused delivery_seq"):
        validate_events([transaction(), transaction("other", seq=5)])


@pytest.mark.parametrize(
    "scenario,error",
    [
        ("unknown", "supersedes unknown"),
        ("before", "must arrive after"),
        ("other_transaction", "changes event type or transaction identity"),
        ("branch", "ambiguous correction branch"),
    ],
)
def test_correction_links_must_form_an_unambiguous_valid_chain(scenario, error):
    first = transaction()
    changes = {"supersedes": "target", "tx": "target", "available": WEDNESDAY}
    if scenario == "unknown":
        changes["supersedes"] = "unknown-event"
    elif scenario == "before":
        changes["available"] = SUNDAY
    elif scenario == "other_transaction":
        changes["tx"] = "other"
    correction = transaction(
        "corrected", seq=4 if scenario == "before" else 6, amount=85, **changes
    )
    events = [first, correction]
    if scenario == "branch":
        events.append(transaction("branch", seq=7, amount=95, **changes))
    with pytest.raises(ContractError, match=error):
        validate_events(events)


def test_recorded_decision_cannot_precede_transaction_delivery(tmp_path):
    store = ArtifactStore(tmp_path)
    tx = transaction(available="2025-01-05T12:01:00Z")
    decision = Decision(
        transaction_id="target",
        decision_time=SUNDAY,
        cutoff_seq=5,
        policy_hash=archive_policy(store),
        original_score=0.1,
        original_action="approve",
    )
    with pytest.raises(ContractError, match="precedes transaction availability"):
        validate_decisions([decision], [tx])
    tied = replace(decision, decision_time=tx.available_at, cutoff_seq=4)
    with pytest.raises(ContractError, match="precedes transaction availability"):
        validate_decisions([tied], [tx])
