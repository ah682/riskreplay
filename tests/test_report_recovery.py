"""Report publication failures must not expose or strand partial runs."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from riskreplay.reporting import save_report, validate_run_files
from riskreplay.web import create_app


def report_fixture(run_id="owned-recovery-run"):
    return {
        "run_id": run_id,
        "mode": "owned_synthetic",
        "information_regime": "Owned synthetic recovery fixture",
        "summary": {"matched": 1, "mismatched": 0, "incomplete": 0, "total": 1, "changed": 0},
        "decisions": [
            {
                "transaction_id": "owned-transaction",
                "status": "matched",
                "recorded_action": "approve",
                "candidate_action": "approve",
                "label_status": "unobserved",
            }
        ],
        "evaluation": {"models": {}},
        "integrity": {"checks": []},
        "dataset_hash": "a" * 64,
        "config": {},
        "performance": {},
    }


def get(app, path):
    async def invoke():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            return await client.get(path)

    return asyncio.run(invoke())


@pytest.mark.parametrize("failed_file", ["report.html", "manifest.json"])
def test_interrupted_report_is_hidden_cleaned_and_retryable(tmp_path, monkeypatch, failed_file):
    report = report_fixture()
    app = create_app(tmp_path)
    write_text = Path.write_text
    during_write = []

    def interrupted(path, *args, **kwargs):
        if path.name == failed_file:
            during_write.append(get(app, "/api/runs").json())
            raise OSError("Interrupted report write")
        return write_text(path, *args, **kwargs)

    with monkeypatch.context() as interruption:
        interruption.setattr(Path, "write_text", interrupted)
        with pytest.raises(OSError, match="Interrupted report write"):
            save_report(tmp_path, report)

    assert during_write == [{"runs": [], "unavailable": [], "count": 0}]
    assert list((tmp_path / "runs").iterdir()) == []
    assert get(app, "/api/runs").json() == {"runs": [], "unavailable": [], "count": 0}

    folder = save_report(tmp_path, report)
    validate_run_files(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["run_id"] == "owned-recovery-run"
    assert set(manifest["files"]) == {
        "report.json",
        "integrity.json",
        "evaluation.json",
        "decisions.csv",
        "report.html",
        "inspector.html",
    }
    assert get(app, "/api/runs").json()["count"] == 1
    assert get(app, f"/api/runs/{report['run_id']}/export?format=html").status_code == 200


def test_unreadable_manifest_isolated_from_healthy_runs(tmp_path):
    healthy = save_report(tmp_path, report_fixture("healthy-run"))
    damaged = save_report(tmp_path, report_fixture("damaged-run"))
    (damaged / "manifest.json").unlink()
    (damaged / "manifest.json").mkdir()
    app = create_app(tmp_path)

    response = get(app, "/api/runs/damaged-run")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_report"
    listing = get(app, "/api/runs")
    assert listing.status_code == 200
    assert [run["run_id"] for run in listing.json()["runs"]] == ["healthy-run"]
    assert listing.json()["count"] == 1
    assert [run["run_id"] for run in listing.json()["unavailable"]] == ["damaged-run"]
    assert (
        get(app, "/api/runs/healthy-run/export?format=json").content
        == (healthy / "report.json").read_bytes()
    )
