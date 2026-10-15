"""Coverage recovery must establish account facts, not reuse pre-gap membership."""

from dataclasses import replace

import pytest

from riskreplay.artifacts import ArtifactStore
from riskreplay.engine import TemporalEngine
from riskreplay.online import OnlineReference
from riskreplay.policy import archive_policy, evaluate
from riskreplay.schema import ContractError, Cutoff, Event


def event(eid, kind, when, sequence, payload, tx=None, available=None, supersedes=None):
    return Event.make(
        event_id=eid,
        event_type=kind,
        event_time=when,
        available_at=available or when,
        delivery_seq=sequence,
        payload=payload,
        transaction_id=tx,
        supersedes=supersedes,
        source="owned-recovery-regression",
    )


def checkpoints():
    return [
        event(
            f"checkpoint-{scope}",
            "checkpoint",
            "2026-01-01T00:00:00Z",
            index,
            {"scope": scope, "complete": True},
        )
        for index, scope in enumerate(("blocklist", "flags", "velocity"), 1)
    ]


def transaction(txid, account, when, sequence):
    return event(txid, "transaction", when, sequence, {"account_id": account, "amount": 25}, txid)


def gap_history(scope):
    kind, field = ("blocklist", "blocked") if scope == "blocklist" else ("flag", "flagged")
    return checkpoints() + [
        event("old-state", kind, "2026-01-02T09:00:00Z", 4, {"account_id": "alice", field: True}),
        transaction("before", "alice", "2026-01-02T10:00:00Z", 5),
        event("gap", "checkpoint", "2026-01-02T11:00:00Z", 6, {"scope": scope, "complete": False}),
        event(
            "resume", "checkpoint", "2026-01-02T12:00:00Z", 7, {"scope": scope, "complete": True}
        ),
        event(
            "refresh", "checkpoint", "2026-01-02T13:00:00Z", 8, {"scope": scope, "complete": True}
        ),
        transaction("alice-after", "alice", "2026-01-02T14:00:00Z", 9),
        transaction("bob-after", "bob", "2026-01-02T14:00:00Z", 10),
    ]


def offline(events, txid, cutoff, tmp_path):
    store = ArtifactStore(tmp_path)
    policy = archive_policy(store)
    return evaluate(TemporalEngine(events), store, txid, cutoff, policy)


def online(events, txid, cutoff):
    reference = OnlineReference()
    for delivery in sorted(events, key=lambda item: item.delivery_key):
        if delivery.delivery_key <= cutoff.key:
            reference.observe(delivery)
    return reference.features(txid, cutoff)


@pytest.mark.parametrize("scope", ["blocklist", "flags"])
def test_complete_marker_cannot_restore_membership_lost_during_gap(scope, tmp_path):
    records = gap_history(scope)
    cutoff = Cutoff("2026-01-02T14:00:00Z", 10)
    result = offline(records, "alice-after", cutoff, tmp_path)
    assert result["missing"] and scope in " ".join(result["missing"])
    assert result["action"] is None and result["score"] is None
    with pytest.raises(ContractError, match=scope):
        online(records, "alice-after", cutoff)


@pytest.mark.parametrize("scope", ["blocklist", "flags"])
def test_post_resume_account_fact_recovers_only_its_account_despite_complete_refresh(
    scope, tmp_path
):
    records = gap_history(scope)
    kind, field = ("blocklist", "blocked") if scope == "blocklist" else ("flag", "flagged")
    records.append(
        event(
            "alice-recovered",
            kind,
            "2026-01-02T12:30:00Z",
            11,
            {"account_id": "alice", field: False},
        )
    )
    cutoff = Cutoff("2026-01-02T14:00:00Z", 10)
    result = offline(records, "alice-after", cutoff, tmp_path)
    assert result["missing"] == []
    assert result["features"][field] == 0
    assert "alice-recovered" in result["provenance"][field]
    assert "resume" in result["provenance"][field]
    assert online(records, "alice-after", cutoff)[field] == 0
    bob = offline(records, "bob-after", cutoff, tmp_path)
    assert bob["missing"] and bob["action"] is None
    with pytest.raises(ContractError, match=scope):
        online(records, "bob-after", cutoff)


@pytest.mark.parametrize("scope", ["blocklist", "flags"])
def test_later_gap_does_not_change_reconstruction_before_it(scope, tmp_path):
    records = gap_history(scope)
    cutoff = Cutoff("2026-01-02T10:00:00Z", 5)
    field = "blocked" if scope == "blocklist" else "flagged"
    result = offline(records, "before", cutoff, tmp_path)
    assert result["missing"] == []
    assert result["features"][field] == 1
    assert online(records, "before", cutoff)[field] == 1


@pytest.mark.parametrize("scope", ["blocklist", "flags"])
def test_late_correction_with_pre_resume_effective_time_does_not_repair_gap(scope, tmp_path):
    records = gap_history(scope)
    kind, field = ("blocklist", "blocked") if scope == "blocklist" else ("flag", "flagged")
    records.append(
        event(
            "late-old-correction",
            kind,
            "2026-01-02T11:30:00Z",
            11,
            {"account_id": "alice", field: False},
            available="2026-01-02T13:30:00Z",
            supersedes="old-state",
        )
    )
    cutoff = Cutoff("2026-01-02T14:00:00Z", 10)
    result = offline(records, "alice-after", cutoff, tmp_path)
    assert result["missing"] and result["action"] is None
    with pytest.raises(ContractError, match=scope):
        online(records, "alice-after", cutoff)


