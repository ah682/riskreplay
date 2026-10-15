"""The local release workflow: owned data -> trained artifacts -> replay evidence."""

from __future__ import annotations

import copy
import os
import platform
import statistics
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import ArtifactStore
from .checks import audit_features, fault_experiment
from .engine import REGIMES, TemporalEngine
from .generator import generate, observe_outcomes
from .modeling import (
    LeakageError,
    train_models,
    validate_chronological_splits,
    validate_training_rows,
)
from .online import OnlineReference
from .policy import apply_rules, archive_policy, compare, evaluate, replay, score_model
from .reporting import save_report
from .schema import Cutoff, Decision, Event, digest, iso, timestamp
from .storage import build_index, load_dataset, save_dataset, write_json

DEFAULT_SEED = 17


def model_rows(
    engine: TemporalEngine, store: ArtifactStore, decisions: list[Decision], evaluation_cutoff: str
) -> list[dict]:
    rows = []
    cutoff = Cutoff(evaluation_cutoff, 2**63 - 1)
    outcome_histories: dict[str, list[dict]] = {}
    for event in engine.by_id.values():
        if (
            event.event_type == "outcome"
            and event.delivery_key <= cutoff.key
            and event.event_time <= cutoff.time
        ):
            outcome_histories.setdefault(event.transaction_id, []).append(
                {
                    "event_id": event.event_id,
                    "event_time": event.event_time,
                    "available_at": event.available_at,
                    "delivery_seq": event.delivery_seq,
                    "supersedes": event.supersedes,
                    "label": event.payload["label"],
                }
            )
    for decision in decisions:
        state = replay(engine, store, decision)
        label = engine.label(decision.transaction_id, decision.original_action, cutoff)
        features = state["features"]
        transaction = state.get("transaction")
        if transaction is None:
            transaction = next(
                (
                    event.to_dict()
                    for event in engine.visible(decision.cutoff)
                    if event.event_type == "transaction"
                    and event.transaction_id == decision.transaction_id
                ),
                {},
            )
        payload = transaction.get("payload", {})
        rows.append(
            {
                "transaction_id": decision.transaction_id,
                "decision_time": decision.decision_time,
                "observed_action": decision.original_action,
                "cohort": payload.get("cohort", "unknown"),
                "amount": payload.get("amount"),
                # Keep the selected population intact: unavailable state reduces
                # evidence within a frozen window, never moves its boundaries.
                "missing_state": state["missing"],
                "features": {} if state["missing"] else features,
                "label": label["label"],
                "label_available_at": label["label_available_at"],
                # Keep identities separate from input features: fitting resolves
                # the original/corrected target at its own historical cutoff.
                "label_history": outcome_histories.get(decision.transaction_id, [])
                if decision.original_action != "decline"
                else [],
                "feature_available_at": {
                    k: max(
                        (engine.by_id[eid].available_at for eid in ids),
                        default=decision.decision_time,
                    )
                    for k, ids in state["provenance"].items()
                },
            }
        )
    return rows


