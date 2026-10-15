"""Versioned executable policy semantics and typed reproduction outcomes."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from .artifacts import ArtifactStore, MissingArtifact
from .engine import TemporalEngine, validate_window_seconds
from .schema import ContractError, Cutoff, Decision

FEATURE_IMPLEMENTATION = "temporal-aggregates-v1"
FEATURE_CODE_HASH = hashlib.sha256(Path(__file__).with_name("engine.py").read_bytes()).hexdigest()
RULE_IMPLEMENTATION = "priority-rules-v1"
RULE_CODE_HASH = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def archive_policy(
    store: ArtifactStore,
    *,
    name: str = "Original policy",
    window_seconds: int = 3600,
    review_amount: float = 350,
    review_score: float = 0.8,
    decline_amount: float = 900,
    decline_score: float = 1.0,
    model: dict | None = None,
    review_velocity: int = 6,
) -> str:
    validate_window_seconds(window_seconds)
    feature = store.put(
        "features",
        {
            "implementation": FEATURE_IMPLEMENTATION,
            "code_hash": FEATURE_CODE_HASH,
            "window_seconds": window_seconds,
            "outage_sentinel": -1,
        },
    )
    rules = store.put(
        "rules",
        {
            "implementation": RULE_IMPLEMENTATION,
            "code_hash": RULE_CODE_HASH,
            "review_amount": review_amount,
            "decline_amount": decline_amount,
            "review_score": review_score,
            "decline_score": decline_score,
            "review_velocity": review_velocity,
        },
    )
    model_key = store.put(
        "models",
        model
        or {
            "type": "fixture_logistic",
            "mode": "deterministic_fixture",
            "bias": -4.2,
            "weights": {"amount": 0.004, "velocity_1h": 0.25, "flagged": 1.2},
        },
    )
    return store.put(
        "policies",
        {
            "name": name,
            "schema_version": 1,
            "features": feature,
            "rules": rules,
            "model": model_key,
        },
    )


def score_model(store: ArtifactStore, spec: dict, features: dict) -> float:
    if spec.get("type") == "fixture_logistic":
        absent = set(spec["weights"]) - set(features)
        if absent:
            raise MissingArtifact(
                f"Model requires unavailable historical features: {', '.join(sorted(absent))}"
            )
        value = spec["bias"] + sum(features[k] * w for k, w in spec["weights"].items())
        return 1 / (1 + math.exp(-max(-700, min(700, value))))
    if spec.get("type") == "sklearn":
        from .modeling import predict_model

        try:
            return predict_model(store.root, spec["file_hash"], features)
        except (OSError, ValueError) as exc:
            raise MissingArtifact(
                f"Missing or invalid trained model {spec['file_hash']}: {exc}"
            ) from exc
    raise MissingArtifact(f"Model implementation unavailable: {spec.get('type')}")


def apply_rules(features: dict, score: float, rules: dict) -> tuple[str, list[dict]]:
    tests = [
        (
            "blocklist",
            bool(features["blocked"]),
            "decline",
            "Account was on the blocklist at the cutoff",
        ),
        (
            "amount_decline",
            features["amount"] >= rules["decline_amount"],
            "decline",
            f"Amount >= {rules['decline_amount']:g}",
        ),
        (
            "score_decline",
            score >= rules["decline_score"],
            "decline",
            f"Score >= {rules['decline_score']:g}",
        ),
        (
            "feature_outage",
            bool(features["outage"]),
            "review",
            "Velocity unavailable during a recorded outage; review fallback",
        ),
        (
            "amount_review",
            features["amount"] >= rules["review_amount"],
            "review",
            f"Amount >= {rules['review_amount']:g}",
        ),
        (
            "velocity_review",
            features["velocity_1h"] >= rules["review_velocity"],
            "review",
            f"Velocity >= {rules['review_velocity']}",
        ),
        (
            "score_review",
            score >= rules["review_score"],
            "review",
            f"Score >= {rules['review_score']:g}",
        ),
    ]
    trace = []
    action = "approve"
    selected = False
    for name, matched, result, message in tests:
        fired = matched and not selected
        trace.append(
            {
                "rule": name,
                "matched": matched,
                "selected": fired,
                "action": result,
                "message": message,
            }
        )
        if fired:
            action, selected = result, True
    return action, trace


def evaluate(
    engine: TemporalEngine,
    store: ArtifactStore,
    transaction_id: str,
    cutoff: Cutoff,
    policy_hash: str,
    *,
    regime: str = "available",
) -> dict:
    result = {
        "action": None,
        "score": None,
        "features": {},
        "provenance": {},
        "missing": [],
        "trace": [],
        "policy_hash": policy_hash,
        "regime": regime,
    }
    try:
        policy = store.get("policies", policy_hash)
        specs = {}
        for kind in ("features", "rules", "models"):
            key = policy["model" if kind == "models" else kind]
            try:
                specs[kind] = store.get(kind, key)
            except MissingArtifact as exc:
                result["missing"].append(str(exc))
        result["versions"] = {
            "policy": policy_hash,
            **{k: policy[k] for k in ("features", "rules", "model")},
        }
        if result["missing"]:
            return result
        if (
            specs["features"].get("implementation") != FEATURE_IMPLEMENTATION
            or specs["features"].get("code_hash") != FEATURE_CODE_HASH
        ):
            raise MissingArtifact(
                "Historical feature implementation/code hash is unavailable; no current-code substitution"
            )
        if (
            specs["rules"].get("implementation") != RULE_IMPLEMENTATION
            or specs["rules"].get("code_hash") != RULE_CODE_HASH
        ):
            raise MissingArtifact("Historical rule implementation is unavailable")
        state = engine.build(transaction_id, cutoff, specs["features"], regime)
        result.update(state)
        if result["missing"]:
            return result
        score = score_model(store, specs["models"], state["features"])
        action, trace = apply_rules(state["features"], score, specs["rules"])
        result.update(
            action=action,
            score=round(float(score), 12),
            trace=trace,
            model_mode=specs["models"].get("mode", "trained_cpu"),
        )
    except (MissingArtifact, ContractError, KeyError) as exc:
        result["missing"].append(str(exc))
    return result


def replay(engine: TemporalEngine, store: ArtifactStore, decision: Decision) -> dict:
    result = evaluate(engine, store, decision.transaction_id, decision.cutoff, decision.policy_hash)
    if result["missing"]:
        status = "incomplete"
    elif (
        result["action"] == decision.original_action
        and abs(result["score"] - decision.original_score) <= 1e-9
        and (not decision.feature_values or result["features"] == decision.feature_values)
    ):
        status = "matched"
    else:
        status = "mismatched"
    return {**result, "status": status}


def compare(
    engine: TemporalEngine, store: ArtifactStore, decision: Decision, candidate_hash: str
) -> dict:
    original = replay(engine, store, decision)
    candidate = evaluate(engine, store, decision.transaction_id, decision.cutoff, candidate_hash)
    explanation = []
    if original["missing"] or candidate["missing"]:
        explanation += [
            {"kind": "evidence", "message": item}
            for item in original["missing"] + candidate["missing"]
        ]
    old_versions, new_versions = original.get("versions", {}), candidate.get("versions", {})
    changes = [("features", "feature"), ("model", "model"), ("rules", "rule")]
    for key, kind in changes:
        if old_versions.get(key) != new_versions.get(key):
            msg = f"{kind.capitalize()} artifact changed: {str(old_versions.get(key))[:12]} → {str(new_versions.get(key))[:12]}"
            if kind == "feature":
                diffs = [
                    f"{k} {v:g} → {candidate['features'].get(k, 'unavailable')}"
                    for k, v in original["features"].items()
                    if candidate["features"].get(k) != v
                ]
                msg += "; " + (
                    ", ".join(diffs) if diffs else "no feature values changed for this transaction"
                )
            if kind == "model" and original["score"] is not None and candidate["score"] is not None:
                msg += f"; score {original['score']:.4f} → {candidate['score']:.4f}"
            explanation.append({"kind": kind, "message": msg})
    first = None
    # Fixed staged attribution: swap feature, then model, then rule. Interactions are order-dependent.
    if not original["missing"] and not candidate["missing"]:
        old_policy = store.get("policies", decision.policy_hash)
        new_policy = store.get("policies", candidate_hash)
        old_model = store.get("models", old_policy["model"])
        old_rules = store.get("rules", old_policy["rules"])
        new_model = store.get("models", new_policy["model"])
        stages = [
            (
                "feature",
                apply_rules(
                    candidate["features"],
                    score_model(store, old_model, candidate["features"]),
                    old_rules,
                )[0],
            ),
            (
                "model",
                apply_rules(
                    candidate["features"],
                    score_model(store, new_model, candidate["features"]),
                    old_rules,
                )[0],
            ),
            ("rule", candidate["action"]),
        ]
        previous_action = original["action"]
        for kind, action in stages:
            if action != previous_action:
                first = f"{kind.capitalize()} stage changed {previous_action} → {action} (feature → model → rule attribution order)"
                break
            previous_action = action
        if candidate["action"] != original["action"]:
            trigger = next(
                (r["message"] for r in candidate["trace"] if r["selected"]),
                "No candidate rule fired; approve default",
            )
            explanation.append({"kind": "rule", "message": trigger})
    if decision.original_action == "decline":
        explanation.append(
            {
                "kind": "evidence",
                "message": "Outcome under approval is unknown: this transaction was historically declined",
            }
        )
    return {
        "original": original,
        "candidate": candidate,
        "explanation": explanation,
        "first_divergence": first,
        "changed": original["action"] is not None
        and candidate["action"] is not None
        and original["action"] != candidate["action"],
    }