@pytest.mark.parametrize("scope", ["blocklist", "flags"])
@pytest.mark.parametrize("state_sequence,recovered", [(99, False), (101, True)])
def test_tied_resume_and_account_state_use_delivery_sequence(
    scope, state_sequence, recovered, tmp_path
):
    records = [
        replace(item, delivery_seq=100) if item.event_id == "resume" else item
        for item in gap_history(scope)
    ]
    kind, field = ("blocklist", "blocked") if scope == "blocklist" else ("flag", "flagged")
    records.append(
        event(
            "tied-state",
            kind,
            "2026-01-02T12:00:00Z",
            state_sequence,
            {"account_id": "alice", field: False},
        )
    )
    cutoff = Cutoff("2026-01-02T14:00:00Z", 10)
    result = offline(records, "alice-after", cutoff, tmp_path)
    if recovered:
        assert result["missing"] == []
        assert result["features"][field] == 0
        assert online(records, "alice-after", cutoff)[field] == 0
    else:
        assert result["missing"] and result["action"] is None
        with pytest.raises(ContractError, match=scope):
            online(records, "alice-after", cutoff)


@pytest.mark.parametrize("scope", ["blocklist", "flags"])
def test_correction_moving_recovery_to_another_account_revokes_original_account_recovery(
    scope, tmp_path
):
    records = gap_history(scope)
    kind, field = ("blocklist", "blocked") if scope == "blocklist" else ("flag", "flagged")
    records += [
        event("recovered", kind, "2026-01-02T12:30:00Z", 11, {"account_id": "alice", field: False}),
        event(
            "recovered-v2",
            kind,
            "2026-01-02T12:30:00Z",
            12,
            {"account_id": "bob", field: False},
            available="2026-01-02T13:30:00Z",
            supersedes="recovered",
        ),
    ]
    cutoff = Cutoff("2026-01-02T14:00:00Z", 10)
    alice = offline(records, "alice-after", cutoff, tmp_path)
    assert alice["missing"] and alice["action"] is None
    with pytest.raises(ContractError, match=scope):
        online(records, "alice-after", cutoff)
    bob = offline(records, "bob-after", cutoff, tmp_path)
    assert bob["missing"] == []
    assert bob["features"][field] == 0
    assert online(records, "bob-after", cutoff)[field] == 0


INVALID_WINDOWS = [False, True, 0, -3600, 1.5, "3600", None]


@pytest.mark.parametrize("window", INVALID_WINDOWS)
def test_archive_rejects_invalid_velocity_window_before_creating_policy(window, tmp_path):
    with pytest.raises(ContractError, match="window_seconds.*positive integer"):
        archive_policy(ArtifactStore(tmp_path), window_seconds=window)


@pytest.mark.parametrize("window", INVALID_WINDOWS)
def test_direct_state_build_rejects_invalid_velocity_window(window):
    records = checkpoints() + [transaction("t", "alice", "2026-01-02T12:00:00Z", 4)]
    with pytest.raises(ContractError, match="window_seconds.*positive integer"):
        TemporalEngine(records).build(
            "t", Cutoff(records[-1].event_time, 4), {"window_seconds": window}
        )


@pytest.mark.parametrize("window", INVALID_WINDOWS)
def test_imported_invalid_feature_window_returns_incomplete_instead_of_an_action(window, tmp_path):
    store = ArtifactStore(tmp_path)
    manifest = store.get("policies", archive_policy(store))
    feature = store.get("features", manifest["features"])
    feature["window_seconds"] = window
    manifest["features"] = store.put("features", feature)
    policy = store.put("policies", manifest)
    records = checkpoints() + [transaction("t", "alice", "2026-01-02T12:00:00Z", 4)]
    result = evaluate(
        TemporalEngine(records), store, "t", Cutoff(records[-1].event_time, 4), policy
    )
    assert result["missing"] and "window_seconds" in " ".join(result["missing"])
    assert result["action"] is None and result["score"] is None


def test_positive_window_evaluates_actual_history_and_initial_known_empty_lists(tmp_path):
    store = ArtifactStore(tmp_path)
    policy = archive_policy(store, window_seconds=3600, review_velocity=1)
    records = checkpoints() + [
        transaction("prior", "alice", "2026-01-02T11:30:00Z", 4),
        transaction("t", "alice", "2026-01-02T12:00:00Z", 5),
    ]
    cutoff = Cutoff(records[-1].event_time, 5)
    result = evaluate(TemporalEngine(records), store, "t", cutoff, policy)
    assert result["missing"] == []
    assert result["features"]["velocity_1h"] == 1
    assert result["features"]["blocked"] == result["features"]["flagged"] == 0
    assert result["action"] == "review"
    assert online(records, "t", cutoff)["velocity_1h"] == 1
