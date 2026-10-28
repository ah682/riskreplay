"""Regression cases for missing evidence and imported archive boundaries."""

import hashlib
import json
from dataclasses import replace

import pytest
from test_invariants import SUNDAY, checkpoints, event, recorded, transaction

from riskreplay.artifacts import ArtifactStore
from riskreplay.cli import main
from riskreplay.engine import TemporalEngine
from riskreplay.pipeline import evaluate_run
from riskreplay.policy import archive_policy, replay
from riskreplay.schema import Cutoff, Decision
from riskreplay.storage import save_dataset

PROVENANCE = {"kind": "owned_synthetic", "source": "runtime audit", "permission": "owned fixture"}


def test_incomplete_report_uses_transaction_version_at_cutoff(tmp_path):
    events = checkpoints() + [
        transaction(when="2025-01-05T10:00:00Z", amount=75, seq=4),
        event(
            "correction", "transaction", "2025-01-05T10:00:00Z", 5,
            {"account_id": "alice", "amount": 150, "cohort": "corrected"},
            tx="target", available="2025-01-05T11:00:00Z", supersedes="target",
        ),
        event(
            "future-correction", "transaction", "2025-01-05T10:00:00Z", 6,
            {"account_id": "alice", "amount": 900, "cohort": "future"},
            tx="target", available="2025-01-05T13:00:00Z", supersedes="correction",
        ),
    ]
    decision = Decision("target", "2025-01-05T12:00:00Z", 5, "f" * 64, 0.01, "approve")
    dataset = save_dataset(tmp_path, events, [decision], PROVENANCE)

    report = evaluate_run(tmp_path, dataset, "f" * 64)

    row = report["decisions"][0]
    assert row["amount"] == 150
    assert row["cohort"] == "corrected"
    assert row["status"] == "incomplete"
    assert row["replayed_action"] is row["candidate_action"] is None
    assert row["features"] == {}


@pytest.mark.parametrize(
    "capture,comparisons,unavailable,matches,mismatches,agreement,divergent",
    [
        ("absent", 0, 2, 0, 0, None, []),
        ("mixed", 1, 1, 1, 0, 1.0, []),
        ("zero", 2, 0, 1, 1, 0.5, ["target"]),
    ],
)
def test_baseline_feature_agreement_requires_captured_evidence(
    tmp_path, capture, comparisons, unavailable, matches, mismatches, agreement, divergent
):
    events = checkpoints() + [transaction(seq=4), transaction("second", seq=5, amount=50)]
    engine = TemporalEngine(events)
    store = ArtifactStore(tmp_path / "artifacts")
    policy = archive_policy(store)
    first = recorded(engine, store, policy, Cutoff(SUNDAY, 4))
    second = recorded(engine, store, policy, Cutoff(SUNDAY, 5), "second")
    first = replace(first, feature_values={"amount": 0} if capture == "zero" else {})
    if capture == "absent":
        second = replace(second, feature_values={})
    dataset = save_dataset(tmp_path, events, [first, second], PROVENANCE)

    report = evaluate_run(tmp_path, dataset, policy)

    for baseline in report["baselines"]:
        assert baseline["n"] == baseline["action_matches"] == 2
        assert baseline["action_agreement"] == 1.0
        assert baseline["feature_comparisons"] == comparisons
        assert baseline["feature_unavailable"] == unavailable
        assert baseline["feature_matches"] == matches
        assert baseline["feature_mismatches"] == mismatches
        assert baseline["feature_agreement"] == agreement
        assert baseline["divergent_transaction_ids"] == divergent


@pytest.mark.parametrize(
    "kind,field,value",
    [
        ("policies", None, []),
        ("policies", "features", []),
        ("policies", "schema_version", True),
        ("features", None, []),
        ("features", None, b"{"),
        ("rules", None, []),
        ("rules", "review_score", "not-a-number"),
        ("rules", "review_amount", True),
        ("rules", "decline_amount", float("nan")),
        ("rules", "review_velocity", 10**400),
        ("models", "weights", []),
        ("models", "weights", {"amount": False}),
        ("models", "weights", {"amount": float("inf")}),
        ("models", "bias", "not-a-number"),
    ],
)
def test_malformed_archive_returns_incomplete(tmp_path, kind, field, value):
    engine = TemporalEngine(checkpoints() + [transaction()])
    store = ArtifactStore(tmp_path / "artifacts")
    policy_hash = archive_policy(store)
    decision = recorded(engine, store, policy_hash)
    policy = store.get("policies", policy_hash)
    reference = "model" if kind == "models" else kind
    spec = policy if kind == "policies" else store.get(kind, policy[reference])
    invalid = {**spec, field: value} if field is not None else value
    # Imported bytes can be hash-consistent while violating an interpreter's contract.
    data = invalid if isinstance(invalid, bytes) else json.dumps(invalid).encode()
    key = hashlib.sha256(data).hexdigest()
    (store.root / kind / f"{key}.json").write_bytes(data)
    if kind != "policies":
        key = store.put("policies", {**policy, reference: key})

    result = replay(engine, store, replace(decision, policy_hash=key))

    assert result["status"] == "incomplete"
    assert result["action"] is result["score"] is None
    assert result["missing"]


@pytest.mark.parametrize("command", ["replay", "compare", "evaluate"])
@pytest.mark.parametrize("pointer", ['{"run_id":', "[]", '{"run_id": []}'])
def test_explicit_dataset_ignores_damaged_latest_pointer(tmp_path, capsys, command, pointer):
    events = checkpoints() + [transaction()]
    store = ArtifactStore(tmp_path / "artifacts")
    policy = archive_policy(store)
    decision = recorded(TemporalEngine(events), store, policy)
    dataset = save_dataset(tmp_path, events, [decision], PROVENANCE)
    (tmp_path / "latest.json").write_text(pointer)
    args = ["--data-dir", str(tmp_path), command]
    if command != "evaluate":
        args.append("target")
    args += ["--dataset", str(dataset)]
    if command != "replay":
        args += ["--candidate", policy]

    main(args)

    output = json.loads(capsys.readouterr().out)
    if command == "evaluate":
        assert output["summary"]["matched"] == 1
    else:
        assert (output if command == "replay" else output["original"])["status"] == "matched"
    assert (tmp_path / "latest.json").read_text() == pointer

    with pytest.raises(SystemExit) as error:
        main(["--data-dir", str(tmp_path), "replay", "target"])
    assert error.value.code == 2
    assert json.loads(capsys.readouterr().err)["command"] == "replay"
