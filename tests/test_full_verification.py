"""Further verification: temporal suffix invariance and split-time outcome history."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import joblib
import numpy as np
import pytest
from sklearn.calibration import CalibratedClassifierCV
from threadpoolctl import threadpool_limits

from riskreplay.artifacts import ArtifactStore
from riskreplay.engine import TemporalEngine
from riskreplay.modeling import train_models
from riskreplay.online import OnlineReference
from riskreplay.pipeline import model_rows
from riskreplay.policy import apply_rules, archive_policy, evaluate, replay, score_model
from riskreplay.schema import Cutoff, Decision, Event
from scripts.verify_models import verify_metrics


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
        source="full-verification-owned",
    )


def initial_history():
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


def transaction(eid, account, amount, time, seq, **kwargs):
    return event(
        eid,
        "transaction",
        time,
        seq,
        {"account_id": account, "amount": amount},
        tx=kwargs.pop("transaction_id", eid),
        **kwargs,
    )


def test_correction_chain_moves_account_without_resurrecting_prior_duplicates(tmp_path):
    when = "2026-01-02T11:30:00Z"
    first = transaction("prior", "alice", 30, when, 4)
    alice = transaction("alice-probe", "alice", 10, "2026-01-02T12:00:00Z", 5)
    bob = transaction("bob-probe", "bob", 10, "2026-01-02T12:00:00Z", 6)
    moved = transaction(
        "prior-v2",
        "bob",
        70,
        when,
        7,
        transaction_id="prior",
        available="2026-01-02T12:01:00Z",
        supersedes="prior",
    )
    latest = transaction(
        "prior-v3",
        "alice",
        90,
        when,
        9,
        transaction_id="prior",
        available="2026-01-02T12:03:00Z",
        supersedes="prior-v2",
    )
    deliveries = initial_history() + [
        first,
        alice,
        bob,
        moved,
        replace(first, available_at="2026-01-02T12:02:00Z", delivery_seq=8),
        latest,
        replace(moved, available_at="2026-01-02T12:04:00Z", delivery_seq=10),
    ]
    offline = TemporalEngine(list(reversed(deliveries)))
    online = OnlineReference()
    expected = {6: (30, 0), 7: (0, 70), 8: (0, 70), 9: (90, 0), 10: (90, 0)}
    for delivery in deliveries:
        online.observe(delivery)
        if delivery.delivery_seq not in expected:
            continue
        cutoff = Cutoff(delivery.available_at, delivery.delivery_seq)
        for txid, amount in zip(
            ("alice-probe", "bob-probe"), expected[delivery.delivery_seq], strict=True
        ):
            live = online.features(txid, cutoff)
            historical = offline.build(txid, cutoff, {"window_seconds": 3600})
            assert not historical["missing"]
            assert live == historical["features"]
            assert live["velocity_amount_1h"] == amount
            assert live["velocity_1h"] == int(amount > 0)
    # This is checked after every correction has arrived, against a fresh complete archive.
    historical = offline.build(
        "alice-probe", Cutoff(alice.available_at, 5), {"window_seconds": 3600}
    )
    assert historical["features"]["velocity_amount_1h"] == 30
    assert "prior-v3" not in historical["visible_ids"]


def test_arbitrary_future_suffix_cannot_change_an_archived_decision(tmp_path):
    tx = transaction("sunday", "alice", 80, "2026-01-04T12:00:00Z", 4)
    store = ArtifactStore(tmp_path)
    policy = archive_policy(store)
    base = initial_history() + [tx]
    cutoff = Cutoff(tx.available_at, 4)
    original = evaluate(TemporalEngine(base), store, "sunday", cutoff, policy)
    decision = Decision(
        "sunday",
        tx.available_at,
        4,
        policy,
        original["score"],
        original["action"],
        original["features"],
    )
    extensions = [
        event(
            "block-tuesday",
            "blocklist",
            "2026-01-06T09:00:00Z",
            5,
            {"account_id": "alice", "blocked": True},
        ),
        event(
            "late-flag",
            "flag",
            "2026-01-03T09:00:00Z",
            6,
            {"account_id": "alice", "flagged": True},
            available="2026-01-06T09:01:00Z",
        ),
        transaction(
            "late-prior", "alice", 25, "2026-01-04T11:59:00Z", 7, available="2026-01-06T09:02:00Z"
        ),
        transaction(
            "sunday-v2",
            "alice",
            1200,
            tx.event_time,
            8,
            transaction_id="sunday",
            available="2026-01-06T09:03:00Z",
            supersedes="sunday",
        ),
        replace(tx, available_at="2026-01-06T09:04:00Z", delivery_seq=9),
        event("future-outcome", "outcome", "2026-01-09T00:00:00Z", 10, {"label": 1}, tx="sunday"),
    ]
    for length in range(1, len(extensions) + 1):
        engine = TemporalEngine(list(reversed(base + extensions[:length])))
        reproduced = replay(engine, store, decision)
        assert reproduced["status"] == "matched"
        assert reproduced["features"] == original["features"]
        assert reproduced["provenance"] == original["provenance"]
        assert engine.label("sunday", "approve", cutoff)["label"] is None


def training_history(store, n=200):
    """Observed outcomes with an explicit independent online recording path."""
    start = datetime(2026, 1, 2, tzinfo=UTC)
    records = initial_history()
    sequence = 4
    for index in range(n):
        when = start + timedelta(hours=index)
        amount = float(40 + (index % 20) * 25)
        txid = f"fit-{index:03d}"
        records += [
            transaction(txid, f"account-{index % 8}", amount, when.isoformat(), sequence),
            event(
                f"label-{index:03d}",
                "outcome",
                (when + timedelta(minutes=15)).isoformat(),
                sequence + 1,
                {"label": int(index % 5 == 0)},
                tx=txid,
            ),
        ]
        sequence += 2
    policy = archive_policy(store)
    manifest = store.get("policies", policy)
    model = store.get("models", manifest["model"])
    rules = store.get("rules", manifest["rules"])
    online, decisions = OnlineReference(), []
    for delivery in records:
        online.observe(delivery)
        if delivery.event_type != "transaction":
            continue
        cutoff = Cutoff(delivery.available_at, delivery.delivery_seq)
        features = online.features(delivery.transaction_id, cutoff)
        score = score_model(store, model, features)
        action, _ = apply_rules(features, score, rules)
        decisions.append(
            Decision(
                delivery.transaction_id,
                cutoff.time,
                cutoff.sequence,
                policy,
                round(score, 12),
                action,
                features,
            )
        )
    return records, decisions


def test_future_outcome_correction_cannot_change_historical_fit_membership(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    events, decisions = training_history(store)
    evaluation_cutoff = "2026-01-11T00:00:00Z"
    before_rows = model_rows(TemporalEngine(events), store, decisions, evaluation_cutoff)
    before = train_models(before_rows, store.root)
    # Original positive label was mature on Jan2. Its later correction must not
    # disappear from (or change the target of) the Jan6/Jan7 historical fit set.
    correction = event(
        "label-000-v2",
        "outcome",
        "2026-01-09T00:00:00Z",
        10000,
        {"label": 0},
        tx="fit-000",
        supersedes="label-000",
    )
    after_rows = model_rows(
        TemporalEngine(events + [correction]), store, decisions, evaluation_cutoff
    )
    after = train_models(after_rows, store.root)
    assert (
        before["training_audit"]["training_transaction_ids"]
        == after["training_audit"]["training_transaction_ids"]
    )
    for name in before["models"]:
        assert before["models"][name]["file_hash"] == after["models"][name]["file_hash"]


def test_latest_outcome_correction_cannot_hide_evaluation_time_maturity(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    events, decisions = training_history(store)
    engine = TemporalEngine(events)
    label = engine.label(
        "fit-000", decisions[0].original_action, Cutoff("2026-01-03T00:00:00Z", 99999)
    )
    assert label["label"] == 1
    assert label["label_status"] == "mature"
    correction = event(
        "label-000-v2",
        "outcome",
        "2026-01-09T00:00:00Z",
        10000,
        {"label": 0},
        tx="fit-000",
        supersedes="label-000",
    )
    revised = TemporalEngine(events + [correction])
    assert (
        revised.label(
            "fit-000", decisions[0].original_action, Cutoff("2026-01-03T00:00:00Z", 99999)
        )
        == label
    )
    assert (
        revised.label(
            "fit-000", decisions[0].original_action, Cutoff("2026-01-10T00:00:00Z", 99999)
        )["label"]
        == 0
    )


def test_correction_before_training_cutoff_replaces_target_and_test_correction_stays_held_out(
    tmp_path,
):
    store = ArtifactStore(tmp_path / "artifacts")
    events, decisions = training_history(store)
    as_of = "2026-01-11T00:00:00Z"
    original = train_models(
        model_rows(TemporalEngine(events), store, decisions, as_of),
        store.root,
        evaluation_cutoff=as_of,
    )
    early = event(
        "label-000-v2",
        "outcome",
        "2026-01-03T00:00:00Z",
        10000,
        {"label": 0},
        tx="fit-000",
        supersedes="label-000",
    )
    revised = train_models(
        model_rows(TemporalEngine(events + [early]), store, decisions, as_of),
        store.root,
        evaluation_cutoff=as_of,
    )
    targets = {
        item["transaction_id"]: item for item in revised["training_audit"]["training_targets"]
    }
    assert targets["fit-000"]["label"] == 0
    assert datetime.fromisoformat(targets["fit-000"]["label_available_at"]) == datetime(
        2026, 1, 3, tzinfo=UTC
    )
    assert revised["models"]["logistic"]["file_hash"] != original["models"]["logistic"]["file_hash"]
    test_only = event(
        "label-190-v2",
        "outcome",
        "2026-01-10T12:00:00Z",
        10001,
        {"label": 0},
        tx="fit-190",
        supersedes="label-190",
    )
    held_out = train_models(
        model_rows(TemporalEngine(events + [test_only]), store, decisions, as_of),
        store.root,
        evaluation_cutoff=as_of,
    )
    assert (
        next(row for row in original["test_rows"] if row["transaction_id"] == "fit-190")["label"]
        == 1
    )
    assert (
        next(row for row in held_out["test_rows"] if row["transaction_id"] == "fit-190")["label"]
        == 0
    )
    for name in original["models"]:
        assert original["models"][name]["file_hash"] == held_out["models"][name]["file_hash"]
    assert all("label_history" not in row for row in held_out["test_rows"])


def test_calibration_preserves_base_estimator_and_raw_diagnostics(tmp_path, monkeypatch):
    original_fit = CalibratedClassifierCV.fit
    compared = []

    def audited_fit(self, features, labels, *args, **kwargs):
        base = self.estimator.estimator
        state_before = joblib.hash(base)
        predictions_before = base.predict_proba(features).copy()
        result = original_fit(self, features, labels, *args, **kwargs)
        assert joblib.hash(base) == state_before
        np.testing.assert_array_equal(base.predict_proba(features), predictions_before)
        compared.append(len(labels))
        return result

    monkeypatch.setattr(CalibratedClassifierCV, "fit", audited_fit)
    store = ArtifactStore(tmp_path / "artifacts")
    events, decisions = training_history(store, n=800)
    as_of = "2026-02-10T00:00:00Z"
    result = train_models(
        model_rows(TemporalEngine(events), store, decisions, as_of),
        store.root,
        evaluation_cutoff=as_of,
    )
    assert len(compared) == 2
    for name, model in result["models"].items():
        calibration = model["calibration"]
        assert calibration["prediction_folds"] == 2
        assert sum(calibration["class_counts"].values()) == calibration["n"]
        assert calibration["class_counts"]["1"] >= 3
        # Verify the separate uncalibrated diagnostics from the actual base model,
        # then recompute their metrics with the independent reference used by the
        # larger audit. This includes a fresh raw-score capacity allocation.
        bundle = joblib.load(store.root / model["artifact_path"])
        rows = result["test_rows"]
        matrix = np.asarray(
            [[row["features"][feature] for feature in bundle["feature_names"]] for row in rows]
        )
        with threadpool_limits(limits=1):
            expected = bundle["base_estimator"].predict_proba(matrix)[:, 1]
        np.testing.assert_array_equal(expected, [row["raw_scores"][name] for row in rows])
        raw_rows = [{**row, "scores": row["raw_scores"]} for row in rows]
        ordered = sorted(
            raw_rows,
            key=lambda row: (
                -row["scores"][name],
                datetime.fromisoformat(row["decision_time"]),
                row["transaction_id"],
            ),
        )
        selected = {row["transaction_id"] for row in ordered[: math.floor(0.1 * len(ordered))]}
        verify_metrics(raw_rows, model["raw_probability_metrics"], name, selected, len(rows))


@pytest.mark.parametrize("scope", ["blocklist", "flags", "velocity"])
def test_late_complete_checkpoint_cannot_repair_prior_missing_evidence(tmp_path, scope):
    initial = [item for item in initial_history() if item.payload["scope"] != scope]
    tx = transaction("probe", "alice", 25, "2026-01-04T12:00:00Z", 4)
    late = event(
        "late-proof",
        "checkpoint",
        "2026-01-01T00:00:00Z",
        5,
        {"scope": scope, "complete": True},
        available="2026-01-06T00:00:00Z",
    )
    store = ArtifactStore(tmp_path)
    result = evaluate(
        TemporalEngine(initial + [tx, late]),
        store,
        "probe",
        Cutoff(tx.available_at, 4),
        archive_policy(store),
    )
    assert result["score"] is None and result["action"] is None
    assert any(scope in reason for reason in result["missing"])
