"""Deterministic, availability-aware CPU baselines on observed outcomes only.

The caller supplies features reconstructed at each original decision cutoff. This
module never opens generator data, looks up present-day state, or discovers files.
Only locally trained, trusted joblib artifacts may be passed to ``predict_model``;
a content hash detects alteration, but does not make an untrusted pickle safe.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import platform
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import scipy
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import auc, average_precision_score, brier_score_loss, precision_recall_curve
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

FEATURE_NAMES = (
    "amount",
    "velocity_1h",
    "velocity_amount_1h",
    "blocked",
    "flagged",
    "outage",
)
REVIEW_CAPACITY = 0.10
FORMAT_VERSION = "riskreplay.sklearn.v1"
_VELOCITIES = frozenset({"velocity_1h", "velocity_amount_1h"})
_FORBIDDEN = frozenset({"oracle_label", "oracle_outcome", "oracle_probability", "ground_truth"})
_MICROSECOND = timedelta(microseconds=1)


class ModelingError(ValueError):
    """Invalid observed-data inputs or insufficient mature training evidence."""


class LeakageError(ModelingError):
    """A supplied split, label, or feature violates its temporal boundary."""


def _time(value: str | datetime, field: str) -> datetime:
    try:
        parsed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
        if not isinstance(parsed, datetime) or parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(UTC)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ModelingError(f"{field}: expected a timezone-aware ISO timestamp") from exc


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _feature_vector(features: dict[str, Any]) -> list[float]:
    """Use a fixed allowlist. Missing velocity is a declared outage sentinel."""
    if _FORBIDDEN.intersection(features):
        raise LeakageError("oracle fields must not enter observed-data features")
    result = []
    for name in FEATURE_NAMES:
        value = features.get(name)
        if value is None and name in _VELOCITIES:
            value = -1.0
        if value is None:
            raise ModelingError(f"missing historical feature {name!r}; reconstruct it first")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ModelingError(f"feature {name!r} must be numeric") from exc
        if not math.isfinite(number):
            raise ModelingError(f"feature {name!r} must be finite")
        if name in {"blocked", "flagged", "outage"} and number not in (0.0, 1.0):
            raise ModelingError(f"feature {name!r} must be 0 or 1")
        if name == "amount" and number < 0:
            raise ModelingError("feature 'amount' must be nonnegative")
        if name in _VELOCITIES and number < 0 and number != -1:
            raise ModelingError(f"feature {name!r} must be nonnegative or -1 when unavailable")
        result.append(number)
    return result


def _check_feature_times(row: dict[str, Any]) -> None:
    decision = _time(row["decision_time"], "decision_time")
    # Optional provenance is checked if supplied. The historical engine is the
    # source of truth when callers pass only the minimal row contract.
    for field in ("feature_available_at", "feature_event_time"):
        value = row.get(field)
        if value is None:
            continue
        entries = value.items() if isinstance(value, dict) else [("all", value)]
        for feature, timestamp in entries:
            if _time(timestamp, f"{field}.{feature}") > decision:
                raise LeakageError(
                    f"{row['transaction_id']}: feature {feature} {field} is after decision_time"
                )


def _label_history(history: Any, decision: datetime, transaction_id: str) -> list[dict[str, Any]]:
    """Validate observed outcome identities without mixing targets into features."""
    if not isinstance(history, list):
        raise ModelingError(f"{transaction_id}: label_history must be a list")
    normalized = []
    for entry in history:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("event_id"), str)
            or not entry["event_id"]
        ):
            raise ModelingError(f"{transaction_id}: label history needs a nonempty event_id")
        event_time = _time(entry.get("event_time"), "outcome.event_time")
        available = _time(entry.get("available_at"), "outcome.available_at")
        sequence = entry.get("delivery_seq")
        label = entry.get("label")
        predecessor = entry.get("supersedes")
        if type(sequence) is not int or sequence < 1:
            raise ModelingError(
                f"{transaction_id}: outcome delivery_seq must be a positive integer"
            )
        if type(label) is not int or label not in (0, 1):
            raise ModelingError(f"{transaction_id}: outcome label must be integer 0 or 1")
        if predecessor is not None and (not isinstance(predecessor, str) or not predecessor):
            raise ModelingError(f"{transaction_id}: outcome supersedes must be an event ID or null")
        if available < event_time or available < decision:
            raise LeakageError(
                f"{transaction_id}: outcome availability precedes its event or decision"
            )
        normalized.append(
            {
                "event_id": entry["event_id"],
                "event_time": _iso(event_time),
                "available_at": _iso(available),
                "delivery_seq": sequence,
                "label": label,
                "supersedes": predecessor,
            }
        )
    normalized.sort(
        key=lambda item: (_time(item["available_at"], "available_at"), item["delivery_seq"])
    )
    identities: dict[str, dict[str, Any]] = {}
    sequences: set[int] = set()
    replaced: set[str] = set()
    for item in normalized:
        if item["event_id"] in identities or item["delivery_seq"] in sequences:
            raise ModelingError(
                f"{transaction_id}: duplicate outcome identity or delivery sequence"
            )
        previous = item["supersedes"]
        if previous is not None and (previous not in identities or previous in replaced):
            raise ModelingError(
                f"{transaction_id}: unknown or branched outcome correction predecessor"
            )
        if previous is not None:
            old = identities[previous]
            if (_time(item["available_at"], "available_at"), item["delivery_seq"]) <= (
                _time(old["available_at"], "available_at"),
                old["delivery_seq"],
            ):
                raise ModelingError(
                    f"{transaction_id}: outcome correction must arrive after predecessor"
                )
            replaced.add(previous)
        identities[item["event_id"]] = item
        sequences.add(item["delivery_seq"])
    return normalized


def _normalized_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen: set[str] = set()
    for original in rows:
        if _FORBIDDEN.intersection(original):
            raise LeakageError("oracle fields must not enter the observed-data model pipeline")
        transaction_id = original.get("transaction_id")
        if not isinstance(transaction_id, str) or not transaction_id:
            raise ModelingError("transaction_id must be a nonempty string")
        if transaction_id in seen:
            raise ModelingError(f"duplicate model row for transaction_id {transaction_id!r}")
        seen.add(transaction_id)
        decision = _time(original.get("decision_time"), f"{transaction_id}.decision_time")
        action = original.get("observed_action")
        if action not in {"approve", "review", "decline"}:
            raise ModelingError(f"{transaction_id}: observed_action must be approve/review/decline")
        label = original.get("label")
        if label is not None and (type(label) is not int or label not in (0, 1)):
            raise ModelingError(f"{transaction_id}: label must be integer 0, 1, or null")
        available = original.get("label_available_at")
        if label is not None and available is None:
            raise ModelingError(f"{transaction_id}: observed label needs label_available_at")
        if available is not None:
            available = _time(available, f"{transaction_id}.label_available_at")
            if available < decision:
                raise LeakageError(f"{transaction_id}: label became available before decision_time")
        # A declined payment has no observed outcome under approval. Reject an
        # accidental oracle join instead of quietly teaching from that field.
        if action == "decline" and label is not None:
            raise LeakageError(
                f"{transaction_id}: declined transaction cannot have an approval label"
            )
        missing = original.get("missing_state", [])
        if not isinstance(missing, list) or any(
            not isinstance(item, str) or not item for item in missing
        ):
            raise ModelingError(f"{transaction_id}: missing_state must be a list of reasons")
        try:
            amount = (
                None if missing and original.get("amount") is None else float(original["amount"])
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelingError(f"{transaction_id}: amount must be numeric") from exc
        if amount is not None and (not math.isfinite(amount) or amount < 0):
            raise ModelingError(f"{transaction_id}: amount must be finite and nonnegative")
        supplied = dict(original.get("features") or {})
        if _FORBIDDEN.intersection(supplied):
            raise LeakageError("oracle fields must not enter observed-data features")
        features = {}
        if not missing:
            supplied.setdefault("amount", amount)
            vector = _feature_vector(supplied)
            if vector[0] != amount:
                raise ModelingError(
                    f"{transaction_id}: amount differs from decision-time feature amount"
                )
            features = dict(zip(FEATURE_NAMES, vector, strict=True))
        _check_feature_times(original)
        cohort = original.get("cohort", "unknown")
        if not isinstance(cohort, str) or not cohort:
            raise ModelingError(f"{transaction_id}: cohort must be a nonempty string")
        row = {
            "transaction_id": transaction_id,
            "decision_time": _iso(decision),
            "label": label,
            "label_available_at": _iso(available) if available is not None else None,
            "observed_action": action,
            "cohort": cohort,
            "amount": amount,
            "features": features,
            "missing_state": list(missing),
        }
        if "label_history" in original:
            history = _label_history(original["label_history"], decision, transaction_id)
            if action == "decline" and history:
                raise LeakageError(
                    f"{transaction_id}: declined transaction cannot have approval label history"
                )
            if not history and label is not None:
                raise ModelingError(
                    f"{transaction_id}: non-null label has no supplied outcome history"
                )
            row["label_history"] = history
        result.append(row)
    return sorted(
        result,
        key=lambda row: (_time(row["decision_time"], "decision_time"), row["transaction_id"]),
    )


def validate_training_rows(
    rows: list[dict[str, Any]],
    training_cutoff: str | datetime,
    *,
    prediction_before: str | datetime | None = None,
) -> None:
    """Reject future/unknown labels and features in an already selected fit set.

    Labels are available inclusively at ``training_cutoff``. If supplied,
    ``prediction_before`` is an exclusive decision-time boundary. This validator
    intentionally raises rather than dropping leaky rows from a proposed fit set.
    """
    cutoff = _time(training_cutoff, "training_cutoff")
    boundary = _time(prediction_before, "prediction_before") if prediction_before else None
    normalized = _normalized_rows(rows)
    for row in normalized:
        transaction_id = row["transaction_id"]
        if row["missing_state"]:
            raise LeakageError(f"{transaction_id}: missing historical state cannot enter fitting")
        decision = _time(row["decision_time"], "decision_time")
        if decision > cutoff or (boundary is not None and decision >= boundary):
            raise LeakageError(f"{transaction_id}: prediction lies outside the training window")
        if row["label"] is None or row["label_available_at"] is None:
            raise LeakageError(f"{transaction_id}: unknown label cannot be a training target")
        if _time(row["label_available_at"], "label_available_at") > cutoff:
            raise LeakageError(f"{transaction_id}: label was unavailable at training cutoff")
        if row["observed_action"] == "decline":
            raise LeakageError(f"{transaction_id}: declined outcome is unobserved")


def validate_chronological_splits(
    train_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
) -> None:
    """Reject overlap, reused transactions, and timestamp ties across split boundaries."""
    seen: set[str] = set()
    previous_end: datetime | None = None
    for name, rows in (("train", train_rows), ("validation", validation_rows), ("test", test_rows)):
        if not rows:
            raise LeakageError(f"{name} chronological window is empty")
        times = []
        for row in rows:
            transaction_id = row["transaction_id"]
            if transaction_id in seen:
                raise LeakageError(f"{transaction_id}: transaction reused across or within splits")
            seen.add(transaction_id)
            times.append(_time(row["decision_time"], "decision_time"))
        if previous_end is not None and min(times) <= previous_end:
            raise LeakageError(f"{name} overlaps an earlier chronological split (including ties)")
        previous_end = max(times)


def _row_at_cutoff(row: dict[str, Any], cutoff: datetime) -> dict[str, Any]:
    """Resolve the target known then, omitting future corrections from fit hashes."""
    if "label_history" not in row:
        return row
    result = {key: value for key, value in row.items() if key != "label_history"}
    visible = [
        item
        for item in row["label_history"]
        if _time(item["available_at"], "outcome.available_at") <= cutoff
        and _time(item["event_time"], "outcome.event_time") <= cutoff
    ]
    superseded = {item["supersedes"] for item in visible if item["supersedes"] is not None}
    active = [item for item in visible if item["event_id"] not in superseded]
    if active:
        latest = max(
            active,
            key=lambda item: (
                _time(item["event_time"], "event_time"),
                _time(item["available_at"], "available_at"),
                item["delivery_seq"],
            ),
        )
        result["label"] = latest["label"]
        result["label_available_at"] = latest["available_at"]
    else:
        result["label"] = None
        pending = [
            item["available_at"]
            for item in row["label_history"]
            if _time(item["available_at"], "available_at") > cutoff
        ]
        # Preserve a future arrival hint from model_rows without its unavailable target.
        if row["label_available_at"] is not None:
            pending.append(row["label_available_at"])
        result["label_available_at"] = (
            min(pending, key=lambda value: _time(value, "available_at")) if pending else None
        )
    return result


def _label_status(row: dict[str, Any], cutoff: datetime) -> str:
    row = _row_at_cutoff(row, cutoff)
    if row["observed_action"] == "decline":
        return "declined_unobserved"
    available = row["label_available_at"]
    if available is not None and _time(available, "label_available_at") > cutoff:
        return "immature"
    if row["label"] is None or available is None:
        return "unobserved"
    return "mature_observed"


def _mature(rows: list[dict[str, Any]], cutoff: datetime) -> list[dict[str, Any]]:
    resolved = [_row_at_cutoff(row, cutoff) for row in rows]
    return [row for row in resolved if _label_status(row, cutoff) == "mature_observed"]


def _counts(rows: list[dict[str, Any]], cutoff: datetime) -> dict[str, Any]:
    statuses = [_label_status(row, cutoff) for row in rows]
    mature = _mature(rows, cutoff)
    return {
        "total": len(rows),
        "mature_observed": len(mature),
        "observed_fraud": sum(row["label"] == 1 for row in mature),
        "observed_genuine": sum(row["label"] == 0 for row in mature),
        "immature": statuses.count("immature"),
        "declined_unobserved": statuses.count("declined_unobserved"),
        "unobserved": statuses.count("unobserved"),
        # State coverage overlaps label maturity: a known label does not make
        # unavailable historical features safe to fit or score.
        "missing_state": sum(bool(row["missing_state"]) for row in rows),
        "scoreable": sum(not row["missing_state"] for row in rows),
        "missing_state_transaction_ids": [
            row["transaction_id"] for row in rows if row["missing_state"]
        ],
        "label_cutoff_inclusive": _iso(cutoff),
    }


def _matrix(rows: list[dict[str, Any]]) -> np.ndarray:
    return np.asarray([_feature_vector(row["features"]) for row in rows], dtype=np.float64).reshape(
        len(rows), len(FEATURE_NAMES)
    )


def _labels(rows: list[dict[str, Any]]) -> np.ndarray:
    # All fit/metric callers first select mature observed rows. Never coerce null to zero.
    if any(row["label"] not in (0, 1) or row["label"] is None for row in rows):
        raise LeakageError("only explicitly observed labels may be converted to model targets")
    return np.asarray([row["label"] for row in rows], dtype=np.int64)


def _rules_score(features: dict[str, float]) -> float:
    if features["blocked"]:
        return 0.98
    if features["flagged"]:
        return 0.65
    if features["outage"] or any(features[name] == -1 for name in _VELOCITIES):
        return 0.30
    if features["velocity_1h"] >= 4 or features["velocity_amount_1h"] >= 1500:
        return 0.45
    return 0.20 if features["amount"] >= 500 else 0.02


def _ratio(numerator: float | int, denominator: float | int) -> float | None:
    return float(numerator / denominator) if denominator else None


def _metrics(
    rows: list[dict[str, Any]],
    scores: dict[str, float],
    cutoff: datetime,
    selected: set[str],
    capacity_denominator: int,
) -> dict[str, Any]:
    mature = _mature([row for row in rows if row["transaction_id"] in scores], cutoff)
    y = _labels(mature)
    p = np.asarray([scores[row["transaction_id"]] for row in mature], dtype=np.float64)
    positives = int(y.sum())
    if positives:
        precision, recall, _ = precision_recall_curve(y, p)
        pr_auc = float(auc(recall, precision))
        ap = float(average_precision_score(y, p))
    else:
        pr_auc, ap = None, None
    bins = []
    for index in range(10):
        lower, upper = index / 10, (index + 1) / 10
        mask = (p >= lower) & ((p < upper) if index < 9 else (p <= upper))
        count = int(mask.sum())
        bins.append(
            {
                "lower": lower,
                "upper": upper,
                "upper_inclusive": index == 9,
                "count": count,
                "observed_fraud": int(y[mask].sum()),
                "mean_prediction": float(p[mask].mean()) if count else None,
                "fraud_rate": float(y[mask].mean()) if count else None,
            }
        )
    chosen = [row for row in rows if row["transaction_id"] in selected]
    known_chosen = [row for row in mature if row["transaction_id"] in selected]
    true_positives = sum(row["label"] == 1 for row in known_chosen)
    observed_amount = sum(row["amount"] for row in known_chosen)
    captured_fraud_amount = sum(row["amount"] for row in known_chosen if row["label"] == 1)
    fraud_amount = sum(row["amount"] for row in mature if row["label"] == 1)
    return {
        "counts": _counts(rows, cutoff),
        "metric_population": "mature observed outcomes with reconstructable features under the recorded policy only",
        "metric_n": len(mature),
        "average_precision": ap,
        "average_precision_definition": "non-interpolated recall-increment weighted precision",
        "pr_auc": pr_auc,
        "pr_auc_definition": "trapezoidal area under the precision-recall curve",
        "positive_class": "observed fraud = 1",
        "observed_prevalence": _ratio(positives, len(mature)),
        "ranking_status": "defined" if positives else "undefined: no mature observed positives",
        "brier_score": float(brier_score_loss(y, p)) if mature else None,
        "reliability_bins": bins,
        "review": {
            "capacity_fraction": REVIEW_CAPACITY,
            "capacity_denominator_all_test_transactions": capacity_denominator,
            "capacity_slots_global": math.floor(REVIEW_CAPACITY * capacity_denominator),
            "allocation": "scoreable transactions by score descending; decision_time then transaction_id breaks ties; missing-state rows remain in the capacity denominator",
            "selected": len(chosen),
            "selected_mature_observed": len(known_chosen),
            "selected_unknown_outcomes": len(chosen) - len(known_chosen),
            "observed_fraud_selected": true_positives,
            "observed_fraud_denominator": positives,
            "precision": _ratio(true_positives, len(known_chosen)),
            "recall": _ratio(true_positives, positives),
            "precision_denominator": len(known_chosen),
            "precision_scope": "mature observed subset of selected transactions",
            "full_selected_precision_identified": len(known_chosen) == len(chosen) and bool(chosen),
        },
        "amount_weighted": {
            "observed_fraud_amount_selected": captured_fraud_amount,
            "observed_fraud_amount_denominator": fraud_amount,
            "selected_observed_amount_denominator": observed_amount,
            "recall": _ratio(captured_fraud_amount, fraud_amount),
            "precision": _ratio(captured_fraud_amount, observed_amount),
            "assumption": (
                "Nonnegative amounts in one nominal currency weight mature observed transactions. "
                "Transaction amount is not net loss; unknown and declined outcomes are excluded. "
                "These are descriptive capture ratios, not recoverable revenue or prevented loss."
            ),
        },
    }


def _selected(rows: list[dict[str, Any]], scores: dict[str, float]) -> set[str]:
    ordered = sorted(
        [row for row in rows if row["transaction_id"] in scores],
        key=lambda row: (
            -scores[row["transaction_id"]],
            _time(row["decision_time"], "decision_time"),
            row["transaction_id"],
        ),
    )
    return {row["transaction_id"] for row in ordered[: math.floor(REVIEW_CAPACITY * len(rows))]}


def _report_scores(
    rows: list[dict[str, Any]], scores: dict[str, float], cutoff: datetime
) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    selected = _selected(rows, scores)
    metrics = _metrics(rows, scores, cutoff, selected, len(rows))
    cohorts = {
        cohort: _metrics(
            [row for row in rows if row["cohort"] == cohort], scores, cutoff, selected, len(rows)
        )
        for cohort in sorted({row["cohort"] for row in rows})
    }
    return metrics, cohorts, selected


def _write_artifact(root: Path, bundle: dict[str, Any]) -> str:
    buffer = io.BytesIO()
    joblib.dump(bundle, buffer, compress=0, protocol=5)
    data = buffer.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    directory = root / "models"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}.joblib"
    try:
        with path.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ModelingError(
                f"refusing to overwrite modified immutable artifact {path}"
            ) from None
    return digest


@lru_cache(maxsize=16)
def _load_verified_bytes(digest: str, data: bytes) -> dict[str, Any]:
    # The caller hashes *these same bytes* before this function. There is no
    # separate path-based deserialization step susceptible to a read/verify race.
    bundle = joblib.load(io.BytesIO(data))
    if not isinstance(bundle, dict) or bundle.get("format_version") != FORMAT_VERSION:
        raise ModelingError(f"unsupported model artifact format: {digest}")
    if bundle.get("feature_names") != list(FEATURE_NAMES):
        raise ModelingError("model artifact uses an unsupported historical feature schema")
    return bundle


def predict_model(artifact_root: Path, file_hash: str, features: dict[str, Any]) -> float:
    """Score using a hash-verified, locally trained trusted artifact.

    Do not expose arbitrary joblib upload/loading in an API. Joblib is executable
    serialization; integrity verification alone does not establish provenance.
    Every call verifies file bytes, including when deserialization is cached.
    """
    if not isinstance(file_hash, str) or re.fullmatch(r"[a-f0-9]{64}", file_hash) is None:
        raise ModelingError("model file_hash must be a lowercase SHA-256 digest")
    root = Path(artifact_root).resolve()
    path = root / "models" / f"{file_hash}.joblib"
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ModelingError("model artifact must be a regular local file inside the artifact root")
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise ModelingError(f"missing historical model artifact {file_hash}") from exc
    if hashlib.sha256(data).hexdigest() != file_hash:
        raise ModelingError(f"model artifact hash mismatch: {file_hash}")
    bundle = _load_verified_bytes(file_hash, data)
    matrix = np.asarray([_feature_vector(features)], dtype=np.float64)
    with threadpool_limits(limits=1):
        return float(bundle["predictor"].predict_proba(matrix)[0, 1])


def train_models(
    rows: list[dict[str, Any]],
    output_dir: Path,
    seed: int = 17,
    *,
    evaluation_cutoff: str | datetime | None = None,
) -> dict[str, Any]:
    """Train real CPU models and evaluate one frozen chronological test window.

    Time-range windows are 60% train, 20% validation and 20% test. The validation
    window is subdivided chronologically for tuning (first half) and calibration
    (second half). Boundaries are determined from decision times, never labels.
    No final refit occurs: preprocessing and both estimators see training rows
    only. An optional later evaluation cutoff changes label maturity, not fitting.
    """
    normalized = _normalized_rows(rows)
    if len(normalized) < 30:
        raise ModelingError("at least 30 chronological transactions are required for three windows")
    start = _time(normalized[0]["decision_time"], "decision_time")
    end = _time(normalized[-1]["decision_time"], "decision_time")
    if end - start < timedelta(seconds=1):
        raise ModelingError("transactions must span at least one second for chronological windows")
    validation_start = start + (end - start) * 0.60
    test_start = start + (end - start) * 0.80
    calibration_start = validation_start + (test_start - validation_start) * 0.50
    train_cutoff = validation_start - _MICROSECOND
    validation_cutoff = test_start - _MICROSECOND
    evaluate_at = _time(evaluation_cutoff, "evaluation_cutoff") if evaluation_cutoff else end
    if evaluate_at < end:
        raise ModelingError("evaluation_cutoff must include the final test decision")

    train_window = [
        r for r in normalized if _time(r["decision_time"], "decision_time") < validation_start
    ]
    validation_window = [
        r
        for r in normalized
        if validation_start <= _time(r["decision_time"], "decision_time") < test_start
    ]
    test_window = [
        r for r in normalized if _time(r["decision_time"], "decision_time") >= test_start
    ]
    validate_chronological_splits(train_window, validation_window, test_window)
    training = _mature([r for r in train_window if not r["missing_state"]], train_cutoff)
    validation = _mature(
        [r for r in validation_window if not r["missing_state"]], validation_cutoff
    )
    tuning = [
        r for r in validation if _time(r["decision_time"], "decision_time") < calibration_start
    ]
    calibration = [
        r for r in validation if _time(r["decision_time"], "decision_time") >= calibration_start
    ]
    validate_training_rows(training, train_cutoff, prediction_before=validation_start)
    validate_training_rows(validation, validation_cutoff, prediction_before=test_start)
    if len(training) < 20 or set(_labels(training)) != {0, 1}:
        raise ModelingError(
            "training needs at least 20 mature observed labels and both classes before validation; "
            f"found {_counts(train_window, train_cutoff)}"
        )
    calibration_status = "fitted on the later validation half only"
    if (
        len(calibration) < 30
        or min(sum(r["label"] == value for r in calibration) for value in (0, 1)) < 3
    ):
        calibration_status = "skipped: later validation half needs >=30 labels and >=3 per class"
        calibration = []
    # If the first half has no mature labels, all validation can tune only when
    # calibration is skipped. Otherwise retain an explicitly predetermined model.
    if not tuning and not calibration:
        tuning = validation
    x_train, y_train = _matrix(training), _labels(training)
    x_tune, y_tune = _matrix(tuning), _labels(tuning)
    code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    schema = {"names": list(FEATURE_NAMES), "missing_velocity": -1, "version": "availability-v1"}
    versions = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "scikit_learn": sklearn.__version__,
        "joblib": joblib.__version__,
    }
    metadata = {
        "seed": seed,
        "code_hash": code_hash,
        "feature_schema_hash": _hash(schema),
        "versions": versions,
        "threads": 1,
        "train_rows_hash": _hash(training),
        "tuning_rows_hash": _hash(tuning),
        "calibration_rows_hash": _hash(calibration),
        "training_label_cutoff_inclusive": _iso(train_cutoff),
        "validation_label_cutoff_inclusive": _iso(validation_cutoff),
        "preprocessing_fit_transaction_ids": [r["transaction_id"] for r in training],
        "training_transaction_ids": [r["transaction_id"] for r in training],
        "training_targets": [
            {key: row[key] for key in ("transaction_id", "label", "label_available_at")}
            for row in training
        ],
        "tuning_transaction_ids": [r["transaction_id"] for r in tuning],
        "calibration_transaction_ids": [r["transaction_id"] for r in calibration],
    }
    logistic = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            (
                "classifier",
                LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000, random_state=seed),
            ),
        ]
    )
    grid = [
        {"learning_rate": 0.06, "max_iter": 70, "max_leaf_nodes": 7, "l2_regularization": 2.0},
        {"learning_rate": 0.10, "max_iter": 100, "max_leaf_nodes": 15, "l2_regularization": 5.0},
    ]
    trials = []
    fitted = []
    with threadpool_limits(limits=1):
        logistic.fit(x_train, y_train)
        for index, parameters in enumerate(grid):
            estimator = HistGradientBoostingClassifier(
                **parameters,
                min_samples_leaf=15,
                early_stopping=False,
                categorical_features=None,
                random_state=seed,
            )
            estimator.fit(x_train, y_train)
            probabilities = estimator.predict_proba(x_tune)[:, 1] if tuning else np.asarray([])
            ap = float(average_precision_score(y_tune, probabilities)) if y_tune.sum() else None
            brier = float(brier_score_loss(y_tune, probabilities)) if tuning else None
            trials.append(
                {
                    "index": index,
                    "parameters": estimator.get_params(),
                    "average_precision": ap,
                    "brier_score": brier,
                    "n": len(tuning),
                }
            )
            fitted.append(estimator)
        best = max(
            range(len(grid)),
            key=lambda index: (
                trials[index]["average_precision"]
                if trials[index]["average_precision"] is not None
                else -1,
                -trials[index]["brier_score"] if trials[index]["brier_score"] is not None else -1,
                -index,
            ),
        )
        estimators = {"logistic": logistic, "gradient_boosted": fitted[best]}
        models: dict[str, Any] = {}
        all_scores = {}
        raw_scores = {}
        all_selections = {}
        scoreable_test = [row for row in test_window if not row["missing_state"]]
        x_test = _matrix(scoreable_test)
        for name, estimator in estimators.items():
            predictor = estimator
            if calibration:
                predictor = CalibratedClassifierCV(
                    FrozenEstimator(estimator), method="sigmoid", cv=2
                )
                predictor.fit(_matrix(calibration), _labels(calibration))
            bundle = {
                "format_version": FORMAT_VERSION,
                "kind": name,
                "feature_names": list(FEATURE_NAMES),
                "metadata": metadata,
                "base_estimator": estimator,
                "predictor": predictor,
            }
            digest = _write_artifact(Path(output_dir), bundle)
            scores = dict(
                zip(
                    [r["transaction_id"] for r in scoreable_test],
                    map(float, predictor.predict_proba(x_test)[:, 1]) if scoreable_test else [],
                    strict=True,
                )
            )
            raw_scores[name] = dict(
                zip(
                    [r["transaction_id"] for r in scoreable_test],
                    map(float, estimator.predict_proba(x_test)[:, 1]) if scoreable_test else [],
                    strict=True,
                )
            )
            all_scores[name] = scores
            metrics, cohorts, selected = _report_scores(test_window, scores, evaluate_at)
            all_selections[name] = selected
            models[name] = {
                "file_hash": digest,
                "artifact_path": f"models/{digest}.joblib",
                "feature_names": list(FEATURE_NAMES),
                "code_hash": code_hash,
                "feature_schema_hash": metadata["feature_schema_hash"],
                "training_rows_hash": metadata["train_rows_hash"],
                "seed": seed,
                "n_training": len(training),
                "parameters": estimator.named_steps["classifier"].get_params()
                if name == "logistic"
                else estimator.get_params(),
                "preprocessing": {
                    "imputer": {"strategy": "median", "fit_population": "training only"},
                    "scaler": {"method": "StandardScaler", "fit_population": "training only"},
                    "missing_velocity_sentinel": -1,
                }
                if name == "logistic"
                else {
                    "method": "native numeric features",
                    "missing_velocity_sentinel": -1,
                },
                "calibration": {
                    "method": "sigmoid" if calibration else None,
                    "status": calibration_status,
                    "n": len(calibration),
                    "class_counts": {
                        str(value): sum(row["label"] == value for row in calibration)
                        for value in (0, 1)
                    },
                    "prediction_folds": 2 if calibration else None,
                    "base_estimator_refitted": False,
                },
                "metrics": metrics,
                "cohorts": cohorts,
                "raw_probability_metrics": _report_scores(
                    test_window, raw_scores[name], evaluate_at
                )[0],
            }

    rules_scores = {r["transaction_id"]: _rules_score(r["features"]) for r in scoreable_test}
    all_scores["rules"] = rules_scores
    rules_metrics, rules_cohorts, rules_selected = _report_scores(
        test_window, rules_scores, evaluate_at
    )
    all_selections["rules"] = rules_selected
    rule_definition = [
        "blocked -> 0.98",
        "flagged -> 0.65",
        "outage or unavailable velocity -> 0.30",
        "velocity_1h >= 4 or velocity_amount_1h >= 1500 -> 0.45",
        "amount >= 500 -> 0.20",
        "otherwise -> 0.02",
    ]
    report = {
        "schema_version": 1,
        "mode": "observed_only",
        "seed": seed,
        "dataset_hash": _hash(normalized),
        "code_hash": code_hash,
        "feature_schema_hash": metadata["feature_schema_hash"],
        "versions": versions,
        "feature_schema": schema,
        "splits": {
            "method": "60/20/20 percent of all selected decision-time span before missing-state exclusion; timestamp ties stay together",
            "boundary_semantics": "window start inclusive, next window start exclusive; labels <= cutoff",
            "start_inclusive": _iso(start),
            "validation_start_inclusive": _iso(validation_start),
            "calibration_start_inclusive": _iso(calibration_start),
            "test_start_inclusive": _iso(test_start),
            "test_end_inclusive": _iso(end),
            "training_label_cutoff_inclusive": _iso(train_cutoff),
            "validation_label_cutoff_inclusive": _iso(validation_cutoff),
            "evaluation_cutoff_inclusive": _iso(evaluate_at),
            "train": _counts(train_window, train_cutoff),
            "validation": _counts(validation_window, validation_cutoff),
            "test": _counts(test_window, evaluate_at),
            "frozen_test_transaction_ids": [r["transaction_id"] for r in test_window],
            "frozen_test_rows_hash": _hash(test_window),
        },
        "training_audit": metadata,
        "tuning": {
            "objective": "maximize validation average precision, then minimize Brier, then grid order",
            "selected_trial": best,
            "trials": trials,
            "status": "validation tuned"
            if tuning
            else "no eligible tuning rows with mature labels and historical features; preset first trial",
        },
        "models": models,
        "rules_baseline": {
            "definition": rule_definition,
            "rules_hash": _hash(rule_definition),
            "score_kind": "fixed heuristic scores, not calibrated probabilities",
            "metrics": rules_metrics,
            "cohorts": rules_cohorts,
        },
        "test_rows": [
            {
                **row,
                "label": row["label"]
                if _label_status(row, evaluate_at) == "mature_observed"
                else None,
                "label_status": _label_status(row, evaluate_at),
                "scores": {
                    name: scores.get(row["transaction_id"]) for name, scores in all_scores.items()
                },
                "raw_scores": {
                    name: scores.get(row["transaction_id"]) for name, scores in raw_scores.items()
                },
                "selected_for_review": {
                    name: row["transaction_id"] in chosen for name, chosen in all_selections.items()
                },
            }
            for source_row in test_window
            for row in [_row_at_cutoff(source_row, evaluate_at)]
        ],
        "assumptions": [
            "Features must come from historical availability-aware reconstruction; optional feature timestamps are checked.",
            "Missing-state rows remain in frozen windows and label/capacity denominators; fitting and scoring exclude them, with null scores and explicit coverage counts. Metric denominators contain only mature scored rows.",
            "Base estimators and preprocessing fit on mature training rows only; final test is never used for fitting or tuning.",
            "Calibration uses a disjoint later validation half; no final refit uses validation or test features.",
            "Evaluation as-of defaults to the last decision time; later-arriving labels are immature, never negatives.",
            "Observed outcome histories, when supplied, are resolved separately at each label cutoff; future corrections cannot remove or change prior fit targets.",
            "Review capacity is floor(10% of all test transactions), including transactions with unknown outcomes.",
            "Cohort review metrics use the global review selection, not a new per-cohort capacity allocation.",
            "Observed-only discrimination/calibration are selection-biased and do not identify declined outcomes under approval.",
            "No recovered revenue, counterfactual fraud loss reduction, or real merchant validation is estimated.",
            "Joblib artifacts are trusted local training outputs; never deserialize externally supplied joblib files.",
        ],
    }
    # Exercise strict JSON compatibility before returning a purported exportable report.
    _canonical(report)
    return report
