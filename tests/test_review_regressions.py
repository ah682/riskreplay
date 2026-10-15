"""Review regressions for ownership and fixed-window evidence coverage."""

from dataclasses import replace

import pytest
from test_full_verification import training_history

from riskreplay.artifacts import ArtifactStore
from riskreplay.engine import TemporalEngine
from riskreplay.modeling import LeakageError, train_models, validate_training_rows
from riskreplay.pipeline import demo, model_rows
from scripts.verify_models import verify_metrics


def test_failed_demo_cannot_claim_unrelated_directory(tmp_path):
    note = tmp_path / "unrelated-note.txt"
    note.write_text("keep this")
    with pytest.raises(ValueError):
        demo(tmp_path, n_transactions=1)
    assert note.read_text() == "keep this"
    assert not (tmp_path / ".riskreplay-owned").exists()


def test_demo_refuses_populated_unowned_directory_even_with_valid_arguments(tmp_path):
    note = tmp_path / "unrelated-note.txt"
    note.write_text("keep this")
    with pytest.raises(ValueError, match="unowned"):
        demo(tmp_path, n_transactions=80)
    assert list(tmp_path.iterdir()) == [note]


def test_invalid_demo_does_not_create_owned_directory(tmp_path):
    root = tmp_path / "not-created"
    with pytest.raises(ValueError):
        demo(root, n_transactions=1)
    assert not root.exists()


def test_demo_refuses_symlink_root(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        demo(link, n_transactions=80)
    assert not list(target.iterdir())


@pytest.mark.parametrize("missing_indices", [range(160, 200), range(180, 200), (0, 25, 130, 199)])
def test_missing_state_keeps_frozen_windows_and_denominators(tmp_path, missing_indices):
    store = ArtifactStore(tmp_path / "artifacts")
    events, decisions = training_history(store)
    missing_ids = {f"fit-{index:03d}" for index in missing_indices}
    selected = [
        replace(decision, policy_hash="f" * 64)
        if decision.transaction_id in missing_ids
        else decision
        for decision in decisions
    ]
    rows = model_rows(TemporalEngine(events), store, selected, "2026-01-11T00:00:00Z")
    assert len(rows) == 200
    evaluation = train_models(rows, store.root, evaluation_cutoff="2026-01-11T00:00:00Z")
    splits = evaluation["splits"]
    assert splits["test_start_inclusive"] == "2026-01-08T15:12:00Z"
    assert splits["test_end_inclusive"] == "2026-01-10T07:00:00Z"
    assert splits["frozen_test_transaction_ids"] == [f"fit-{i:03d}" for i in range(160, 200)]
    missing_test = {txid for txid in missing_ids if int(txid[4:]) >= 160}
    assert splits["test"]["total"] == 40
    assert splits["test"]["missing_state"] == len(missing_test)
    assert set(splits["test"]["missing_state_transaction_ids"]) == missing_test
    audit = evaluation["training_audit"]
    for group in (
        "training_transaction_ids",
        "tuning_transaction_ids",
        "calibration_transaction_ids",
    ):
        assert not missing_ids.intersection(audit[group])
    for row in evaluation["test_rows"]:
        missing = row["transaction_id"] in missing_test
        assert bool(row["missing_state"]) == missing
        if missing:
            assert all(score is None for score in row["scores"].values())
            assert not any(row["selected_for_review"].values())
    for name, info in {**evaluation["models"], "rules": evaluation["rules_baseline"]}.items():
        metrics = info["metrics"]
        assert metrics["counts"]["total"] == 40
        assert metrics["counts"]["mature_observed"] == 40
        assert metrics["metric_n"] == 40 - len(missing_test)
        assert metrics["review"]["capacity_denominator_all_test_transactions"] == 40
        assert metrics["review"]["capacity_slots_global"] == 4
        assert metrics["review"]["selected"] == min(4, 40 - len(missing_test))
        if len(missing_test) == 40:
            assert metrics["brier_score"] is None
            assert metrics["average_precision"] is None
        selected_ids = {
            row["transaction_id"]
            for row in evaluation["test_rows"]
            if row["selected_for_review"][name]
        }
        assert verify_metrics(evaluation["test_rows"], metrics, name, selected_ids, 40) > 60


def test_missing_state_cannot_be_passed_as_a_fit_row(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    events, decisions = training_history(store)
    rows = model_rows(TemporalEngine(events), store, decisions, "2026-01-11T00:00:00Z")
    rows[0]["missing_state"] = ["historical flags unavailable"]
    with pytest.raises(LeakageError, match="historical"):
        validate_training_rows(rows[:1], "2026-01-07T00:00:00Z")


def test_missing_transaction_keeps_its_window_without_guessing_its_features(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    events, decisions = training_history(store)
    events = [event for event in events if event.transaction_id != "fit-199"]
    rows = model_rows(TemporalEngine(events), store, decisions, "2026-01-11T00:00:00Z")
    assert len(rows) == 200
    last = rows[-1]
    assert last["missing_state"]
    assert last["amount"] is None
    assert last["features"] == {}
    result = train_models(rows, store.root, evaluation_cutoff="2026-01-11T00:00:00Z")
    assert result["splits"]["test_end_inclusive"] == "2026-01-10T07:00:00Z"
    assert result["splits"]["test"]["unobserved"] == 1
    assert result["splits"]["test"]["missing_state"] == 1
    assert result["models"]["logistic"]["metrics"]["metric_n"] == 39
