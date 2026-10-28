"""Offline environment repair must not write through shared package-cache inodes."""

import hashlib
import importlib.metadata as metadata
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from scripts import setup


@pytest.fixture
def offline_setup(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "requirements.lock").write_text("ruff==1.0\n")
    env = root / ".venv"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(env)
    site = (
        env / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    )
    source = tmp_path / "source"
    files = {
        "fixture_package/__init__.py": "VALUE = 'new package'\n",
        "fixture_module.py": "VALUE = 'new module'\n",
        "ruff-1.0.data/scripts/ruff": "#!/bin/sh\nexit 0\n",
        "ruff-1.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: ruff\nVersion: 1.0\n",
    }
    for relative, content in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (source / "ruff-1.0.data/scripts/ruff").chmod(0o755)
    (source / "ruff-1.0.dist-info/RECORD").write_text(
        "".join(f"{name},,\n" for name in files) + "ruff-1.0.dist-info/RECORD,,\n"
    )
    monkeypatch.setattr(setup, "ROOT", root)
    monkeypatch.setattr(setup, "ENV", env)
    monkeypatch.setattr(setup, "PINS", [["ruff", "1.0"]])
    monkeypatch.setenv("RISKREPLAY_PACKAGE_SOURCE", str(source))

    # The fixture has real wheel metadata and uses the real venv interpreter for
    # version checks. Only the unrelated scientific-runtime smoke test is skipped.
    run = subprocess.run

    def fixture_runtime(command, *args, **kwargs):
        if command[:2] == [str(env / "bin/python"), "-c"] and command[2].startswith(
            "import numpy, scipy, sklearn"
        ):
            return subprocess.CompletedProcess(command, 0)
        return run(command, *args, **kwargs)

    monkeypatch.setattr(setup.subprocess, "run", fixture_runtime)
    return root, env, site, source


@pytest.mark.parametrize("member", ["fixture_package/__init__.py", "fixture_module.py", "launcher"])
@pytest.mark.parametrize("same_source", [True, False], ids=["same-inode", "different-version"])
def test_offline_copy_preserves_shared_cache_files(offline_setup, member, same_source):
    root, env, site, source = offline_setup
    if member == "launcher":
        src = source / "ruff-1.0.data/scripts/ruff"
        destination = env / "bin/ruff"
    else:
        src = source / member
        destination = site / member
    destination.parent.mkdir(parents=True, exist_ok=True)
    if same_source:
        shared = src
    else:
        shared = root / "other-environment-file"
        shared.write_text("keep this other environment's version\n")
    expected_source = src.read_bytes()
    expected_shared = shared.read_bytes()
    os.link(shared, destination)

    setup.main()

    assert destination.read_bytes() == expected_source
    assert src.read_bytes() == expected_source
    assert shared.read_bytes() == expected_shared
    assert not destination.samefile(shared)
    if member == "launcher":
        assert destination.stat().st_mode & 0o111
    marker = json.loads((env / "riskreplay-environment.json").read_text())
    assert marker["offline_reuse"] is True
    assert marker["versions"] == {"ruff": "1.0"}


@pytest.mark.parametrize("previous_marker", [False, True], ids=["no-marker", "stale-marker"])
def test_failed_offline_copy_preserves_previous_file(offline_setup, monkeypatch, previous_marker):
    root, env, site, _ = offline_setup
    destination = site / "fixture_module.py"
    destination.write_text("previous complete module\n")
    if previous_marker:
        (env / "riskreplay-environment.json").write_text(
            json.dumps(
                {
                    "lock_hash": hashlib.sha256(
                        (root / "requirements.lock").read_bytes()
                    ).hexdigest(),
                    "versions": {"ruff": "1.0"},
                }
            )
        )
    copy = setup.shutil.copy2

    def interrupted_copy(src, dst, *args, **kwargs):
        if Path(src).name == "fixture_module.py":
            Path(dst).write_text("partial")
            raise OSError("interrupted fixture copy")
        return copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(setup.shutil, "copy2", interrupted_copy)
    with pytest.raises(OSError, match="interrupted fixture copy"):
        setup.main()

    assert destination.read_text() == "previous complete module\n"
    assert not (env / "riskreplay-environment.json").exists()
    assert not list(site.rglob(".copying-*"))


