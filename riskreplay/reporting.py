"""Portable reports with raw denominators and no counterfactual ROI."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import shutil
import tempfile
from pathlib import Path

from .schema import digest
from .storage import write_json

RUN_FILES = (
    "report.json",
    "integrity.json",
    "evaluation.json",
    "decisions.csv",
    "report.html",
    "inspector.html",
)


def semantic_report(report: dict) -> dict:
    return {
        key: value
        for key, value in report.items()
        if key not in {"run_id", "created_at", "performance", "semantic_hash"}
    }


def validate_report(report: dict) -> None:
    """Recompute recorded semantic integrity; hashes detect alteration, not source trust."""
    if not isinstance(report, dict):
        raise ValueError("Persisted report must be an object")
    expected = report.get("semantic_hash")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("Persisted report is missing a valid semantic hash")
    if expected != digest(semantic_report(report)):
        raise ValueError("Persisted report semantic hash does not match its contents")


def validate_run_files(folder: Path, filename: str | None = None) -> None:
    """Check generated file hashes; earlier runs without a manifest retain semantic checks."""
    selected = (filename,) if filename is not None else RUN_FILES
    if any(name not in RUN_FILES for name in selected):
        raise ValueError("Unknown run artifact")
    manifest_path = folder / "manifest.json"
    hashes = None
    if manifest_path.is_symlink():
        raise ValueError("Run manifest must not be a symlink")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if (
            not isinstance(manifest, dict)
            or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1
            or manifest.get("run_id") != folder.name
            or not isinstance(manifest.get("files"), dict)
            or set(manifest["files"]) != set(RUN_FILES)
        ):
            raise ValueError("Invalid run artifact manifest")
        hashes = manifest["files"]
    for name in selected:
        path = folder / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Run artifact is missing or invalid: {name}")
        if hashes is not None and hashlib.sha256(path.read_bytes()).hexdigest() != hashes[name]:
            raise ValueError(f"Run artifact checksum changed: {name}")


def save_report(root: Path, report: dict) -> Path:
    semantic_hash = digest(semantic_report(report))
    report["semantic_hash"] = semantic_hash
    folder = Path(root) / "runs" / report["run_id"]
    if folder.exists():
        existing = json.loads((folder / "report.json").read_text())
        validate_report(existing)
        if existing.get("semantic_hash") != semantic_hash:
            raise ValueError(
                "Run identity collision: semantic results changed; use a new run identity"
            )
        validate_run_files(folder)
        return folder
    folder.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".writing-", dir=folder.parent))
    try:
        _write_run_files(temporary, report, semantic_hash)
        temporary.rename(folder)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return folder


def _write_run_files(folder: Path, report: dict, semantic_hash: str) -> None:
    """Finish every export and checksum before publishing the run directory."""
    write_json(folder / "report.json", report)
    write_json(folder / "integrity.json", report["integrity"])
    write_json(folder / "evaluation.json", report["evaluation"])
    columns = [
        "transaction_id",
        "decision_time",
        "status",
        "recorded_action",
        "replayed_action",
        "candidate_action",
        "original_score",
        "candidate_score",
        "label_status",
        "first_divergence",
    ]
    with (folder / "decisions.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for decision in report["decisions"]:
            # Spreadsheet formula injection defense applies even to local imported IDs.
            row = {
                k: (
                    "'" + str(v)
                    if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r"))
                    else v
                )
                for k, v in decision.items()
            }
            writer.writerow(row)
    summary = report["summary"]
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(d.get(k, '')))}</td>"
            for k in [
                "transaction_id",
                "status",
                "recorded_action",
                "candidate_action",
                "label_status",
            ]
        )
        + "</tr>"
        for d in report["decisions"]
    )
    metrics = "".join(
        f"<h3>{html.escape(name.replace('_', ' ').title())}</h3><pre>{html.escape(json.dumps(model['metrics'], indent=2))}</pre>"
        for name, model in report["evaluation"].get("models", {}).items()
    )
    body = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RiskReplay · {report["run_id"]}</title>
    <style>body{{font:16px system-ui;max-width:1120px;margin:48px auto;padding:0 24px;color:#173c36;background:#fafbf8}}h1{{font-size:40px}}.note{{border-left:4px solid #aa7830;padding:18px;background:#fff5de}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{text-align:left;border-bottom:1px solid #dce3de;padding:10px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf2ef;padding:20px}}summary{{cursor:pointer}}a{{color:#106955}}</style>
    <p>RISKREPLAY / LOCAL EVIDENCE REPORT</p><h1>Every decision has a history.</h1><p>Run <strong>{report["run_id"]}</strong> · {report["mode"]}</p>
    <p class="note">{html.escape(report["information_regime"])}<br><strong>Declined outcomes under approval remain unknown. No recovered revenue or counterfactual fraud-loss claim is supported.</strong></p>
    <h2>Reconstruction</h2><p>{summary["matched"]} matched · {summary["mismatched"]} mismatched · {summary["incomplete"]} incomplete / {summary["total"]} decisions. {summary["changed"]} candidate action changes.</p>
    <h2>Label evidence</h2><pre>{html.escape(json.dumps({k: v for k, v in summary.items() if k in ["mature", "immature", "declined_unobserved", "unobserved", "missing_state"]}, indent=2))}</pre>
    <h2>Held-out model evaluation</h2>{metrics}
    <h2>Temporal integrity</h2><pre>{html.escape(json.dumps(report["integrity"]["checks"], indent=2))}</pre>
    <h2>Configuration and identity</h2><pre>{html.escape(json.dumps({"dataset_hash": report["dataset_hash"], "semantic_hash": semantic_hash, "config": report["config"], "performance": report["performance"]}, indent=2))}</pre>
    <h2>Decision ledger</h2><table><thead><tr><th>Transaction</th><th>Replay</th><th>Recorded</th><th>Candidate</th><th>Evidence</th></tr></thead><tbody>{rows}</tbody></table><p>Full event timelines, artifact hashes, feature provenance and raw metrics are in the adjacent report.json and local inspector.</p></html>"""
    (folder / "report.html").write_text(body)
    static = Path(__file__).with_name("static")
    template = (static / "index.html").read_text()
    template = template.replace(
        '<link rel="stylesheet" href="/static/styles.css">',
        "<style>" + (static / "styles.css").read_text() + "</style>",
    ).replace('<script src="/static/app.js" defer></script>', "")
    # Escape the HTML parser's script terminator even in inert application/json.
    data = json.dumps(report, allow_nan=False).replace("<", "\\u003c")
    bundle = '<script type="application/json" id="riskreplay-bundle">' + data + "</script>"
    bundle += "<script>" + (static / "app.js").read_text() + "</script>"
    (folder / "inspector.html").write_text(template.replace("</body>", bundle + "</body>"))
    write_json(
        folder / "manifest.json",
        {
            "schema_version": 1,
            "run_id": report["run_id"],
            "files": {
                name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in RUN_FILES
            },
        },
    )
