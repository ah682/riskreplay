#!/usr/bin/env python3
"""Install exact pins, reusing already installed distributions for offline hosts.

Copies only public Python distributions, never environment/config/credential files.
Normal clean hosts use uv/pip with requirements.lock. Local reuse is optional and
validated against exact versions; the resulting environment is self-contained.
"""

from __future__ import annotations

import importlib.metadata as metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".venv"
PINS = [
    line.strip().split("==")
    for line in (ROOT / "requirements.lock").read_text().splitlines()
    if line and not line.startswith("#")
]


def normalized(name):
    return name.lower().replace("_", "-").replace(".", "-")


def installed_versions(python):
    check = (
        "import importlib.metadata as m, json\nversions = {}\nfor name in "
        + repr([name for name, _ in PINS])
        + ":\n    try:\n        versions[name] = m.version(name)\n"
        "    except m.PackageNotFoundError:\n        versions[name] = None\n"
        "print(json.dumps(versions))\n"
    )
    return json.loads(subprocess.check_output([str(python), "-c", check], text=True))


def copy_package_file(source, destination):
    """Replace the directory entry without writing through an existing cache link."""
    destination = Path(destination)
    with tempfile.TemporaryDirectory(prefix=".copying-", dir=destination.parent) as temporary:
        staged = Path(temporary) / destination.name
        shutil.copy2(source, staged)
        staged.replace(destination)
    return str(destination)


def main():
    if sys.version_info[:2] != (3, 12):
        print("RiskReplay's lock is verified on Python 3.12; use Python 3.12 for reproducibility.")
    python = ENV / "bin" / "python"
    lock_hash = __import__("hashlib").sha256((ROOT / "requirements.lock").read_bytes()).hexdigest()
    marker = ENV / "riskreplay-environment.json"
    if (
        python.exists()
        and marker.exists()
        and json.loads(marker.read_text()).get("lock_hash") == lock_hash
        and installed_versions(python) == dict(PINS)
    ):
        print("Pinned RiskReplay environment ready.")
        return
    venv.EnvBuilder(with_pip=False, symlinks=True).create(ENV)
    site = (
        ENV / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    )
    roots = [Path(p) for p in sys.path if p and ("site-packages" in p or "dist-packages" in p)]
    roots += list((Path.home() / ".local/share/pipx/venvs").glob("*/lib/python3.12/site-packages"))
    roots += list((Path.home() / ".cache/uv/archive-v0").glob("*"))
    if os.environ.get("RISKREPLAY_PACKAGE_SOURCE"):
        roots.insert(0, Path(os.environ["RISKREPLAY_PACKAGE_SOURCE"]))
    wanted = {normalized(name): version for name, version in PINS}
    found = {}
    for root in roots:
        if root.resolve() == site.resolve():
            continue
        for dist in metadata.distributions(path=[str(root)]):
            name = normalized(dist.metadata.get("Name", ""))
            if wanted.get(name) == dist.version and name not in found:
                found[name] = dist
    if len(found) == len(wanted):
        print(f"Offline setup: copying {len(found)} exact-version installed distributions.")
        for name, dist in found.items():
            source = Path(dist.locate_file(""))
            # Copy top-level wheel contents to include native-library companion directories.
            members = {
                Path(str(f)).parts[0]
                for f in (dist.files or [])
                if Path(str(f)).parts and Path(str(f)).parts[0] != ".."
            }
            if not members:
                top = dist.read_text("top_level.txt") or name.replace("-", "_")
                members = {line for line in top.splitlines() if line} | {Path(dist._path).name}
            for member in members:
                src = source / member
                dst = site / member
                if src.is_dir():
                    shutil.copytree(
                        src,
                        dst,
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"),
                        copy_function=copy_package_file,
                    )
                elif src.is_file():
                    copy_package_file(src, dst)
            if name == "ruff":
                candidates = list(source.glob("ruff-*.data/scripts/ruff")) + [
                    source.parent.parent.parent / "bin/ruff"
                ]
                for candidate in candidates:
                    if candidate.is_file():
                        copy_package_file(candidate, ENV / "bin/ruff")
                        break
    elif shutil.which("uv"):
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--cache-dir",
                str(ROOT / ".package-cache"),
                "-r",
                str(ROOT / "requirements.lock"),
            ],
            check=True,
        )
    else:
        subprocess.run([str(python), "-m", "ensurepip"], check=True)
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.lock")], check=True
        )
    versions = installed_versions(python)
    for name, version in PINS:
        if versions[name] != version:
            raise RuntimeError(f"Version mismatch for {name}")
    subprocess.run(
        [
            str(python),
            "-c",
            "import numpy, scipy, sklearn, pyarrow, fastapi, uvicorn, pytest; from sklearn.ensemble import HistGradientBoostingClassifier; print('Runtime imports verified.')",
        ],
        check=True,
    )
    (site / "riskreplay-local.pth").write_text(str(ROOT) + "\n")
    launcher = ENV / "bin/riskreplay"
    launcher.write_text(f"#!{python}\nfrom riskreplay.cli import main\nmain()\n")
    launcher.chmod(0o755)
    marker.write_text(
        json.dumps(
            {
                "lock_hash": lock_hash,
                "versions": versions,
                "offline_reuse": len(found) == len(wanted),
            },
            indent=2,
        )
    )
    print("Pinned RiskReplay environment ready.")


if __name__ == "__main__":
    main()