def install_obsolete_distribution(root, site):
    dist_info = site / "ruff-0.9.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text("Metadata-Version: 2.1\nName: ruff\nVersion: 0.9\n")
    shared = root / "other-environment-old-module.py"
    shared.write_text("obsolete API kept in the old cache\n")
    os.link(shared, site / "obsolete_fixture_module.py")
    (dist_info / "RECORD").write_text(
        "ruff-0.9.dist-info/METADATA,,\nruff-0.9.dist-info/RECORD,,\nobsolete_fixture_module.py,,\n"
    )
    return shared


@pytest.mark.parametrize(
    ("installed_version", "force_pip"),
    [(None, False), ("0.9", False), ("0.9", True)],
    ids=["missing", "wrong-version", "wrong-version-pip"],
)
def test_matching_marker_does_not_hide_incorrect_installed_versions(
    offline_setup, monkeypatch, installed_version, force_pip
):
    root, env, site, _ = offline_setup
    marker = env / "riskreplay-environment.json"
    marker.write_text(
        json.dumps(
            {
                "lock_hash": hashlib.sha256((root / "requirements.lock").read_bytes()).hexdigest(),
                "versions": {"ruff": "1.0"},
                "offline_reuse": True,
            }
        )
    )
    if force_pip:
        which = shutil.which
        monkeypatch.setattr(
            setup.shutil, "which", lambda name: None if name == "uv" else which(name)
        )
    if installed_version is not None:
        shared = install_obsolete_distribution(root, site)

    setup.main()

    installed = {
        dist.metadata["Name"]: dist.version
        for dist in metadata.distributions(path=[site])
        if dist.metadata["Name"] == "ruff"
    }
    assert installed == {"ruff": "1.0"}
    assert (site / "fixture_module.py").read_text() == "VALUE = 'new module'\n"
    assert json.loads(marker.read_text())["versions"] == {"ruff": "1.0"}
    if installed_version is not None:
        assert not (site / "ruff-0.9.dist-info").exists()
        assert not (site / "obsolete_fixture_module.py").exists()
        assert shared.read_text() == "obsolete API kept in the old cache\n"


@pytest.mark.parametrize("force_pip", [False, True], ids=["default-manager", "pip"])
def test_matching_marker_does_not_accept_duplicate_installed_versions(
    offline_setup, monkeypatch, force_pip
):
    root, _, site, _ = offline_setup
    setup.main()
    shared = install_obsolete_distribution(root, site)
    if force_pip:
        which = shutil.which
        monkeypatch.setattr(
            setup.shutil, "which", lambda name: None if name == "uv" else which(name)
        )

    setup.main()

    installed = [
        (dist.metadata["Name"], dist.version)
        for dist in metadata.distributions(path=[site])
        if dist.metadata["Name"] == "ruff"
    ]
    assert installed == [("ruff", "1.0")]
    assert not (site / "obsolete_fixture_module.py").exists()
    assert shared.read_text() == "obsolete API kept in the old cache\n"


@pytest.mark.parametrize("marker_contents", ['{"lock_hash":', "[]", "null", '"invalid marker"'])
def test_damaged_setup_marker_is_rebuilt(offline_setup, marker_contents):
    root, env, site, _ = offline_setup
    marker = env / "riskreplay-environment.json"
    marker.write_text(marker_contents)

    setup.main()

    repaired = json.loads(marker.read_text())
    assert (
        repaired["lock_hash"]
        == hashlib.sha256((root / "requirements.lock").read_bytes()).hexdigest()
    )
    assert repaired["versions"] == {"ruff": "1.0"}
    assert (site / "fixture_module.py").read_text() == "VALUE = 'new module'\n"
