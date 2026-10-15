"""Auditable temporal-integrity checks and a labeled fault experiment."""

from __future__ import annotations

from .engine import TemporalEngine
from .schema import Decision


def audit_features(engine: TemporalEngine, decision: Decision, state: dict) -> list[dict]:
    findings = []
    provenance = state.get("provenance", {})
    for feature, ids in provenance.items():
        for eid in ids:
            event = engine.by_id.get(eid)
            if event is None:
                findings.append({"code": "missing_evidence", "feature": feature, "event_id": eid})
                continue
            if (
                event.delivery_key > decision.cutoff.key
                or event.event_time > decision.decision_time
            ):
                findings.append(
                    {"code": "impossible_knowledge", "feature": feature, "event_id": eid}
                )
                if event.supersedes:
                    findings.append(
                        {"code": "retrospective_correction", "feature": feature, "event_id": eid}
                    )
            if event.event_type == "outcome":
                findings.append(
                    {
                        "code": "future_label"
                        if event.delivery_key > decision.cutoff.key
                        else "label_as_feature",
                        "feature": feature,
                        "event_id": eid,
                    }
                )
    ids = provenance.get("velocity_1h", [])
    transactions = [
        engine.by_id[e].transaction_id
        for e in ids
        if e in engine.by_id and engine.by_id[e].event_type == "transaction"
    ]
    velocity = state.get("features", {}).get("velocity_1h")
    if (
        velocity is not None
        and velocity >= 0
        and (len(transactions) != len(set(transactions)) or velocity != len(set(transactions)))
    ):
        findings.append(
            {
                "code": "duplicate_counted_velocity",
                "feature": "velocity_1h",
                "expected": len(set(transactions)),
                "observed": velocity,
            }
        )
    return findings


def fault_experiment(
    engine: TemporalEngine, decisions: list[Decision], states: dict[str, dict]
) -> dict:
    """Inject labeled faults into copies, never the canonical dataset or model rows."""
    import copy

    cases = []
    sunday = next(d for d in decisions if d.transaction_id == "t-sunday")
    base = states[sunday.transaction_id]
    for code, predicate, feature in [
        (
            "impossible_knowledge",
            lambda e: e.event_type == "transaction" and e.transaction_id == "t-late",
            "velocity_1h",
        ),
        (
            "retrospective_correction",
            lambda e: e.supersedes and e.transaction_id == "t-correction",
            "amount",
        ),
        (
            "future_label",
            lambda e: e.event_type == "outcome" and e.transaction_id == "t-monday",
            "amount",
        ),
    ]:
        event = next((e for e in engine.events if predicate(e)), None)
        if event is None:
            continue
        injected = copy.deepcopy(base)
        injected["provenance"].setdefault(feature, []).append(event.event_id)
        findings = audit_features(engine, sunday, injected)
        cases.append(
            {
                "case": code,
                "injected": True,
                "expected_code": code,
                "detected": any(f["code"] == code for f in findings),
                "findings": findings,
            }
        )
    injected = copy.deepcopy(base)
    injected["features"]["velocity_1h"] += 1
    findings = audit_features(engine, sunday, injected)
    cases.append(
        {
            "case": "duplicate_counted_velocity",
            "injected": True,
            "expected_code": "duplicate_counted_velocity",
            "detected": any(f["code"] == "duplicate_counted_velocity" for f in findings),
            "findings": findings,
        }
    )
    clean = []
    for decision in decisions:
        if states[decision.transaction_id].get("missing"):
            continue
        findings = audit_features(engine, decision, states[decision.transaction_id])
        clean.append({"transaction_id": decision.transaction_id, "findings": findings})
    return {
        "protocol": "Four known faults injected into copied feature evidence; all complete historical snapshots are negative controls.",
        "true_positives": sum(c["detected"] for c in cases),
        "false_negatives": sum(not c["detected"] for c in cases),
        "false_positives": sum(bool(c["findings"]) for c in clean),
        "true_negatives": sum(not c["findings"] for c in clean),
        "cases": cases,
        "negative_controls": clean,
    }
