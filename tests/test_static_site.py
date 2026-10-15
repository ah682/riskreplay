"""The public demo contains verified synthetic reports, never private inputs."""

import json

import pytest

from riskreplay.pipeline import demo
from riskreplay.reporting import save_report, semantic_report
from riskreplay.schema import digest
from scripts.build_pages import export_site


@pytest.fixture(scope="module")
def saved_demo(tmp_path_factory):
    root = tmp_path_factory.mktemp("static-source")
    report = demo(root, n_transactions=80)
    return root, report


def test_static_demo_preserves_report_and_relative_exports(saved_demo, tmp_path):
    source, report = saved_demo
    output = tmp_path / "project-subpath"
    result = export_site(source, output)
    original = source / "runs" / report["run_id"]
    assert (output / "index.html").read_bytes() == (original / "inspector.html").read_bytes()
    for name in (
        "report.json",
        "decisions.csv",
        "report.html",
        "evaluation.json",
        "integrity.json",
    ):
        assert (output / name).read_bytes() == (original / name).read_bytes()
    assert (output / ".nojekyll").exists()
    assert result["run_id"] == report["run_id"]
    assert result["semantic_hash"] == report["semantic_hash"]
    assert not list(output.rglob("*.joblib"))
    assert not (output / "simulation_oracle").exists()
    assert not (output / "artifacts").exists()
    # Rebuilding a previously generated site remains supported.
    assert export_site(source, output) == result


def test_publisher_rejects_partner_data_even_when_report_is_valid(saved_demo, tmp_path):
    source, report = saved_demo
    partner = {**report, "mode": "partner_records", "run_id": "private-incident"}
    partner["semantic_hash"] = digest(semantic_report(partner))
    save_report(tmp_path, partner)
    (tmp_path / "latest.json").write_text(json.dumps({"run_id": partner["run_id"]}))
    with pytest.raises(ValueError, match="synthetic"):
        export_site(tmp_path, tmp_path / "public")
    assert not (tmp_path / "public").exists()


def test_tampered_source_is_not_exported(saved_demo, tmp_path):
    import shutil

    source, report = saved_demo
    copied = tmp_path / "source"
    shutil.copytree(source, copied)
    (copied / "runs" / report["run_id"] / "decisions.csv").write_text("altered")
    with pytest.raises(ValueError, match="checksum"):
        export_site(copied, tmp_path / "public")
    assert not (tmp_path / "public").exists()


def test_unverified_legacy_exports_are_not_published(saved_demo, tmp_path):
    import shutil

    source, report = saved_demo
    copied = tmp_path / "source"
    shutil.copytree(source, copied)
    run = copied / "runs" / report["run_id"]
    (run / "manifest.json").unlink()
    (run / "inspector.html").write_text("unverified content")
    with pytest.raises(ValueError, match="manifest"):
        export_site(copied, tmp_path / "public")
    assert not (tmp_path / "public").exists()


def test_nonempty_unowned_output_is_preserved(saved_demo, tmp_path):
    source, _ = saved_demo
    note = tmp_path / "unrelated.txt"
    note.write_text("keep this")
    with pytest.raises(ValueError, match="unowned"):
        export_site(source, tmp_path)
    assert list(tmp_path.iterdir()) == [note]


def test_source_overlap_or_symlink_output_cannot_destroy_report(saved_demo, tmp_path):
    source, report = saved_demo
    with pytest.raises(ValueError, match="overlap"):
        export_site(source, source)
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        export_site(source, link)
    assert not list(target.iterdir())
    assert (source / "runs" / report["run_id"] / "report.json").exists()
