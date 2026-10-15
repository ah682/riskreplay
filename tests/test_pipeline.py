"""Release gates across generation, fitting, persistence, comparison and exports."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from riskreplay.artifacts import ArtifactStore
from riskreplay.cli import main
from riskreplay.engine import TemporalEngine
from riskreplay.pipeline import demo, evaluate_run
from riskreplay.policy import replay
from riskreplay.storage import load_dataset, save_dataset


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    root = tmp_path_factory.mktemp("complete")
    return root, demo(root, n_transactions=320)


def test_end_to_end_release_and_raw_evidence(completed):
    root, report = completed
    assert report["integrity"]["failed"] == 0
    assert report["integrity"]["online_offline"]["matched"] == 320
    assert report["integrity"]["online_offline"]["mismatched_or_unavailable_ids"] == []
    assert (
        report["config"]["recording_reference"]["implementation"]
        == "independent_delivery_order_reference_v1"
    )
    assert report["summary"]["matched"] == 318
    assert report["summary"]["mismatched"] == report["summary"]["incomplete"] == 1
    assert report["summary"]["changed"] > 0
    assert report["summary"]["declined_unobserved"] > 0
    assert report["summary"]["immature"] > 0
    faults = report["integrity"]["fault_experiment"]
    assert (faults["true_positives"], faults["false_negatives"], faults["false_positives"]) == (
        4,
        0,
        0,
    )
    folder = root / "runs" / report["run_id"]
    for name in (
        "report.json",
        "report.html",
        "decisions.csv",
        "evaluation.json",
        "integrity.json",
    ):
        assert (folder / name).stat().st_size > 100
    assert "oracle_label" not in (folder / "report.json").read_text()
    with sqlite3.connect(root / "index.sqlite") as connection:
        assert connection.execute("select count(*) from decisions").fetchone()[0] == 320
        assert connection.execute("pragma user_version").fetchone()[0] == 1
    for model in report["evaluation"]["models"].values():
        assert model["n_training"] > 20
        metric = model["metrics"]
        assert (
            metric["counts"]["mature_observed"]
            + metric["counts"]["immature"]
            + metric["counts"]["declined_unobserved"]
            + metric["counts"]["unobserved"]
            == metric["counts"]["total"]
        )
        assert 0 <= metric["pr_auc"] <= 1
        assert (
            metric["review"]["selected"]
            == metric["review"]["selected_mature_observed"]
            + metric["review"]["selected_unknown_outcomes"]
        )


def test_parquet_roundtrip_replays_complete_and_incomplete(completed):
    root, report = completed
    latest = json.loads((root / "latest.json").read_text())
    events, decisions, manifest = load_dataset(root / latest["dataset"])
    assert manifest["dataset_hash"] == report["dataset_hash"]
    engine, store = TemporalEngine(events), ArtifactStore(root / "artifacts")
    for transaction_id, status in (
        ("t-sunday", "matched"),
        ("t-monday", "mismatched"),
        ("t-after-outage", "incomplete"),
    ):
        result = replay(
            engine, store, next(d for d in decisions if d.transaction_id == transaction_id)
        )
        assert result["status"] == status
    declined_ids = {d.transaction_id for d in decisions if d.original_action == "decline"}
    assert not any(e.event_type == "outcome" and e.transaction_id in declined_ids for e in events)


def test_clean_runs_identical_decisions_metrics_artifact_bytes(completed, tmp_path):
    _, first = completed
    second = demo(tmp_path, n_transactions=320)
    assert second["dataset_hash"] == first["dataset_hash"]
    assert second["semantic_hash"] == first["semantic_hash"]
    assert second["decisions"] == first["decisions"]
    assert second["evaluation"] == first["evaluation"]


def test_evaluation_reuses_same_information_and_does_not_overwrite_demo(completed):
    root, original = completed
    latest = json.loads((root / "latest.json").read_text())
    rerun = evaluate_run(
        root,
        root / latest["dataset"],
        latest["candidate_policy"],
        evaluation=original["evaluation"],
    )
    assert rerun["summary"] == original["summary"]
    assert rerun["decisions"] == original["decisions"]
    assert (
        rerun["run_id"] != original["run_id"]
    )  # Includes whether pristine pre-fault recording was audited.


def test_import_without_training_or_duplicates_does_not_claim_false_failures(completed):
    root, original = completed
    latest = json.loads((root / "latest.json").read_text())
    events, decisions, manifest = load_dataset(root / latest["dataset"])
    unique = {}
    for event in sorted(events, key=lambda event: event.delivery_key):
        unique.setdefault(event.event_id, event)
    dataset = save_dataset(root, list(unique.values()), decisions, manifest["provenance"])
    report = evaluate_run(root, dataset, latest["candidate_policy"])
    checks = {check["name"]: check for check in report["integrity"]["checks"]}
    assert checks["Duplicate deliveries retained and deduplicated"]["passed"] is True
    assert checks["Training targets available before training cutoff"]["status"] == "unavailable"
    assert checks["Training targets available before training cutoff"]["passed"] is None
    assert report["integrity"]["failed"] == 0
    assert report["integrity"]["unavailable"] == 1
    assert report["integrity"]["online_offline"]["status"] == "unavailable"
    assert report["summary"] == original["summary"]


def test_cli_failure_is_actionable_and_reset_refuses_unowned(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        main(["--data-dir", str(tmp_path), "replay", "missing"])
    assert error.value.code == 2
    assert "No dataset selected" in capsys.readouterr().err
    preserve = tmp_path / "user.txt"
    preserve.write_text("preserve me")
    with pytest.raises(SystemExit):
        main(["--data-dir", str(tmp_path), "reset", "--yes"])
    assert preserve.read_text() == "preserve me"


def test_viewer_revision_creates_new_inspector_without_rewriting_history(
    completed, tmp_path, monkeypatch
):
    from riskreplay import pipeline, reporting

    root, original = completed
    latest = json.loads((root / "latest.json").read_text())
    source = tmp_path / "riskreplay"
    shutil.copytree(
        Path(pipeline.__file__).parent, source, ignore=shutil.ignore_patterns("__pycache__")
    )
    monkeypatch.setattr(pipeline, "__file__", str(source / "pipeline.py"))
    monkeypatch.setattr(reporting, "__file__", str(source / "reporting.py"))
    before = evaluate_run(
        root,
        root / latest["dataset"],
        latest["candidate_policy"],
        evaluation=original["evaluation"],
    )
    old_folder = root / "runs" / before["run_id"]
    old_bytes = {path.name: path.read_bytes() for path in old_folder.iterdir()}
    stylesheet = source / "static" / "styles.css"
    revision = "\n/* verified viewer revision */\n.metric-ratio { color: #000; }\n"
    stylesheet.write_text(stylesheet.read_text() + revision)
    after = evaluate_run(
        root,
        root / latest["dataset"],
        latest["candidate_policy"],
        evaluation=original["evaluation"],
    )
    assert after["run_id"] != before["run_id"]
    assert after["run_identity"]["presentation_hash"] != before["run_identity"]["presentation_hash"]
    for key in ("dataset_hash", "decisions", "evaluation", "summary"):
        assert after[key] == before[key]
    assert {path.name: path.read_bytes() for path in old_folder.iterdir()} == old_bytes
    assert revision in (root / "runs" / after["run_id"] / "inspector.html").read_text()