def demo(root: Path, seed: int = DEFAULT_SEED, n_transactions: int = 1800) -> dict:
    root = Path(root)
    marker = root / ".riskreplay-owned"
    if root.is_symlink():
        raise ValueError("Demo directory must not be a symlink")
    if root.exists() and (
        not root.is_dir() or (any(root.iterdir()) and (not marker.is_file() or marker.is_symlink()))
    ):
        raise ValueError(
            "Demo refuses a nonempty unowned directory; choose an empty data directory"
        )
    simulation = generate(seed, n_transactions)
    root.mkdir(parents=True, exist_ok=True)
    marker.touch()
    store = ArtifactStore(root / "artifacts")
    original_v1 = archive_policy(store, name="Archived logging policy · v1")
    original_v2 = archive_policy(store, name="Archived logging policy · v2", review_amount=250)
    events = [Event(**event) for event in simulation["events"]]
    online = OnlineReference()
    decisions = []
    recorded_ids = set()
    for tx in sorted(events, key=lambda event: event.delivery_key):
        online.observe(tx)
        if tx.event_type != "transaction" or tx.supersedes or tx.transaction_id in recorded_ids:
            continue
        recorded_ids.add(tx.transaction_id)
        cutoff = Cutoff(tx.available_at, tx.delivery_seq)
        day = (timestamp(cutoff.time) - timestamp(simulation["config"]["start_time"])).days
        policy = original_v2 if day >= simulation["config"]["policy_shift_day"] else original_v1
        manifest = store.get("policies", policy)
        feature_spec = store.get("features", manifest["features"])
        features = online.features(tx.transaction_id, cutoff, feature_spec["window_seconds"])
        score = score_model(store, store.get("models", manifest["model"]), features)
        action, _ = apply_rules(features, score, store.get("rules", manifest["rules"]))
        decisions.append(
            Decision(
                tx.transaction_id,
                cutoff.time,
                cutoff.sequence,
                policy,
                round(float(score), 12),
                action,
                features,
            )
        )
    observed = observe_outcomes(
        simulation["events"],
        [d.transaction_id for d in decisions if d.original_action == "decline"],
    )
    events = [Event(**event) for event in observed]
    engine = TemporalEngine(events)
    # Oracle is a sibling, never passed to model_rows, train_models, or evaluate_run.
    oracle_path = root / "simulation_oracle" / f"seed-{seed}-n-{n_transactions}.json"
    if not oracle_path.exists():
        write_json(
            oracle_path,
            {
                "mode": "simulation_ground_truth_only",
                "warning": "Not an observed merchant label source. No estimator experiment is claimed.",
                "rows": simulation["oracle"],
            },
        )
    evaluation_cutoff = simulation["config"]["evaluation_cutoff"]
    rows = model_rows(engine, store, decisions, evaluation_cutoff)
    evaluation = train_models(rows, store.root, seed=seed, evaluation_cutoff=evaluation_cutoff)
    boosted = evaluation["models"]["gradient_boosted"]
    candidate = archive_policy(
        store,
        name="Candidate · boosted / review at 0.18",
        decline_amount=1200,
        review_amount=500,
        review_score=0.18,
        review_velocity=4,
        model={
            "type": "sklearn",
            "mode": "trained_cpu",
            "file_hash": boosted["file_hash"],
            "feature_names": boosted["feature_names"],
            "training_cutoff": evaluation["splits"]["validation_label_cutoff_inclusive"],
        },
    )
    # Purposeful evidence defects make the incomplete/mismatched product states inspectable.
    missing_manifest = store.get("policies", original_v1)
    missing_manifest["name"] = "Archived policy · deliberately missing model"
    missing_manifest["model"] = "f" * 64
    missing_policy = store.put("policies", missing_manifest)
    recorded = []
    for decision in decisions:
        if decision.transaction_id == "t-after-outage":
            decision = replace(decision, policy_hash=missing_policy)
        elif decision.transaction_id == "t-monday":
            decision = replace(
                decision, original_score=round(min(1.0, decision.original_score + 0.2), 12)
            )
        recorded.append(decision)
    config = copy.deepcopy(simulation["config"])
    config["generator_suggested_splits"] = config.pop("split_times")
    config["split_note"] = (
        "Actual model split is 60/20/20 of decision-time span; see evaluation.splits. Generator schedule suggestions are not used for fitting."
    )
    config.update(
        {
            "original_mode": "deterministic_fixture",
            "recording_reference": {
                "implementation": "independent_delivery_order_reference_v1",
                "code_hash": digest(Path(__file__).with_name("online.py").read_text()),
                "protocol": "Live state consumes deliveries in availability/sequence order; historical TemporalEngine does not construct recorded features.",
            },
            "candidate_mode": "trained_cpu",
            "candidate_policy": candidate,
            "original_policies": [original_v1, original_v2],
            "injected_record_defects": {
                "t-monday": "Original score deliberately perturbed by +0.2",
                "t-after-outage": "Archived policy deliberately references an absent model",
            },
            "observation_boundary": "Original declines have no observed approval labels; reviews assumed fulfilled in this simulator.",
        }
    )
    dataset = save_dataset(
        root,
        events,
        recorded,
        {
            "kind": "owned_synthetic",
            "source": "RiskReplay sequential generator",
            "permission": "Project-owned synthetic fixtures",
            "config": config,
        },
    )
    build_index(root / "index.sqlite", events, recorded)
    report = evaluate_run(
        root, dataset, candidate, evaluation=evaluation, clean_decisions=decisions
    )
    write_json(
        root / "latest.json",
        {
            "run_id": report["run_id"],
            "dataset": str(dataset.relative_to(root)),
            "candidate_policy": candidate,
        },
    )
    return report


