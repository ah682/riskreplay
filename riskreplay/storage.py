"""Immutable Parquet bundles with checksums and a disposable local SQL index."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .schema import (
    ContractError,
    Decision,
    Event,
    canonical,
    digest,
    validate_decisions,
    validate_events,
)


def write_json(path: Path, value: dict | list):
    data = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".writing-", dir=path.parent) as temporary:
        staged = Path(temporary) / path.name
        staged.write_text(data)
        staged.replace(path)


def _parquet(path: Path, rows: list[dict], json_fields: tuple[str, ...]):
    serialized = [
        {k: canonical(v).decode() if k in json_fields else v for k, v in row.items()}
        for row in rows
    ]
    table = pa.Table.from_pylist(serialized)
    pq.write_table(table, path, compression="zstd", version="2.6")


def save_dataset(
    root: Path, events: list[Event], decisions: list[Decision], provenance: dict
) -> Path:
    if not isinstance(provenance, dict):
        raise ContractError("Dataset provenance must be an object")
    if "config" in provenance and not isinstance(provenance["config"], dict):
        raise ContractError("Provenance config must be an object when supplied")
    events = validate_events(events)
    decisions = validate_decisions(decisions, events)
    normalized = {
        "events": [e.to_dict() for e in events],
        "decisions": [d.to_dict() for d in decisions],
        "provenance": provenance,
    }
    key = digest(normalized)
    target = Path(root) / "datasets" / key
    if target.exists():
        _, _, existing = load_dataset(target)
        if existing["dataset_hash"] != key:
            raise ContractError("Dataset directory identity does not match requested content hash")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".writing-", dir=target.parent))
    try:
        _parquet(temporary / "events.parquet", normalized["events"], ("payload",))
        _parquet(temporary / "decisions.parquet", normalized["decisions"], ("feature_values",))
        manifest = {
            "schema_version": 1,
            "dataset_hash": key,
            "event_deliveries": len(events),
            "event_identities": len({e.event_id for e in events}),
            "decision_count": len(decisions),
            "provenance": provenance,
            "files": {
                name: hashlib.sha256((temporary / name).read_bytes()).hexdigest()
                for name in ("events.parquet", "decisions.parquet")
            },
        }
        write_json(temporary / "manifest.json", manifest)
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return target


def load_dataset(path: Path) -> tuple[list[Event], list[Decision], dict]:
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text())
    if not isinstance(manifest, dict):
        raise ContractError("Dataset manifest must be an object")
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ContractError("Unsupported dataset schema; expected version 1")
    if not isinstance(manifest.get("files"), dict):
        raise ContractError("Dataset manifest requires file checksums")
    if not isinstance(manifest.get("provenance"), dict):
        raise ContractError("Dataset manifest provenance must be an object")
    if "config" in manifest["provenance"] and not isinstance(
        manifest["provenance"]["config"], dict
    ):
        raise ContractError("Dataset manifest provenance config must be an object")
    for name in ("events.parquet", "decisions.parquet"):
        if hashlib.sha256((path / name).read_bytes()).hexdigest() != manifest["files"].get(name):
            raise ContractError(f"Dataset integrity failure: {name} checksum changed")
    events = [
        Event(**{**r, "payload": json.loads(r["payload"])})
        for r in pq.read_table(path / "events.parquet").to_pylist()
    ]
    decisions = [
        Decision(**{**r, "feature_values": json.loads(r["feature_values"])})
        for r in pq.read_table(path / "decisions.parquet").to_pylist()
    ]
    events = validate_events(events)
    decisions = validate_decisions(decisions, events)
    expected_counts = {
        "event_deliveries": len(events),
        "event_identities": len({event.event_id for event in events}),
        "decision_count": len(decisions),
    }
    for name, value in expected_counts.items():
        if type(manifest.get(name)) is not int or manifest[name] != value:
            raise ContractError(f"Dataset manifest {name} does not match validated records")
    key = digest(
        {
            "events": [e.to_dict() for e in events],
            "decisions": [d.to_dict() for d in decisions],
            "provenance": manifest["provenance"],
        }
    )
    if key != manifest["dataset_hash"]:
        raise ContractError("Dataset normalized content hash does not match manifest")
    return events, decisions, manifest


def build_index(path: Path, events: list[Event], decisions: list[Decision]):
    """SQLite is a rebuildable query index, never the authoritative history."""
    with sqlite3.connect(path) as connection:
        connection.executescript("""
        PRAGMA user_version=1;
        DROP TABLE IF EXISTS deliveries;
        DROP TABLE IF EXISTS decisions;
        CREATE TABLE deliveries (delivery_seq INTEGER PRIMARY KEY, event_id TEXT NOT NULL,
          transaction_id TEXT, event_type TEXT NOT NULL, event_time TEXT NOT NULL,
          available_at TEXT NOT NULL, payload_hash TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE INDEX deliveries_knowledge ON deliveries(available_at, delivery_seq);
        CREATE INDEX deliveries_tx ON deliveries(transaction_id);
        CREATE TABLE decisions (transaction_id TEXT PRIMARY KEY, decision_time TEXT NOT NULL,
          cutoff_seq INTEGER NOT NULL, policy_hash TEXT NOT NULL, original_action TEXT NOT NULL);
        """)
        connection.executemany(
            "INSERT INTO deliveries VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    e.delivery_seq,
                    e.event_id,
                    e.transaction_id,
                    e.event_type,
                    e.event_time,
                    e.available_at,
                    e.payload_hash,
                    canonical(e.payload).decode(),
                )
                for e in events
            ],
        )
        connection.executemany(
            "INSERT INTO decisions VALUES (?,?,?,?,?)",
            [
                (d.transaction_id, d.decision_time, d.cutoff_seq, d.policy_hash, d.original_action)
                for d in decisions
            ],
        )


def import_jsonl(events_path: Path, decisions_path: Path, root: Path, provenance: dict) -> Path:
    if not isinstance(provenance, dict):
        raise ContractError("Import provenance must be an object")

    def read(path, cls):
        rows = []
        for number, line in enumerate(Path(path).read_text().splitlines(), 1):
            if line.strip():
                try:
                    rows.append(cls(**json.loads(line)))
                except (ValueError, TypeError) as exc:
                    raise ContractError(f"{Path(path).name}:line {number}: {exc}") from exc
        return rows

    events = read(events_path, Event)
    decisions = read(decisions_path, Decision)
    if not events or not decisions:
        raise ContractError("Import requires at least one event and one recorded decision")
    if provenance.get("kind") not in {"owned_synthetic", "partner_records"}:
        raise ContractError("Provenance kind must be owned_synthetic or partner_records")
    if any(
        not isinstance(provenance.get(name), str) or not provenance[name].strip()
        for name in ("source", "permission")
    ):
        raise ContractError("Provenance must document source and permission to use the data")
    return save_dataset(root, events, decisions, provenance)
