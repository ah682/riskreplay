"""Credential-free local workflows. All external imports are files, never live writes."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from .artifacts import ArtifactStore
from .engine import TemporalEngine
from .pipeline import demo, evaluate_run, model_rows
from .policy import compare, evaluate, replay
from .reporting import validate_report, validate_run_files
from .schema import Decision
from .storage import import_jsonl, load_dataset, write_json

DEFAULT_ROOT = Path(os.environ.get("RISKREPLAY_DATA_DIR", "var/demo"))


def _server_port(value: str) -> int:
    try:
        port = int(value)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535")
    return port


def _selection(args):
    latest_path = args.data_dir / "latest.json"
    try:
        latest = json.loads(latest_path.read_text()) if latest_path.exists() else {}
        if not isinstance(latest, dict) or any(
            not isinstance(latest[key], str) or not latest[key]
            for key in ("dataset", "run_id", "candidate_policy")
            if key in latest
        ):
            raise ValueError("latest.json must be an object with string selection values")
    except (OSError, ValueError):
        if args.dataset is None or (args.command in {"compare", "evaluate"} and not args.candidate):
            raise
        latest = {}
    dataset = args.dataset or (args.data_dir / latest["dataset"] if latest else None)
    if dataset is None:
        raise ValueError("No dataset selected. Run 'make demo' or pass --dataset PATH.")
    events, decisions, manifest = load_dataset(dataset)
    return dataset, events, decisions, manifest, latest


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="riskreplay",
        description="Inspect historical risk decisions and evidence limits locally.",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=DEFAULT_ROOT, help="Local artifacts and report directory"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser(
        "demo", help="Generate owned data, train, replay, and export a complete run"
    )
    generate.add_argument("--seed", type=int, default=17)
    generate.add_argument("--transactions", type=int, default=1800)
    serve = commands.add_parser("serve", help="Start the read-only local inspector")
    serve.add_argument(
        "--port", type=_server_port, default=os.environ.get("RISKREPLAY_PORT", "8765")
    )
    for command in ("replay", "compare", "evaluate", "train"):
        sub = commands.add_parser(command)
        sub.add_argument("--dataset", type=Path)
        if command in ("replay", "compare"):
            sub.add_argument("transaction_id")
        if command in ("compare", "evaluate"):
            sub.add_argument(
                "--candidate",
                help="Content hash of candidate policy (default: latest demo candidate)",
            )
        if command == "compare":
            sub.add_argument(
                "--policy-a",
                help="Optional left policy hash, evaluated on the same recorded cutoff",
            )
    ingest = commands.add_parser(
        "import", help="Validate normalized JSONL and persist an immutable Parquet bundle"
    )
    ingest.add_argument("--events", type=Path, required=True)
    ingest.add_argument("--decisions", type=Path, required=True)
    ingest.add_argument(
        "--provenance",
        type=Path,
        required=True,
        help="JSON with kind, source, permission; no implicit real-data claim",
    )
    reset = commands.add_parser("reset", help="Remove only RiskReplay-owned generated data")
    reset.add_argument(
        "--yes", action="store_true", help="Required explicit destructive-reset flag"
    )
    verify = commands.add_parser(
        "verify-reproducibility", help="Train and evaluate twice in two clean temporary roots"
    )
    verify.add_argument("--transactions", type=int, default=600)
    verify.add_argument(
        "--output", type=Path, default=Path("var/verification/reproducibility.json")
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            report = demo(args.data_dir, seed=args.seed, n_transactions=args.transactions)
            _summary(report, args.data_dir)
            if report["integrity"]["failed"]:
                return_code = 1
                raise SystemExit(return_code)
        elif args.command == "serve":
            import uvicorn

            from .web import create_app

            print(f"RiskReplay local inspector: http://127.0.0.1:{args.port}", flush=True)
            uvicorn.run(
                create_app(args.data_dir), host="127.0.0.1", port=args.port, log_level="warning"
            )
        elif args.command == "import":
            result = import_jsonl(
                args.events, args.decisions, args.data_dir, json.loads(args.provenance.read_text())
            )
            print(
                json.dumps(
                    {
                        "dataset": str(result),
                        "status": "validated",
                        "note": "Replay still requires the actual archived artifacts and historical state.",
                    },
                    indent=2,
                )
            )
        elif args.command == "reset":
            if not args.yes:
                raise ValueError(
                    "Reset removes generated runs and models. Pass --yes to reset this RiskReplay-owned data directory."
                )
            marker = args.data_dir / ".riskreplay-owned"
            if not marker.is_file() or marker.is_symlink() or args.data_dir.is_symlink():
                raise ValueError(
                    "Refusing reset: directory is not a regular RiskReplay-owned demo directory."
                )
            shutil.rmtree(args.data_dir)
            print(f"Reset generated data: {args.data_dir}")
        elif args.command == "verify-reproducibility":
            with tempfile.TemporaryDirectory(prefix="riskreplay-repeat-") as temporary:
                a = demo(Path(temporary) / "a", n_transactions=args.transactions)
                b = demo(Path(temporary) / "b", n_transactions=args.transactions)
                evidence = {
                    "transactions": args.transactions,
                    "seed": 17,
                    "semantic_hash_a": a["semantic_hash"],
                    "semantic_hash_b": b["semantic_hash"],
                    "identical": a["semantic_hash"] == b["semantic_hash"],
                    "dataset_identical": a["dataset_hash"] == b["dataset_hash"],
                    "model_artifacts_identical": {
                        name: a["evaluation"]["models"][name]["file_hash"]
                        == b["evaluation"]["models"][name]["file_hash"]
                        for name in a["evaluation"]["models"]
                    },
                    "excluded_nonsemantic_metadata": [
                        "run_id",
                        "created_at",
                        "performance",
                        "semantic_hash",
                    ],
                }
                write_json(args.output, evidence)
                print(json.dumps(evidence, indent=2))
                if not evidence["identical"]:
                    raise ValueError(
                        "Semantic decisions/metrics differed across clean repeated runs"
                    )
        else:
            dataset, events, decisions, manifest, latest = _selection(args)
            store = ArtifactStore(args.data_dir / "artifacts")
            engine = TemporalEngine(events)
            if args.command == "train":
                from .modeling import train_models

                cutoff = (
                    manifest["provenance"]
                    .get("config", {})
                    .get("evaluation_cutoff", max(d.decision_time for d in decisions))
                )
                result = train_models(
                    model_rows(engine, store, decisions, cutoff),
                    store.root,
                    evaluation_cutoff=cutoff,
                )
                output = args.data_dir / "training" / f"{result['dataset_hash']}.json"
                write_json(output, result)
                print(
                    json.dumps(
                        {
                            "training_report": str(output),
                            "models": {k: v["file_hash"] for k, v in result["models"].items()},
                        },
                        indent=2,
                    )
                )
            elif args.command == "evaluate":
                candidate = args.candidate or latest.get("candidate_policy")
                if not candidate:
                    raise ValueError("Pass --candidate with an archived policy hash")
                previous_path = (
                    args.data_dir / "runs" / latest.get("run_id", "no-run") / "report.json"
                )
                previous = None
                if previous_path.is_file() and str(dataset) == str(
                    args.data_dir / latest.get("dataset", "")
                ):
                    previous_report = json.loads(previous_path.read_text())
                    validate_report(previous_report)
                    validate_run_files(previous_path.parent, "report.json")
                    if previous_report.get("dataset_hash") != manifest["dataset_hash"]:
                        raise ValueError("Saved evaluation does not match the selected dataset")
                    previous = previous_report["evaluation"]
                report = evaluate_run(args.data_dir, dataset, candidate, evaluation=previous)
                _summary(report, args.data_dir)
            else:
                decision = next(
                    (d for d in decisions if d.transaction_id == args.transaction_id), None
                )
                if decision is None:
                    raise ValueError(
                        f"Transaction {args.transaction_id!r} has no recorded decision in this dataset"
                    )
                if args.command == "replay":
                    result = replay(engine, store, decision)
                    result.pop("visible_ids", None)
                else:
                    candidate = args.candidate or latest.get("candidate_policy")
                    if not candidate:
                        raise ValueError("Pass --candidate with an archived policy hash")
                    if args.policy_a:
                        left = evaluate(
                            engine, store, decision.transaction_id, decision.cutoff, args.policy_a
                        )
                        if left["missing"]:
                            raise ValueError(
                                "Left comparison policy is incomplete: "
                                + "; ".join(left["missing"])
                            )
                        decision = Decision(
                            decision.transaction_id,
                            decision.decision_time,
                            decision.cutoff_seq,
                            args.policy_a,
                            left["score"],
                            left["action"],
                            left["features"],
                        )
                    result = compare(engine, store, decision, candidate)
                    for key in ("original", "candidate"):
                        result[key].pop("visible_ids", None)
                    result["information_regime"] = (
                        "Equivalent original available facts; candidate is retrospective. Declined approval outcomes remain unknown."
                    )
                print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc), "command": args.command}), file=sys.stderr)
        raise SystemExit(2) from exc


def _summary(report, root):
    result = {
        "run_id": report["run_id"],
        "summary": report["summary"],
        "integrity_passed": report["integrity"]["passed"],
        "integrity_failed": report["integrity"]["failed"],
        "semantic_hash": report["semantic_hash"],
        "report": str(root / "runs" / report["run_id"] / "report.html"),
        "inspector": str(root / "runs" / report["run_id"] / "inspector.html"),
        "model_metrics": {
            name: {
                "average_precision": model["metrics"]["average_precision"],
                "pr_auc": model["metrics"]["pr_auc"],
                "brier_score": model["metrics"]["brier_score"],
                "counts": model["metrics"]["counts"],
            }
            for name, model in report["evaluation"].get("models", {}).items()
        },
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
