"""Independent delivery audit: real CLI processes, imports, storage, and exports.

All inputs are regenerated owned fixtures in temporary directories. These tests
never read, replace, or reset the user's saved demonstration or partner records.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from riskreplay.artifacts import ArtifactStore
from riskreplay.generator import generate, observe_outcomes
from riskreplay.online import OnlineReference
from riskreplay.policy import apply_rules, archive_policy, score_model
from riskreplay.reporting import save_report
from riskreplay.schema import ContractError, Cutoff, Decision, Event, digest
from riskreplay.storage import load_dataset, save_dataset
from riskreplay.web import create_app

REPOSITORY = Path(__file__).resolve().parents[1]


class _ASGIClient:
    """Run the real application without the sandbox-blocked background portal."""

    def __init__(self, app):
        self.app = app

    def get(self, path):
        async def request():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(path)

        return asyncio.run(request())


def cli(root, *arguments):
    return subprocess.run(
        [sys.executable, "-m", "riskreplay", "--data-dir", str(root), *map(str, arguments)],
        cwd=REPOSITORY,
        env={
            **os.environ,
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def jsonl(path, rows):
    path.write_text("".join(json.dumps(row, allow_nan=False) + "\n" for row in rows))


@pytest.fixture(scope="module")
def fresh_owned_source(tmp_path_factory):
    root = tmp_path_factory.mktemp("owned-delivery-source")
    store = ArtifactStore(root / "artifacts")
    policy = archive_policy(store, name="Independent delivery audit original")
    candidate = archive_policy(store, name="Independent delivery audit candidate", review_amount=50)
    manifest = store.get("policies", policy)
    feature_spec = store.get("features", manifest["features"])
    rules = store.get("rules", manifest["rules"])
    model = store.get("models", manifest["model"])
    simulation = generate(seed=29, n_transactions=64)
    online = OnlineReference()
    decisions = []
    recorded = set()
    for row in simulation["events"]:
        event = Event(**row)
        online.observe(event)
        if (
            event.event_type != "transaction"
            or event.supersedes
            or event.transaction_id in recorded
        ):
            continue
        recorded.add(event.transaction_id)
        cutoff = Cutoff(event.available_at, event.delivery_seq)
        features = online.features(event.transaction_id, cutoff, feature_spec["window_seconds"])
        score = score_model(store, model, features)
        action, _ = apply_rules(features, score, rules)
        decisions.append(
            Decision(
                event.transaction_id,
                cutoff.time,
                cutoff.sequence,
                policy,
                round(score, 12),
                action,
                features,
            )
        )
    observed = observe_outcomes(
        simulation["events"],
        [d.transaction_id for d in decisions if d.original_action == "decline"],
    )
    events = [Event(**row) for row in observed]
    provenance = {
        "kind": "owned_synthetic",
        "source": "Independent CLI verification / regenerated seed 29",
        "permission": "Project-owned synthetic fixtures; no partner records used",
        "config": simulation["config"],
    }
    jsonl(root / "events.jsonl", [event.to_dict() for event in events])
    jsonl(root / "decisions.jsonl", [decision.to_dict() for decision in decisions])
    (root / "provenance.json").write_text(json.dumps(provenance))
    return {
        "root": root,
        "events": events,
        "decisions": decisions,
        "provenance": provenance,
        "policy": policy,
        "candidate": candidate,
    }


def import_owned(source, destination, *, events=None, decisions=None, provenance=None):
    return cli(
        destination,
        "import",
        "--events",
        events or source["root"] / "events.jsonl",
        "--decisions",
        decisions or source["root"] / "decisions.jsonl",
        "--provenance",
        provenance or source["root"] / "provenance.json",
    )


@pytest.fixture
def imported(fresh_owned_source, tmp_path):
    result = import_owned(fresh_owned_source, tmp_path)
    assert result.returncode == 0, result.stderr
    dataset = Path(json.loads(result.stdout)["dataset"])
    shutil.copytree(fresh_owned_source["root"] / "artifacts", tmp_path / "artifacts")
    return fresh_owned_source, tmp_path, dataset


def test_actual_cli_import_and_parquet_json_roundtrip_are_exact(imported):
    source, root, dataset = imported
    events, decisions, manifest = load_dataset(dataset)
    assert [e.to_dict() for e in events] == [e.to_dict() for e in source["events"]]
    assert [d.to_dict() for d in decisions] == [d.to_dict() for d in source["decisions"]]
    assert manifest["provenance"] == source["provenance"]
    normalized = {
        "events": [e.to_dict() for e in events],
        "decisions": [d.to_dict() for d in decisions],
        "provenance": manifest["provenance"],
    }
    assert digest(normalized) == manifest["dataset_hash"] == dataset.name
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in dataset.iterdir()}
    again = import_owned(source, root)
    assert again.returncode == 0, again.stderr
    assert Path(json.loads(again.stdout)["dataset"]) == dataset
    assert before == {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in dataset.iterdir()
    }
    assert not list((root / "datasets").glob(".writing-*"))


def test_real_cli_replay_compare_and_two_policy_selection(imported):
    source, root, dataset = imported
    replay = cli(root, "replay", "t-sunday", "--dataset", dataset)
    assert replay.returncode == 0, replay.stderr
    result = json.loads(replay.stdout)
    assert result["status"] == "matched"
    assert result["action"] == "approve"
    assert result["features"]["blocked"] == 0
    assert "visible_ids" not in result
    compared = cli(
        root, "compare", "t-sunday", "--dataset", dataset, "--candidate", source["candidate"]
    )
    assert compared.returncode == 0, compared.stderr
    result = json.loads(compared.stdout)
    assert result["changed"] is True
    assert result["candidate"]["action"] == "review"
    assert result["original"]["status"] == "matched"
    assert "Equivalent original available facts" in result["information_regime"]
    same = cli(
        root,
        "compare",
        "t-sunday",
        "--dataset",
        dataset,
        "--policy-a",
        source["candidate"],
        "--candidate",
        source["candidate"],
    )
    assert same.returncode == 0, same.stderr
    result = json.loads(same.stdout)
    assert result["changed"] is False
    assert result["original"]["action"] == result["candidate"]["action"] == "review"


def test_import_without_archived_artifacts_is_incomplete_not_fabricated(
    fresh_owned_source,
    tmp_path,
):
    result = import_owned(fresh_owned_source, tmp_path)
    assert result.returncode == 0, result.stderr
    dataset = json.loads(result.stdout)["dataset"]
    replay = cli(tmp_path, "replay", "t-sunday", "--dataset", dataset)
    assert replay.returncode == 0, replay.stderr
    state = json.loads(replay.stdout)
    assert state["status"] == "incomplete"
    assert state["action"] is None and state["score"] is None
    assert any("policies artifact" in reason for reason in state["missing"])
    assert not (tmp_path / "artifacts").exists()


def test_missing_trusted_trained_model_does_not_fall_back_to_fixture(imported):
    source, root, _ = imported
    store = ArtifactStore(root / "artifacts")
    unavailable = archive_policy(store, model={"type": "sklearn", "file_hash": "f" * 64})
    decisions = [
        replace(row, policy_hash=unavailable) if row.transaction_id == "t-sunday" else row
        for row in source["decisions"]
    ]
    dataset = save_dataset(root, source["events"], decisions, source["provenance"])
    result = cli(root, "replay", "t-sunday", "--dataset", dataset)
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout)
    assert state["status"] == "incomplete"
    assert state["action"] is None and state["score"] is None
    assert any("trained model" in reason for reason in state["missing"])


def test_cli_evaluate_exports_exact_columns_and_original_json_evidence(imported):
    source, root, dataset = imported
    result = cli(root, "evaluate", "--dataset", dataset, "--candidate", source["candidate"])
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["summary"]["matched"] == 64
    assert output["summary"]["incomplete"] == output["summary"]["mismatched"] == 0
    folder = Path(output["report"]).parent
    report = json.loads((folder / "report.json").read_text())
    assert report["summary"] == output["summary"]
    assert report["evaluation"]["models"] == {}
    assert report["evaluation"]["mode"] == "not_trained_for_this_import"
    assert "oracle_label" not in (folder / "report.json").read_text()
    with (folder / "decisions.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(report["decisions"]) == 64
    for csv_row, evidence in zip(rows, report["decisions"], strict=True):
        for column, value in csv_row.items():
            expected = evidence[column]
            assert value == ("" if expected is None else str(expected)), column
    bundle = (folder / "inspector.html").read_text()
    embedded = re.search(
        r'<script type="application/json" id="riskreplay-bundle">(.*?)</script>',
        bundle,
        re.S,
    )
    assert embedded is not None
    assert json.loads(embedded.group(1)) == report
    assert json.loads((folder / "evaluation.json").read_text()) == report["evaluation"]
    assert json.loads((folder / "integrity.json").read_text()) == report["integrity"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_time", None),
        ("available_at", 7),
        ("event_time", "not-a-date"),
        ("payload_hash", "0" * 64),
        ("event_id", 7),
        ("schema_version", True),
        ("schema_version", 1.0),
    ],
)
def test_invalid_event_import_has_line_context_json_error_and_no_partial_bundle(
    fresh_owned_source,
    tmp_path,
    field,
    value,
):
    rows = [event.to_dict() for event in fresh_owned_source["events"]]
    rows[1] = {**rows[1], field: value}
    bad = tmp_path / "bad-events.jsonl"
    jsonl(bad, rows)
    result = import_owned(fresh_owned_source, tmp_path / "destination", events=bad)
    assert result.returncode == 2
    error = json.loads(result.stderr)
    assert error["command"] == "import"
    assert "bad-events.jsonl:line 2" in error["error"]
    assert not (tmp_path / "destination" / "datasets").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("decision_time", None),
        ("original_score", True),
        ("schema_version", True),
        ("feature_values", None),
        ("feature_values", []),
        ("feature_values", {"amount": True}),
        ("feature_values", {"amount": "not-numeric"}),
    ],
)
def test_invalid_decision_import_is_rejected_before_persistence(
    fresh_owned_source,
    tmp_path,
    field,
    value,
):
    rows = [decision.to_dict() for decision in fresh_owned_source["decisions"]]
    rows[0] = {**rows[0], field: value}
    bad = tmp_path / "bad-decisions.jsonl"
    jsonl(bad, rows)
    result = import_owned(fresh_owned_source, tmp_path / "destination", decisions=bad)
    assert result.returncode == 2
    error = json.loads(result.stderr)
    assert "bad-decisions.jsonl:line 1" in error["error"]
    assert not (tmp_path / "destination" / "datasets").exists()


def test_zero_recorded_features_are_evidence_while_empty_mapping_is_optional(imported):
    source, root, _ = imported
    original = next(d for d in source["decisions"] if d.transaction_id == "t-sunday")
    for feature_values, expected in [
        ({}, "matched"),
        ({**original.feature_values, "amount": 0}, "mismatched"),
    ]:
        decisions = [
            replace(d, feature_values=feature_values) if d == original else d
            for d in source["decisions"]
        ]
        dataset = save_dataset(root, source["events"], decisions, source["provenance"])
        result = cli(root, "replay", "t-sunday", "--dataset", dataset)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["status"] == expected


@pytest.mark.parametrize("failure", ["malformed_json", "empty", "duplicate_identity", "provenance"])
def test_other_invalid_cli_inputs_fail_actionably(fresh_owned_source, tmp_path, failure):
    events = tmp_path / "events.jsonl"
    shutil.copyfile(fresh_owned_source["root"] / "events.jsonl", events)
    provenance = tmp_path / "provenance.json"
    shutil.copyfile(fresh_owned_source["root"] / "provenance.json", provenance)
    if failure == "malformed_json":
        events.write_text(events.read_text().splitlines()[0] + "\n{invalid json}\n")
    elif failure == "empty":
        events.write_text("")
    elif failure == "duplicate_identity":
        rows = [event.to_dict() for event in fresh_owned_source["events"]]
        conflict = {**rows[0], "source": "changed-identity", "delivery_seq": 99999}
        jsonl(events, [*rows, conflict])
    else:
        provenance.write_text(json.dumps({"kind": "owned_synthetic", "source": "no-permission"}))
    result = import_owned(
        fresh_owned_source, tmp_path / "destination", events=events, provenance=provenance
    )
    assert result.returncode == 2
    assert json.loads(result.stderr)["error"]
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "destination" / "datasets").exists()


@pytest.mark.parametrize("name", ["events.parquet", "decisions.parquet"])
def test_content_addressed_bundle_rejects_changed_file_bytes(imported, name):
    _, _, dataset = imported
    path = dataset / name
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(ContractError, match="checksum changed"):
        load_dataset(dataset)


@pytest.mark.parametrize("counter", ["event_deliveries", "event_identities", "decision_count"])
def test_manifest_counts_are_validated_against_records(imported, counter):
    _, _, dataset = imported
    path = dataset / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest[counter] += 999
    path.write_text(json.dumps(manifest))
    with pytest.raises(ContractError, match="(?i)(count|manifest|metadata)"):
        load_dataset(dataset)


def test_manifest_provenance_is_covered_by_normalized_hash(imported):
    _, _, dataset = imported
    path = dataset / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["provenance"]["source"] = "unrelated source substitution"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ContractError, match="content hash"):
        load_dataset(dataset)


def report_fixture(transaction_ids):
    return {
        "run_id": "owned-export-audit",
        "mode": "owned_synthetic",
        "information_regime": "Owned audit fixture; no merchant validation",
        "summary": {
            "matched": len(transaction_ids),
            "mismatched": 0,
            "incomplete": 0,
            "total": len(transaction_ids),
            "changed": 0,
        },
        "decisions": [
            {
                "transaction_id": txid,
                "decision_time": "2025-01-05T12:00:00Z",
                "status": "matched",
                "recorded_action": "approve",
                "replayed_action": "approve",
                "candidate_action": "approve",
                "original_score": 0.01,
                "candidate_score": 0.01,
                "label_status": "unobserved",
                "first_divergence": None,
            }
            for txid in transaction_ids
        ],
        "evaluation": {"models": {}},
        "integrity": {"checks": []},
        "dataset_hash": "a" * 64,
        "config": {},
        "performance": {},
    }


def test_html_and_json_exports_escape_untrusted_transaction_and_config_strings(tmp_path):
    hostile = '</script><img src=x onerror="alert(1)">' + '\nComma, quote" & unicode £'
    report = report_fixture([hostile])
    report["config"]["source_description"] = hostile
    folder = save_report(tmp_path, report)
    rendered = (folder / "report.html").read_text()
    assert hostile not in rendered
    assert html.escape(hostile) in rendered
    bundle = (folder / "inspector.html").read_text()
    assert hostile not in bundle
    embedded = re.search(
        r'<script type="application/json" id="riskreplay-bundle">(.*?)</script>',
        bundle,
        re.S,
    )
    assert embedded is not None
    assert json.loads(embedded.group(1)) == report
    assert json.loads((folder / "report.json").read_text()) == report
    with (folder / "decisions.csv").open(newline="") as handle:
        assert list(csv.DictReader(handle))[0]["transaction_id"] == hostile


def test_csv_formula_neutralization_is_explicit_and_json_remains_lossless(tmp_path):
    identifiers = ["=SUM(1,2)", "+1+2", "-1+2", "@SUM(1,2)", "\t=1+2", "\r=1+2"]
    report = report_fixture(identifiers)
    folder = save_report(tmp_path, report)
    with (folder / "decisions.csv").open(newline="") as handle:
        csv_ids = [row["transaction_id"] for row in csv.DictReader(handle)]
    assert csv_ids == ["'" + txid for txid in identifiers]
    original_ids = [
        row["transaction_id"]
        for row in json.loads((folder / "report.json").read_text())["decisions"]
    ]
    assert original_ids == identifiers


def test_existing_report_cannot_hide_modified_semantics_behind_stale_hash(tmp_path):
    report = report_fixture(["owned-transaction"])
    folder = save_report(tmp_path, report)
    before = json.loads((folder / "report.json").read_text())
    before["summary"]["matched"] = 999
    (folder / "report.json").write_text(json.dumps(before))
    with pytest.raises(ValueError, match="(?i)(integrity|hash|semantic)"):
        save_report(tmp_path, report)


@pytest.mark.parametrize("tamper", ["changed_summary", "removed_semantic_hash"])
def test_api_rejects_modified_report_and_removed_semantic_hash(tmp_path, tamper):
    report = report_fixture(["owned-transaction"])
    folder = save_report(tmp_path, report)
    modified = json.loads((folder / "report.json").read_text())
    if tamper == "changed_summary":
        modified["summary"]["matched"] = 999
    else:
        modified.pop("semantic_hash")
    (folder / "report.json").write_text(json.dumps(modified))
    client = _ASGIClient(create_app(tmp_path))
    for endpoint in [
        f"/api/runs/{report['run_id']}",
        f"/api/runs/{report['run_id']}/export?format=json",
    ]:
        response = client.get(endpoint)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_report"
    listing = client.get("/api/runs").json()
    assert listing["runs"] == []
    assert listing["unavailable"][0]["run_id"] == report["run_id"]


@pytest.mark.parametrize(
    "filename",
    [
        "decisions.csv",
        "evaluation.json",
        "integrity.json",
        "report.html",
        "inspector.html",
    ],
)
@pytest.mark.parametrize("tamper", ["modified", "removed"])
def test_generated_export_artifacts_are_checked_before_run_reuse(tmp_path, filename, tamper):
    report = report_fixture(["owned-transaction"])
    folder = save_report(tmp_path, report)
    manifest = json.loads((folder / "manifest.json").read_text())
    assert len(manifest["files"]) == 6
    path = folder / filename
    if tamper == "modified":
        path.write_bytes(path.read_bytes() + b"\nforged export")
    else:
        path.unlink()
    with pytest.raises(ValueError, match="(?i)(artifact|checksum|integrity)"):
        save_report(tmp_path, report)


@pytest.mark.parametrize(
    "filename,format_name", [("decisions.csv", "csv"), ("report.html", "html")]
)
def test_api_never_serves_export_whose_manifest_checksum_changed(tmp_path, filename, format_name):
    report = report_fixture(["owned-transaction"])
    folder = save_report(tmp_path, report)
    path = folder / filename
    path.write_bytes(path.read_bytes() + b"\nforged export")
    response = _ASGIClient(create_app(tmp_path)).get(
        f"/api/runs/{report['run_id']}/export?format={format_name}"
    )
    assert response.status_code == 422
    assert "forged export" not in response.text


def test_cli_evaluate_does_not_consume_modified_evaluation_sidecar(imported):
    source, root, dataset = imported
    first = cli(root, "evaluate", "--dataset", dataset, "--candidate", source["candidate"])
    assert first.returncode == 0, first.stderr
    summary = json.loads(first.stdout)
    folder = Path(summary["report"]).parent
    canonical = json.loads((folder / "report.json").read_text())
    (root / "latest.json").write_text(
        json.dumps(
            {
                "run_id": summary["run_id"],
                "dataset": str(dataset.relative_to(root)),
                "candidate_policy": source["candidate"],
            }
        )
    )
    forged = {**canonical["evaluation"], "mode": "forged-evaluation-sidecar"}
    (folder / "evaluation.json").write_text(json.dumps(forged))
    result = cli(root, "evaluate")
    # Rejecting a corrupt run or deriving evidence only from the verified
    # canonical report are both valid. Consuming the forged sidecar is not.
    if result.returncode == 2:
        assert any(
            word in json.loads(result.stderr)["error"].lower()
            for word in ("checksum", "integrity", "artifact")
        )
    else:
        assert result.returncode == 0, result.stderr
        output_folder = Path(json.loads(result.stdout)["report"]).parent
        report = json.loads((output_folder / "report.json").read_text())
        assert report["evaluation"] == canonical["evaluation"]


@pytest.mark.parametrize("shape", [None, [], "not-an-object"])
def test_provenance_requires_an_object_with_an_actionable_cli_error(
    fresh_owned_source,
    tmp_path,
    shape,
):
    bad = tmp_path / "bad-provenance.json"
    bad.write_text(json.dumps(shape))
    result = import_owned(fresh_owned_source, tmp_path / "destination", provenance=bad)
    assert result.returncode == 2
    assert "provenance" in json.loads(result.stderr)["error"].lower()


@pytest.mark.parametrize("config", [None, [], "not-an-object"])
def test_reserved_provenance_config_requires_an_object(
    fresh_owned_source,
    tmp_path,
    config,
):
    provenance = {**fresh_owned_source["provenance"], "config": config}
    bad = tmp_path / "bad-config.json"
    bad.write_text(json.dumps(provenance))
    result = import_owned(fresh_owned_source, tmp_path / "destination", provenance=bad)
    assert result.returncode == 2
    assert "config" in json.loads(result.stderr)["error"].lower()
    assert not (tmp_path / "destination" / "datasets").exists()


@pytest.mark.parametrize("shape", [[], {"schema_version": 1, "files": []}])
def test_dataset_manifest_invalid_shape_is_a_typed_error(imported, shape):
    _, root, dataset = imported
    (dataset / "manifest.json").write_text(json.dumps(shape))
    result = cli(root, "replay", "t-sunday", "--dataset", dataset)
    assert result.returncode == 2
    assert "manifest" in json.loads(result.stderr)["error"].lower()


def test_report_manifest_invalid_shape_is_not_an_unhandled_api_exception(tmp_path):
    report = report_fixture(["owned-transaction"])
    folder = save_report(tmp_path, report)
    (folder / "manifest.json").write_text("[]")
    with pytest.raises(ValueError, match="(?i)manifest"):
        save_report(tmp_path, report)
    response = _ASGIClient(create_app(tmp_path)).get(f"/api/runs/{report['run_id']}")
    assert response.status_code == 422


def test_cli_errors_and_guarded_reset_preserve_unowned_files(imported, tmp_path):
    source, root, dataset = imported
    result = cli(root, "replay", "unknown-transaction", "--dataset", dataset)
    assert result.returncode == 2
    assert "no recorded decision" in json.loads(result.stderr)["error"]
    no_candidate = cli(root, "compare", "t-sunday", "--dataset", dataset)
    assert no_candidate.returncode == 2
    assert "--candidate" in json.loads(no_candidate.stderr)["error"]
    preserve = root / "user-owned.txt"
    preserve.write_text("preserve user data")
    for extra in [(), ("--yes",)]:
        reset = cli(root, "reset", *extra)
        assert reset.returncode == 2
        assert preserve.read_text() == "preserve user data"
    owned = tmp_path / "separate-owned-reset-target"
    owned.mkdir()
    (owned / ".riskreplay-owned").touch()
    (owned / "generated.txt").write_text("disposable owned fixture")
    reset = cli(owned, "reset", "--yes")
    assert reset.returncode == 0, reset.stderr
    assert not owned.exists()
    assert source["root"].exists()


def test_installed_console_launcher_exposes_documented_commands(tmp_path):
    launcher = Path(sys.executable).parent / "riskreplay"
    if not launcher.is_file():
        pytest.skip("Console launcher is verified by setup; python -m riskreplay is tested above")
    output = subprocess.run(
        [str(launcher), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert output.returncode == 0, output.stderr
    for command in (
        "demo",
        "serve",
        "replay",
        "compare",
        "evaluate",
        "train",
        "import",
        "reset",
        "verify-reproducibility",
    ):
        assert command in output.stdout


def test_bundle_file_hashes_equal_the_written_bytes(imported):
    _, _, dataset = imported
    manifest = json.loads((dataset / "manifest.json").read_text())
    assert manifest["files"] == {
        name: hashlib.sha256((dataset / name).read_bytes()).hexdigest()
        for name in ("events.parquet", "decisions.parquet")
    }
