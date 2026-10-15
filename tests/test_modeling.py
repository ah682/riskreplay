"""Independent chronological model fixtures; no generator oracle access."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import UTC, datetime, timedelta

import joblib
import numpy as np
import pytest
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from riskreplay.modeling import (
    FEATURE_NAMES,
    LeakageError,
    ModelingError,
    predict_model,
    train_models,
    validate_chronological_splits,
    validate_training_rows,
)


def observed_fixture(n: int = 720) -> list[dict]:
    """Owned, simple observed labels; distinct from the end-to-end demo generator."""
    rng = np.random.default_rng(231)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for index in range(n):
        decision = start + timedelta(hours=index)
        amount = round(float(rng.lognormal(5.2, 0.65)), 2)
        velocity = int(rng.integers(0, 7))
        flagged = int(index % 9 == 0)
        outage = int(index % 37 == 0)
        action = "decline" if index % 13 == 0 else "review" if flagged else "approve"
        label = int(flagged or (amount >= 250 and velocity >= 3))
        if index % 23 == 0:
            label = 1 - label
        available = (decision + timedelta(hours=2 + index % 5)).isoformat()
        if action == "decline" or index % 17 == 0:
            label, available = None, None
        rows.append(
            {
                "transaction_id": f"unit-{index:05d}",
                "decision_time": decision.isoformat(),
                "label": label,
                "label_available_at": available,
                "observed_action": action,
                "cohort": "new" if index % 3 == 0 else "returning",
                "amount": amount,
                "features": {
                    "amount": amount,
                    "velocity_1h": None if outage else velocity,
                    "velocity_amount_1h": None if outage else round(amount * velocity, 2),
                    "blocked": int(action == "decline"),
                    "flagged": flagged,
                    "outage": outage,
                },
            }
        )
    return rows


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    directory = tmp_path_factory.mktemp("trained-models")
    rows = observed_fixture()
    report = train_models(rows, directory, seed=17)
    return rows, directory, report


def test_real_cpu_estimators_and_archived_prediction(trained):
    _, root, report = trained
    assert set(report["models"]) == {"logistic", "gradient_boosted"}
    for name, info in report["models"].items():
        path = root / info["artifact_path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == info["file_hash"]
        model = joblib.load(path)
        if name == "logistic":
            classifier = model["base_estimator"].named_steps["classifier"]
            assert isinstance(classifier, LogisticRegression)
            assert np.any(np.abs(classifier.coef_) > 0.001)
        else:
            assert isinstance(model["base_estimator"], HistGradientBoostingClassifier)
            assert model["base_estimator"].n_iter_ >= 70
        test = report["test_rows"][4]
        assert predict_model(root, info["file_hash"], test["features"]) == pytest.approx(
            test["scores"][name], abs=1e-14
        )
        assert info["n_training"] >= 20
        assert len({row["scores"][name] for row in report["test_rows"]}) > 3
        assert info["calibration"]["n"] >= 30


def test_training_labels_are_available_before_validation_and_no_row_reuse(trained):
    source, _, report = trained
    by_id = {row["transaction_id"]: row for row in source}
    audit = report["training_audit"]
    train_ids = set(audit["training_transaction_ids"])
    tune_ids = set(audit["tuning_transaction_ids"])
    calibration_ids = set(audit["calibration_transaction_ids"])
    test_ids = set(report["splits"]["frozen_test_transaction_ids"])
    assert train_ids.isdisjoint(tune_ids | calibration_ids | test_ids)
    assert tune_ids.isdisjoint(calibration_ids | test_ids)
    assert calibration_ids.isdisjoint(test_ids)
    cutoff = datetime.fromisoformat(audit["training_label_cutoff_inclusive"])
    for transaction_id in train_ids:
        assert datetime.fromisoformat(by_id[transaction_id]["label_available_at"]) <= cutoff
    assert report["splits"]["train"]["immature"] > 0
    assert train_ids == set(audit["preprocessing_fit_transaction_ids"])


def test_preprocessing_statistics_are_from_training_only(trained):
    source, root, report = trained
    info = report["models"]["logistic"]
    bundle = joblib.load(root / info["artifact_path"])
    ids = set(report["training_audit"]["training_transaction_ids"])
    expected = np.asarray(
        [
            [
                (-1.0 if row["features"][name] is None else row["features"][name])
                for name in FEATURE_NAMES
            ]
            for row in source
            if row["transaction_id"] in ids
        ]
    )
    np.testing.assert_allclose(
        bundle["base_estimator"].named_steps["scaler"].mean_, expected.mean(0)
    )
    np.testing.assert_allclose(
        bundle["base_estimator"].named_steps["imputer"].statistics_, np.median(expected, axis=0)
    )


def test_repeat_runs_are_identical_including_artifact_bytes(trained, tmp_path):
    source, _, first = trained
    second = train_models(list(reversed(source)), tmp_path, seed=17)
    assert first == second
    json.dumps(second, allow_nan=False)


def test_changing_final_test_labels_and_features_cannot_change_fitted_artifacts(trained, tmp_path):
    source, _, first = trained
    mutated = copy.deepcopy(source)
    test_ids = set(first["splits"]["frozen_test_transaction_ids"])
    for row in mutated:
        if row["transaction_id"] in test_ids:
            row["amount"] = 1_000_000.0
            row["features"]["amount"] = row["amount"]
            row["features"]["flagged"] = 1 - row["features"]["flagged"]
            if row["label"] is not None:
                row["label"] = 1 - row["label"]
    second = train_models(mutated, tmp_path, seed=17)
    assert first["dataset_hash"] != second["dataset_hash"]
    assert first["splits"]["frozen_test_rows_hash"] != second["splits"]["frozen_test_rows_hash"]
    for name in first["models"]:
        assert first["models"][name]["file_hash"] == second["models"][name]["file_hash"]
    assert first["tuning"] == second["tuning"]


def test_later_evaluation_matures_labels_without_refitting(trained, tmp_path):
    source, _, first = trained
    last = datetime.fromisoformat(source[-1]["decision_time"])
    second = train_models(source, tmp_path, evaluation_cutoff=last + timedelta(days=7))
    assert second["splits"]["test"]["immature"] == 0
    assert second["splits"]["test"]["mature_observed"] > first["splits"]["test"]["mature_observed"]
    for name in first["models"]:
        assert first["models"][name]["file_hash"] == second["models"][name]["file_hash"]


def test_raw_denominators_maturity_and_capacity_are_recomputable(trained):
    _, _, report = trained
    rows = report["test_rows"]
    counts = report["splits"]["test"]
    assert counts["mature_observed"] + counts["immature"] + counts["declined_unobserved"] + counts[
        "unobserved"
    ] == len(rows)
    assert counts["declined_unobserved"] and counts["immature"] and counts["unobserved"]
    assert all(row["label"] is None for row in rows if row["label_status"] != "mature_observed")
    for name, info in {**report["models"], "rules": report["rules_baseline"]}.items():
        metrics = info["metrics"]
        selected = [r for r in rows if r["selected_for_review"][name]]
        known = [r for r in selected if r["label_status"] == "mature_observed"]
        fraud = sum(r["label"] == 1 for r in known)
        assert len(selected) == math.floor(0.10 * len(rows))
        assert metrics["review"]["precision_denominator"] == len(known)
        assert metrics["review"]["selected_unknown_outcomes"] == len(selected) - len(known)
        assert metrics["review"]["precision"] == pytest.approx(fraud / len(known))
        assert metrics["review"]["recall"] == pytest.approx(fraud / counts["observed_fraud"])
        assert sum(b["count"] for b in metrics["reliability_bins"]) == counts["mature_observed"]
        assert metrics["amount_weighted"]["observed_fraud_amount_denominator"] == pytest.approx(
            sum(r["amount"] for r in rows if r["label"] == 1)
        )
        assert sum(c["review"]["selected"] for c in info["cohorts"].values()) == len(selected)


def test_friday_fraud_cannot_enter_monday_training():
    row = observed_fixture(3)[1]
    row["decision_time"] = "2026-01-02T12:00:00Z"  # Friday
    row["label_available_at"] = "2026-01-09T12:00:00Z"  # next Friday
    row["label"] = 1
    with pytest.raises(LeakageError, match="unavailable at training cutoff"):
        validate_training_rows([row], "2026-01-05T12:00:00Z")
    validate_training_rows([row], "2026-01-09T12:00:00Z")


def test_intentionally_shuffled_and_overlapping_splits_are_rejected():
    rows = observed_fixture(12)
    validate_chronological_splits(rows[:4], rows[4:8], rows[8:])
    with pytest.raises(LeakageError, match="overlaps"):
        validate_chronological_splits([rows[0], rows[10]], rows[4:8], [rows[11]])
    with pytest.raises(LeakageError, match="reused"):
        validate_chronological_splits(rows[:4], rows[4:8], [rows[4], *rows[8:]])
    tied = copy.deepcopy(rows[4:8])
    tied[0]["decision_time"] = rows[3]["decision_time"]
    with pytest.raises(LeakageError, match="including ties"):
        validate_chronological_splits(rows[:4], tied, rows[8:])


@pytest.mark.parametrize("field", ["feature_available_at", "feature_event_time"])
def test_future_feature_provenance_is_rejected(field):
    row = observed_fixture(3)[1]
    row[field] = {"flagged": "2027-01-01T00:00:00Z"}
    with pytest.raises(LeakageError, match="after decision_time"):
        validate_training_rows([row], "2028-01-01T00:00:00Z")


def test_unknown_declined_and_oracle_labels_are_never_negatives(tmp_path):
    row = observed_fixture(3)[1]
    row["label"] = None
    with pytest.raises(LeakageError, match="unknown label"):
        validate_training_rows([row], "2026-02-01T00:00:00Z")
    row["label"] = 1
    row["observed_action"] = "decline"
    with pytest.raises(LeakageError, match="declined transaction"):
        validate_training_rows([row], "2026-02-01T00:00:00Z")
    rows = observed_fixture()
    rows[1]["oracle_label"] = 1
    with pytest.raises(LeakageError, match="oracle"):
        train_models(rows, tmp_path)


def test_missing_historical_features_fail_instead_of_imputing_known_state(tmp_path):
    rows = observed_fixture()
    del rows[3]["features"]["blocked"]
    with pytest.raises(ModelingError, match="missing historical feature 'blocked'"):
        train_models(rows, tmp_path)


def test_cached_prediction_still_verifies_integrity_and_no_path_traversal(trained, tmp_path):
    _, root, report = trained
    info = report["models"]["gradient_boosted"]
    features = report["test_rows"][0]["features"]
    destination = tmp_path / info["artifact_path"]
    destination.parent.mkdir()
    destination.write_bytes((root / info["artifact_path"]).read_bytes())
    predict_model(tmp_path, info["file_hash"], features)
    destination.write_bytes(b"corrupt historical model")
    with pytest.raises(ModelingError, match="hash mismatch"):
        predict_model(tmp_path, info["file_hash"], features)
    with pytest.raises(ModelingError, match="SHA-256"):
        predict_model(tmp_path, "../../outside", features)
    with pytest.raises(ModelingError, match="missing historical model"):
        predict_model(tmp_path, "0" * 64, features)


def test_modified_content_addressed_artifact_is_not_overwritten(trained, tmp_path):
    source, _, report = trained
    destination = tmp_path / report["models"]["logistic"]["artifact_path"]
    destination.parent.mkdir()
    destination.write_bytes(b"modified immutable artifact")
    with pytest.raises(ModelingError, match="refusing to overwrite"):
        train_models(source, tmp_path)
    assert destination.read_bytes() == b"modified immutable artifact"


def test_fractional_timestamps_are_sorted_as_times_not_strings(tmp_path):
    rows = observed_fixture()
    original = datetime.fromisoformat(rows[0]["decision_time"])
    rows[0]["decision_time"] = (original + timedelta(microseconds=500_000)).isoformat()
    extra = copy.deepcopy(rows[0])
    extra["transaction_id"] = "earliest-without-fraction"
    extra["decision_time"] = original.isoformat()
    report = train_models([*rows, extra], tmp_path)
    assert datetime.fromisoformat(report["splits"]["start_inclusive"]) == original


def test_no_mature_test_labels_reports_null_metrics_not_false_success(trained, tmp_path):
    source, _, report = trained
    rows = copy.deepcopy(source)
    test_ids = set(report["splits"]["frozen_test_transaction_ids"])
    for row in rows:
        if row["transaction_id"] in test_ids:
            row["label"] = None
            row["label_available_at"] = None
    result = train_models(rows, tmp_path)
    for name, info in result["models"].items():
        assert info["metrics"]["counts"]["mature_observed"] == 0
        assert info["metrics"]["average_precision"] is None
        assert info["metrics"]["pr_auc"] is None
        assert info["metrics"]["brier_score"] is None
        assert info["metrics"]["review"]["precision"] is None
        assert info["metrics"]["review"]["recall"] is None
        assert info["file_hash"] == report["models"][name]["file_hash"]