def evaluate_run(
    root: Path,
    dataset: Path,
    candidate_policy: str,
    *,
    evaluation: dict | None = None,
    clean_decisions: list[Decision] | None = None,
) -> dict:
    events, decisions, manifest = load_dataset(dataset)
    store = ArtifactStore(Path(root) / "artifacts")
    engine = TemporalEngine(events)
    config = manifest["provenance"].get("config", {})
    evaluation_cutoff = config.get("evaluation_cutoff", max(d.decision_time for d in decisions))
    label_cutoff = Cutoff(evaluation_cutoff, 2**63 - 1)
    if evaluation is None:
        evaluation = {
            "models": {},
            "mode": "not_trained_for_this_import",
            "assumptions": ["No model quality claims generated for this import."],
        }
    results, latencies, states = [], [], {}
    for decision in decisions:
        started = time.perf_counter()
        compared = compare(engine, store, decision, candidate_policy)
        latencies.append(time.perf_counter() - started)
        old, new = compared["original"], compared["candidate"]
        states[decision.transaction_id] = old
        tx = (
            old.get("transaction")
            or new.get("transaction")
            or engine.transactions[decision.transaction_id][0].to_dict()
        )
        label = engine.label(decision.transaction_id, decision.original_action, label_cutoff)
        explanation = compared["explanation"]
        if old["status"] == "mismatched":
            explanation.insert(
                0,
                {
                    "kind": "evidence",
                    "message": f"Recorded {decision.original_action} / {decision.original_score:.4f}; archived reconstruction {old['action']} / {old['score']:.4f}. The recorded decision does not match its archived evidence.",
                },
            )
        missing = list(dict.fromkeys(old["missing"] + new["missing"]))
        versions = old.get("versions", {})
        item = {
            "transaction_id": decision.transaction_id,
            "decision_time": decision.decision_time,
            "cutoff_seq": decision.cutoff_seq,
            "amount": float(tx["payload"]["amount"]),
            "cohort": tx["payload"].get("cohort", "unknown"),
            "status": old["status"],
            "recorded_action": decision.original_action,
            "replayed_action": old["action"],
            "candidate_action": new["action"],
            "original_score": decision.original_score,
            "replayed_score": old["score"],
            "candidate_score": new["score"],
            "label_status": label["label_status"],
            "label": label["label"],
            "label_available_at": label["label_available_at"],
            "missing": missing,
            "explanation": explanation,
            "features": old["features"],
            "candidate_features": new["features"],
            "provenance": old["provenance"],
            "timeline": engine.timeline(
                decision.transaction_id, decision.cutoff, old["provenance"] or new["provenance"]
            ),
            "versions": {
                "original_policy": decision.policy_hash,
                "candidate_policy": candidate_policy,
                "feature": versions.get("features"),
                "model": versions.get("model"),
                "rules": versions.get("rules"),
            },
            "original_rule_trace": old["trace"],
            "candidate_rule_trace": new["trace"],
            "first_divergence": compared["first_divergence"],
            "changed": compared["changed"],
            "counterfactual_outcome": "unknown"
            if decision.original_action == "decline"
            else "observed under logging policy only",
            "candidate_information_regime": "Retrospective candidate on original available features; pre-test transactions are diagnostic only",
        }
        results.append(item)
    statuses = Counter(r["status"] for r in results)
    labels = Counter(r["label_status"] for r in results)
    summary = {
        "total": len(results),
        **{key: statuses[key] for key in ("matched", "mismatched", "incomplete")},
        "changed": sum(r["changed"] for r in results),
        **{key: labels[key] for key in ("mature", "immature", "declined_unobserved", "unobserved")},
        "missing_state": sum(bool(r["missing"]) for r in results),
        "reconstructable": len(results) - statuses["incomplete"],
        "replay_agreement_numerator": statuses["matched"],
        "replay_agreement_denominator": len(results) - statuses["incomplete"],
    }
    baselines = []
    for regime in ("available", "event_time_only", "current_state"):
        action_matches = feature_matches = total = incomplete = 0
        divergent_ids = []
        for decision in decisions:
            out = (
                states[decision.transaction_id]
                if regime == "available"
                else evaluate(
                    engine,
                    store,
                    decision.transaction_id,
                    decision.cutoff,
                    decision.policy_hash,
                    regime=regime,
                )
            )
            if out["missing"]:
                incomplete += 1
                continue
            total += 1
            action_matches += out["action"] == decision.original_action
            equal = out["features"] == decision.feature_values
            feature_matches += equal
            if not equal:
                divergent_ids.append(decision.transaction_id)
        baselines.append(
            {
                "name": regime,
                "information_regime": REGIMES[regime],
                "n": total,
                "incomplete": incomplete,
                "action_matches": action_matches,
                "feature_matches": feature_matches,
                "feature_mismatches": total - feature_matches,
                "action_agreement": action_matches / total if total else None,
                "feature_agreement": feature_matches / total if total else None,
                "divergent_transaction_ids": divergent_ids,
            }
        )
    controls = (
        fault_experiment(engine, decisions, states)
        if "t-sunday" in states and not states["t-sunday"].get("missing")
        else {"cases": [], "protocol": "Not run: this import is not the owned acceptance fixture"}
    )
    findings = [
        {
            "transaction_id": d.transaction_id,
            "findings": audit_features(engine, d, states[d.transaction_id]),
        }
        for d in decisions
    ]
    clean_labels_check = None
    split_leak_detected = False
    label_leak_detected = False
    if evaluation.get("models"):
        rows = model_rows(engine, store, clean_decisions or decisions, evaluation_cutoff)
        future = next(
            (
                r
                for r in rows
                if r["label"] is not None
                and timestamp(r["label_available_at"])
                > timestamp(evaluation["splits"]["training_label_cutoff_inclusive"])
                and timestamp(r["decision_time"])
                < timestamp(evaluation["splits"]["validation_start_inclusive"])
            ),
            None,
        )
        if future:
            try:
                validate_training_rows(
                    [future], evaluation["splits"]["training_label_cutoff_inclusive"]
                )
            except LeakageError:
                label_leak_detected = True
        try:
            validate_chronological_splits([rows[-1]], [rows[0]], [rows[1]])
        except LeakageError:
            split_leak_detected = True
        targets = evaluation["training_audit"].get("training_targets")
        if targets is None:  # Earlier saved report schema without outcome-history target audit.
            fit_ids = set(evaluation["training_audit"]["training_transaction_ids"])
            targets = [row for row in rows if row["transaction_id"] in fit_ids]
        clean_labels_check = bool(targets) and all(
            timestamp(r["label_available_at"])
            <= timestamp(evaluation["splits"]["training_label_cutoff_inclusive"])
            for r in targets
        )

    def check(name, passed, detail):
        return {
            "name": name,
            "passed": None if passed is None else bool(passed),
            "status": "unavailable" if passed is None else "passed" if passed else "failed",
            "detail": detail,
        }

    complete_count = sum(not state["missing"] for state in states.values())
    checks = [
        check(
            "Original feature evidence respects the cutoff",
            not any(f["findings"] for f in findings) if complete_count else None,
            f"{complete_count} / {len(findings)} complete decision snapshots audited; incomplete snapshots excluded",
        ),
        check(
            "Duplicate deliveries retained and deduplicated",
            not any(
                f["code"] == "duplicate_counted_velocity"
                for row in findings
                for f in row["findings"]
            )
            if complete_count
            else None,
            f"{len(events) - len(engine.by_id)} duplicate deliveries retained",
        ),
        check(
            "Training targets available before training cutoff",
            clean_labels_check,
            "Mature observed targets only; no missing label filled with zero"
            if clean_labels_check is not None
            else "No training audit available for this imported dataset",
        ),
    ]
    if evaluation.get("models"):
        checks += [
            check(
                "Intentionally future training label rejected",
                label_leak_detected,
                "Controlled leaky fit-set probe",
            ),
            check(
                "Intentionally overlapping/reversed split rejected",
                split_leak_detected,
                "Controlled chronological split probe",
            ),
        ]
    if controls.get("cases"):
        checks += [
            check(
                "Injected temporal faults detected",
                controls["false_negatives"] == 0,
                f"{controls['true_positives']} / {len(controls['cases'])} known faults",
            ),
            check(
                "Negative controls have no false alarms",
                controls["false_positives"] == 0,
                f"{controls['false_positives']} / {controls['true_negatives'] + controls['false_positives']} false alarms",
            ),
        ]
    online_offline = {
        "status": "unavailable",
        "reason": "No independent pristine recording audit supplied",
    }
    if clean_decisions:
        reconstructed = [replay(engine, store, decision) for decision in clean_decisions]
        matched = sum(state["status"] == "matched" for state in reconstructed)
        unequal_ids = [
            decision.transaction_id
            for decision, state in zip(clean_decisions, reconstructed, strict=True)
            if state["missing"] or state["features"] != decision.feature_values
        ]
        online_offline = {
            "status": "passed" if not unequal_ids else "failed",
            "protocol": "Independent delivery-order feature recorder vs historical snapshot reconstruction, before injected artifact defects",
            "n": len(clean_decisions),
            "matched": len(clean_decisions) - len(unequal_ids),
            "mismatched_or_unavailable_ids": unequal_ids,
            "scope": "Owned local simulation; no production online capture",
        }
        checks += [
            check(
                "Complete archived originals reproduce",
                matched == len(clean_decisions),
                f"{matched} / {len(clean_decisions)} independently recorded originals before the two documented evidence defects",
            )
        ]
    total_latency = sum(latencies)
    ordered = sorted(latencies)
    hardware = platform.processor() or platform.machine()
    cpu_info = Path("/proc/cpuinfo")
    if cpu_info.exists():
        hardware = next(
            (
                line.split(":", 1)[1].strip()
                for line in cpu_info.read_text().splitlines()
                if line.startswith("model name")
            ),
            hardware,
        )
    run_identity = {
        "dataset": manifest["dataset_hash"],
        "candidate": candidate_policy,
        "evaluation": digest(evaluation),
        "pristine_recording_audit": clean_decisions is not None,
        "pipeline_hash": digest(
            {p.name: p.read_text() for p in Path(__file__).parent.glob("*.py")}
        ),
        "presentation_hash": digest(
            {
                p.name: p.read_text()
                for p in sorted(Path(__file__).with_name("static").iterdir())
                if p.is_file()
            }
        ),
    }
    report = {
        "schema_version": 1,
        "run_id": "rr-" + digest(run_identity)[:16],
        "created_at": iso(datetime.now(timezone.utc)),
        "mode": manifest["provenance"]["kind"],
        "information_regime": REGIMES["available"]
        + " Candidate policy is a retrospective experiment; records before the frozen test window are diagnostic only. Model metrics use held-out mature observed labels.",
        "dataset_hash": manifest["dataset_hash"],
        "run_identity": run_identity,
        "config": config,
        "summary": summary,
        "decisions": results,
        "evaluation": evaluation,
        "baselines": baselines,
        "integrity": {
            "checks": checks,
            "passed": sum(c["passed"] is True for c in checks),
            "failed": sum(c["passed"] is False for c in checks),
            "unavailable": sum(c["passed"] is None for c in checks),
            "online_offline": online_offline,
            "fault_experiment": controls,
            "raw_audits": findings,
        },
        "performance": {
            "hardware": hardware,
            "logical_cpus": os.cpu_count(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "protocol": "Warm local serial original+candidate comparison, including feature construction, scoring, and staged attribution; excludes timeline/export and model training. One measured pass, no SLA claim.",
            "n": len(latencies),
            "seconds": total_latency,
            "comparisons_per_second": len(latencies) / total_latency,
            "latency_p50_ms": statistics.median(latencies) * 1000,
            "latency_p95_ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] * 1000,
        },
        "limitations": [
            "Owned synthetic data only. No real merchant, payment-provider, or investigation-time validation.",
            "Observed outcomes are selected by logging policy; declined approval outcomes remain unknown.",
            "Independent streaming vs reconstructed feature agreement is limited to the owned local simulator; no production online/offline validation was performed.",
            "Feature and rule interpreter code hashes must match; unavailable historical implementations return incomplete.",
        ],
    }
    save_report(root, report)
    return report
