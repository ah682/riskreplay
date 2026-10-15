"""Predeclared larger owned profile and independent metric/artifact verification.

Run: .venv/bin/python scripts/verify_models.py --seed 17 --transactions 7200
This is an additional synthetic correctness profile, not a merchant benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def hashes():
    source = PROJECT_ROOT / "riskreplay"
    files = list(source.glob("*.py")) + list((source / "static").glob("*"))
    return {
        str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
        if path.is_file()
    }


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def verify_metrics(rows, metrics, name, selected, global_n):
    """Recompute without sklearn or the application's metric implementation."""
    observed = [row for row in rows if row["label_status"] == "mature_observed"]
    known = [row for row in observed if row["scores"].get(name) is not None]
    chosen = [row for row in rows if row["transaction_id"] in selected]
    chosen_known = [row for row in known if row["transaction_id"] in selected]
    positive = sum(row["label"] == 1 for row in known)
    captured = sum(row["label"] == 1 for row in chosen_known)
    checks = 0

    def equal(actual, expected):
        nonlocal checks
        assert actual == expected, (name, actual, expected)
        checks += 1

    def close(actual, expected):
        nonlocal checks
        assert (actual is None and expected is None) or (
            actual is not None
            and expected is not None
            and math.isclose(actual, expected, abs_tol=1e-11, rel_tol=1e-11)
        ), (name, actual, expected)
        checks += 1

    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None

    counts = metrics["counts"]
    equal(counts["total"], len(rows))
    equal(counts["observed_fraud"], sum(row["label"] == 1 for row in observed))
    equal(counts["observed_genuine"], sum(row["label"] == 0 for row in observed))
    if "metric_n" in metrics:
        equal(metrics["metric_n"], len(known))
        equal(counts["missing_state"], sum(bool(row.get("missing_state")) for row in rows))
        equal(counts["scoreable"], sum(row["scores"].get(name) is not None for row in rows))
    for status in ("mature_observed", "immature", "declined_unobserved", "unobserved"):
        equal(counts[status], sum(row["label_status"] == status for row in rows))
    close(metrics["observed_prevalence"], ratio(positive, len(known)))
    close(
        metrics["brier_score"],
        ratio(math.fsum((row["label"] - row["scores"][name]) ** 2 for row in known), len(known)),
    )
    # Group equal scores first. This independently handles the coarse rule ties.
    groups = {}
    for row in known:
        group = groups.setdefault(row["scores"][name], [0, 0])
        group[0] += row["label"]
        group[1] += 1
    tp = n = 0
    previous_recall, previous_precision = 0.0, 1.0
    ap, area = 0.0, 0.0
    for score in sorted(groups, reverse=True):
        fraud, size = groups[score]
        tp, n = tp + fraud, n + size
        recall = tp / positive if positive else 0
        precision = tp / n
        ap += (recall - previous_recall) * precision
        area += (recall - previous_recall) * (precision + previous_precision) / 2
        previous_recall, previous_precision = recall, precision
    close(metrics["average_precision"], ap if positive else None)
    close(metrics["pr_auc"], area if positive else None)
    review = metrics["review"]
    equal(review["capacity_denominator_all_test_transactions"], global_n)
    equal(review["capacity_slots_global"], math.floor(0.1 * global_n))
    equal(review["selected"], len(chosen))
    equal(review["selected_mature_observed"], len(chosen_known))
    equal(review["selected_unknown_outcomes"], len(chosen) - len(chosen_known))
    equal(review["observed_fraud_selected"], captured)
    equal(review["observed_fraud_denominator"], positive)
    equal(review["precision_denominator"], len(chosen_known))
    close(review["precision"], ratio(captured, len(chosen_known)))
    close(review["recall"], ratio(captured, positive))
    equal(
        review["full_selected_precision_identified"],
        len(chosen_known) == len(chosen) and bool(chosen),
    )
    amount = metrics["amount_weighted"]
    fraud_amount = math.fsum(row["amount"] for row in known if row["label"] == 1)
    captured_amount = math.fsum(row["amount"] for row in chosen_known if row["label"] == 1)
    selected_amount = math.fsum(row["amount"] for row in chosen_known)
    close(amount["observed_fraud_amount_denominator"], fraud_amount)
    close(amount["observed_fraud_amount_selected"], captured_amount)
    close(amount["selected_observed_amount_denominator"], selected_amount)
    close(amount["recall"], ratio(captured_amount, fraud_amount))
    close(amount["precision"], ratio(captured_amount, selected_amount))
    for index, bucket in enumerate(metrics["reliability_bins"]):
        members = [
            row
            for row in known
            if index / 10 <= row["scores"][name]
            and (row["scores"][name] < (index + 1) / 10 or index == 9)
        ]
        equal(bucket["count"], len(members))
        equal(bucket["observed_fraud"], sum(row["label"] for row in members))
        close(
            bucket["mean_prediction"],
            ratio(math.fsum(row["scores"][name] for row in members), len(members)),
        )
        close(bucket["fraud_rate"], ratio(sum(row["label"] for row in members), len(members)))
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--transactions", type=int, default=7200)
    parser.add_argument(
        "--root", type=Path, default=PROJECT_ROOT / "var/verification/calibrated-demo"
    )
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / "var/verification/model-audit.json"
    )
    args = parser.parse_args()
    before = hashes()
    audit = {
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "protocol": "Predeclared additional owned synthetic profile; one fixed seed and size, no seed search or metric selection.",
        "command": f".venv/bin/python scripts/verify_models.py --seed {args.seed} --transactions {args.transactions}",
        "profile": {"seed": args.seed, "n_transactions": args.transactions, "root": str(args.root)},
        "source_sha256_before": before,
    }
    save(args.output, audit)
    print(json.dumps({"profile_started": audit["profile"]}), flush=True)
    oracle_reads = []

    def access_audit(name, arguments):
        if (
            name == "open"
            and isinstance(arguments[0], (str, bytes))
            and "simulation_oracle" in os.fsdecode(arguments[0])
        ):
            mode, flags = arguments[1], arguments[2]
            if (isinstance(mode, str) and "r" in mode) or (
                mode is None and not flags & (os.O_WRONLY | os.O_RDWR)
            ):
                oracle_reads.append(os.fsdecode(arguments[0]))

    sys.addaudithook(access_audit)
    started = time.perf_counter()
    try:
        import joblib
        import numpy as np
        from threadpoolctl import threadpool_limits

        from riskreplay.modeling import FEATURE_NAMES, predict_model
        from riskreplay.pipeline import demo

        report = demo(args.root, seed=args.seed, n_transactions=args.transactions)
        audit["pipeline_seconds"] = time.perf_counter() - started
        evaluation = report["evaluation"]
        rows = evaluation["test_rows"]
        test_ids = {row["transaction_id"] for row in rows}
        target_audit = evaluation["training_audit"]
        fit = set(target_audit["training_transaction_ids"])
        tune = set(target_audit["tuning_transaction_ids"])
        calibrate = set(target_audit["calibration_transaction_ids"])
        assert fit.isdisjoint(tune | calibrate | test_ids)
        assert tune.isdisjoint(calibrate | test_ids) and calibrate.isdisjoint(test_ids)
        assert len(target_audit["training_targets"]) == len(fit)
        cutoff = datetime.fromisoformat(evaluation["splits"]["training_label_cutoff_inclusive"])
        assert all(
            datetime.fromisoformat(row["label_available_at"]) <= cutoff
            for row in target_audit["training_targets"]
        )
        assert all(row["label"] is None for row in rows if row["label_status"] != "mature_observed")
        assert all("label_history" not in row for row in rows)
        assert report["summary"]["total"] == args.transactions
        assert report["summary"]["matched"] == args.transactions - 2
        assert report["summary"]["mismatched"] == report["summary"]["incomplete"] == 1
        assert report["integrity"]["failed"] == 0
        assert report["integrity"]["online_offline"]["matched"] == args.transactions
        checks, models = 0, {}
        model_groups = {**evaluation["models"], "rules": evaluation["rules_baseline"]}
        for name, info in model_groups.items():
            ordered = sorted(
                rows,
                key=lambda row: (
                    -row["scores"][name],
                    datetime.fromisoformat(row["decision_time"]),
                    row["transaction_id"],
                ),
            )
            selected = {row["transaction_id"] for row in ordered[: math.floor(0.1 * len(rows))]}
            assert selected == {
                row["transaction_id"] for row in rows if row["selected_for_review"][name]
            }
            checks += verify_metrics(rows, info["metrics"], name, selected, len(rows))
            for cohort, metrics in info["cohorts"].items():
                checks += verify_metrics(
                    [row for row in rows if row["cohort"] == cohort],
                    metrics,
                    name,
                    selected,
                    len(rows),
                )
            assert sum(value["review"]["selected"] for value in info["cohorts"].values()) == len(
                selected
            )
            models[name] = {"metrics": info["metrics"], "cohorts": info["cohorts"]}
            if name == "rules":
                continue
            artifact = args.root / "artifacts" / info["artifact_path"]
            assert hashlib.sha256(artifact.read_bytes()).hexdigest() == info["file_hash"]
            bundle = joblib.load(artifact)  # This script just trained this local trusted file.
            assert bundle["metadata"]["training_targets"] == target_audit["training_targets"]
            matrix = np.asarray([[row["features"][key] for key in FEATURE_NAMES] for row in rows])
            with threadpool_limits(limits=1):
                actual = bundle["predictor"].predict_proba(matrix)[:, 1]
            np.testing.assert_allclose(
                actual, [row["scores"][name] for row in rows], rtol=0, atol=1e-14
            )
            for index in sorted({0, len(rows) // 4, len(rows) // 2, len(rows) - 1}):
                assert math.isclose(
                    predict_model(
                        args.root / "artifacts", info["file_hash"], rows[index]["features"]
                    ),
                    actual[index],
                    abs_tol=1e-14,
                )
            assert info["calibration"]["method"] == "sigmoid", info["calibration"]
            models[name].update(
                {
                    "file_hash": info["file_hash"],
                    "calibration": info["calibration"],
                    "n_training": info["n_training"],
                    "parameters": info["parameters"],
                    "verified_prediction_count": len(rows),
                }
            )
        assert not oracle_reads, oracle_reads
        audit.update(
            {
                "status": "passed",
                "run_id": report["run_id"],
                "dataset_hash": report["dataset_hash"],
                "semantic_hash": report["semantic_hash"],
                "summary": report["summary"],
                "splits": evaluation["splits"],
                "models": models,
                "integrity_checks": report["integrity"]["checks"],
                "online_offline": report["integrity"]["online_offline"],
                "fault_detection": {
                    key: value
                    for key, value in report["integrity"]["fault_experiment"].items()
                    if key
                    in {"true_positives", "false_negatives", "false_positives", "true_negatives"}
                },
                "independently_recomputed_metric_assertions": checks,
                "oracle_file_reads": oracle_reads,
                "versions": evaluation["versions"],
                "performance": report["performance"],
                "report_path": str(args.root / "runs" / report["run_id"] / "report.json"),
            }
        )
    except Exception as exc:
        audit.update(
            status="failed", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc()
        )
        raise
    finally:
        audit["elapsed_seconds"] = time.perf_counter() - started
        audit["source_sha256_after"] = hashes()
        audit["source_files_changed_during_run"] = [
            name
            for name in sorted(set(before) | set(audit["source_sha256_after"]))
            if before.get(name) != audit["source_sha256_after"].get(name)
        ]
        if audit["source_files_changed_during_run"] and audit["status"] == "passed":
            audit.update(status="failed", error="Source files changed during the frozen audit")
        audit["finished_at"] = datetime.now(UTC).isoformat()
        save(args.output, audit)
        print(
            json.dumps(
                {
                    "status": audit["status"],
                    "output": str(args.output),
                    "elapsed_seconds": audit["elapsed_seconds"],
                }
            ),
            flush=True,
        )
    if audit["status"] != "passed":
        raise RuntimeError(audit["error"])


if __name__ == "__main__":
    main()
