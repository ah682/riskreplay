#!/usr/bin/env python3
"""Export a verified synthetic run as a self-contained GitHub Pages site."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from riskreplay.reporting import validate_report, validate_run_files  # noqa: E402

EXPORTS = {
    "index.html": "inspector.html",
    "inspector.html": "inspector.html",
    "report.json": "report.json",
    "decisions.csv": "decisions.csv",
    "report.html": "report.html",
    "evaluation.json": "evaluation.json",
    "integrity.json": "integrity.json",
}
MARKER = ".riskreplay-static"
MARKER_CONTENT = "riskreplay-static-v1\n"


def export_site(data_dir: Path, output_dir: Path) -> dict:
    """Publish only the report allowlist, excluding archives and the simulation oracle."""
    data_dir, output_dir = Path(data_dir), Path(output_dir)
    latest = json.loads((data_dir / "latest.json").read_text())
    run_id = latest.get("run_id")
    if (
        not isinstance(run_id, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id) is None
    ):
        raise ValueError("latest.json must contain a safe run_id")
    folder = data_dir / "runs" / run_id
    if folder.is_symlink() or folder.parent.is_symlink():
        raise ValueError("The source run must not be a symlink")
    manifest_path = folder / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Static export requires a verified run manifest")
    validate_run_files(folder)
    report = json.loads((folder / "report.json").read_text())
    validate_report(report)
    if report.get("mode") != "owned_synthetic":
        raise ValueError("Public static export accepts owned synthetic demo runs only")
    if report.get("run_id") != run_id:
        raise ValueError("The report identity does not match latest.json")
    if output_dir.is_symlink():
        raise ValueError("Static output must not be a symlink")
    source, destination = data_dir.resolve(), output_dir.resolve()
    if source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError("Static output must not overlap the source data directory")
    marker = output_dir / MARKER
    owned = marker.is_file() and not marker.is_symlink() and marker.read_text() == MARKER_CONTENT
    if output_dir.exists() and (
        not output_dir.is_dir() or (any(output_dir.iterdir()) and not owned)
    ):
        raise ValueError("Refusing to overwrite a nonempty unowned static output directory")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".riskreplay-pages-", dir=output_dir.parent))
    try:
        for target, original in EXPORTS.items():
            shutil.copyfile(folder / original, temporary / target)
        (temporary / ".nojekyll").write_text("")
        manifest = {
            "mode": "owned_synthetic_static_demo",
            "run_id": run_id,
            "dataset_hash": report["dataset_hash"],
            "semantic_hash": report["semantic_hash"],
            "files": {
                target: hashlib.sha256((temporary / target).read_bytes()).hexdigest()
                for target in EXPORTS
            },
        }
        (temporary / "site-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (temporary / MARKER).write_text(MARKER_CONTENT)
        # Build completely before replacing the previous generated directory.
        # A deployment uploads this directory only after this command succeeds.
        if output_dir.exists():
            shutil.rmtree(output_dir)
        temporary.rename(output_dir)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "var/demo")
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    args = parser.parse_args()
    try:
        manifest = export_site(args.data_dir, args.output)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Static build failed: {error}\n")
    print(json.dumps({"output": str(args.output), **manifest}, indent=2))


if __name__ == "__main__":
    main()
