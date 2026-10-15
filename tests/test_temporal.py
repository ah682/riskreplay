from riskreplay.artifacts import ArtifactStore
from riskreplay.engine import TemporalEngine
from riskreplay.policy import archive_policy, evaluate
from riskreplay.schema import Cutoff, Event


def event(eid, kind, when, seq, payload, tx=None, available=None, supersedes=None):
    return Event.make(
        event_id=eid,
        transaction_id=tx,
        event_type=kind,
        event_time=when,
        available_at=available or when,
        delivery_seq=seq,
        payload=payload,
        source="acceptance",
        supersedes=supersedes,
    )


def checkpoints():
    return [
        event(
            f"state-{scope}",
            "checkpoint",
            "2025-01-04T00:00:00Z",
            i + 1,
            {"scope": scope, "complete": True},
        )
        for i, scope in enumerate(("blocklist", "flags", "velocity"))
    ]


def test_tuesday_blocklist_cannot_change_sunday(tmp_path):
    events = checkpoints() + [
        event(
            "sunday",
            "transaction",
            "2025-01-05T10:00:00Z",
            4,
            {"account_id": "alice", "amount": 25},
            "sunday",
        ),
        event(
            "tuesday-block",
            "blocklist",
            "2025-01-07T10:00:00Z",
            5,
            {"account_id": "alice", "blocked": True},
        ),
    ]
    engine = TemporalEngine(events)
    store = ArtifactStore(tmp_path)
    policy = archive_policy(store)
    result = evaluate(engine, store, "sunday", Cutoff("2025-01-05T10:00:00Z", 4), policy)
    assert result["action"] == "approve"
    assert result["features"]["blocked"] == 0
    assert "tuesday-block" not in result["provenance"]["blocked"]
    naive = evaluate(
        engine, store, "sunday", Cutoff("2025-01-05T10:00:00Z", 4), policy, regime="current_state"
    )
    assert naive["action"] == "decline"
