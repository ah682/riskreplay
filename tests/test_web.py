"""The local viewer exposes persisted evidence without mutation or path escape."""

import asyncio
import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI

from riskreplay.reporting import semantic_report
from riskreplay.schema import digest
from riskreplay.web import create_app


class TestClient:
    """Exercise the complete ASGI app on one loop, without a background thread."""

    __test__ = False

    def __init__(self, app: FastAPI):
        self.app = app

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        async def invoke() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(invoke())

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.request("POST", path, **kwargs)


@pytest.fixture
def persisted_run(tmp_path: Path) -> tuple[Path, dict]:
    report = {
        "run_id": "run-fixture-01",
        "created_at": "2025-02-10T12:00:00Z",
        "mode": "owned_synthetic",
        "information_regime": "Availability time at the original decision cutoff.",
        "dataset_hash": "a" * 64,
        "summary": {"total": 1, "matched": 0, "mismatched": 0, "incomplete": 1},
        "decisions": [
            {
                "transaction_id": "tx-sunday-01",
                "status": "incomplete",
                "recorded_action": "decline",
                "replayed_action": None,
                "candidate_action": None,
                "label_status": "declined_unobserved",
                "missing": ["Original model artifact unavailable"],
                "explanation": [{"kind": "evidence", "message": "<script>untrusted</script>"}],
            }
        ],
    }
    report["semantic_hash"] = digest(semantic_report(report))
    directory = tmp_path / "runs" / report["run_id"]
    directory.mkdir(parents=True)
    (directory / "report.json").write_text(json.dumps(report))
    (directory / "decisions.csv").write_text("transaction_id,status\ntx-sunday-01,incomplete\n")
    (directory / "report.html").write_text(
        "<!doctype html><title>Persisted replay evidence</title>"
    )
    return tmp_path, report


def test_run_list_and_incident_preserve_unknowns(persisted_run: tuple[Path, dict]) -> None:
    directory, report = persisted_run
    client = TestClient(create_app(directory))
    listing = client.get("/api/runs")
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    assert listing.json()["runs"][0]["summary"]["incomplete"] == 1
    assert "decisions" not in listing.json()["runs"][0]
    assert client.get(f"/api/runs/{report['run_id']}").json() == report
    incident = client.get(f"/api/runs/{report['run_id']}/transactions/tx-sunday-01").json()
    assert incident["replayed_action"] is None
    assert incident["label_status"] == "declined_unobserved"
    assert incident["missing"] == ["Original model artifact unavailable"]
    assert incident["explanation"][0]["message"] == "<script>untrusted</script>"


@pytest.mark.parametrize(
    "format,filename", [("json", "report.json"), ("csv", "decisions.csv"), ("html", "report.html")]
)
def test_exports_serve_the_actual_persisted_artifact(
    persisted_run: tuple[Path, dict], format: str, filename: str
) -> None:
    directory, report = persisted_run
    client = TestClient(create_app(directory))
    response = client.get(f"/api/runs/{report['run_id']}/export", params={"format": format})
    assert response.status_code == 200
    assert response.content == (directory / "runs" / report["run_id"] / filename).read_bytes()
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_empty_and_partially_corrupt_run_directories(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    assert client.get("/api/runs").json() == {"runs": [], "unavailable": [], "count": 0}
    broken = tmp_path / "runs" / "broken"
    broken.mkdir(parents=True)
    (broken / "report.json").write_text("not valid JSON")
    listing = client.get("/api/runs").json()
    assert listing["count"] == 0
    assert listing["unavailable"][0]["run_id"] == "broken"
    response = client.get("/api/runs/broken")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_report"


@pytest.mark.parametrize(
    "path,status,code",
    [
        ("/api/runs/absent", 404, "artifact_not_found"),
        ("/api/runs/run-fixture-01/transactions/missing", 404, "transaction_not_found"),
        ("/api/runs/run-fixture-01/export?format=exe", 400, "invalid_format"),
        ("/api/runs/%2E%2E", 400, "invalid_id"),
        ("/api/runs/%2Fetc%2Fpasswd", 404, "not_found"),
        ("/api/runs/run-fixture-01/transactions/%2E%2E", 404, "transaction_not_found"),
    ],
)
def test_structured_errors_and_path_validation(
    persisted_run: tuple[Path, dict], path: str, status: int, code: str
) -> None:
    directory, _ = persisted_run
    response = TestClient(create_app(directory)).get(path)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_missing_export_is_not_fabricated(persisted_run: tuple[Path, dict]) -> None:
    directory, report = persisted_run
    (directory / "runs" / report["run_id"] / "decisions.csv").unlink()
    response = TestClient(create_app(directory)).get(
        f"/api/runs/{report['run_id']}/export?format=csv"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "artifact_not_found"


def test_symlinked_artifacts_and_runs_cannot_escape(tmp_path: Path) -> None:
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "report.json").write_text('{"secret":"not report evidence"}')
    run_dir = tmp_path / "data" / "runs" / "safe"
    run_dir.mkdir(parents=True)
    (run_dir / "report.json").symlink_to(outside / "report.json")
    (run_dir.parent / "linked-run").symlink_to(outside, target_is_directory=True)
    client = TestClient(create_app(tmp_path / "data"))
    for run_id in ("safe", "linked-run"):
        response = client.get(f"/api/runs/{run_id}/export?format=json")
        assert response.status_code == 404
        assert "secret" not in response.text
    assert client.get("/api/runs").json()["count"] == 0


def test_symlinked_run_root_is_not_followed(tmp_path: Path) -> None:
    private = tmp_path / "private"
    (private / "run-one").mkdir(parents=True)
    (private / "run-one" / "report.json").write_text('{"run_id":"run-one"}')
    data = tmp_path / "data"
    data.mkdir()
    (data / "runs").symlink_to(private, target_is_directory=True)
    client = TestClient(create_app(data))
    assert client.get("/api/runs").json()["count"] == 0
    assert client.get("/api/runs/run-one").status_code == 404


def test_conflicting_persisted_identity_is_rejected(persisted_run: tuple[Path, dict]) -> None:
    directory, report = persisted_run
    (directory / "runs" / report["run_id"] / "report.json").write_text('{"run_id":"another-run"}')
    response = TestClient(create_app(directory)).get(f"/api/runs/{report['run_id']}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_report"


def test_local_ui_and_read_only_api(persisted_run: tuple[Path, dict]) -> None:
    directory, report = persisted_run
    client = TestClient(create_app(directory))
    response = client.get("/")
    assert response.status_code == 200
    assert "RiskReplay" in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/health").json() == {"status": "ok", "mode": "local_read_only"}
    assert client.post(f"/api/runs/{report['run_id']}", json={"change": True}).status_code == 405
    assert client.get(f"/api/runs/{report['run_id']}").json() == report


@pytest.mark.parametrize(
    "transaction_id", ["txn:123", "tx with spaces", "注文/42", "../../private", "<untrusted>"]
)
def test_normalized_transaction_ids_are_queryable_data(persisted_run, transaction_id):
    directory, report = persisted_run
    report["decisions"][0]["transaction_id"] = transaction_id
    report["semantic_hash"] = digest(semantic_report(report))
    (directory / "runs" / report["run_id"] / "report.json").write_text(json.dumps(report))
    encoded = quote(transaction_id, safe="").replace(".", "%2E")
    response = TestClient(create_app(directory)).get(
        f"/api/runs/{report['run_id']}/transactions/{encoded}"
    )
    assert response.status_code == 200
    assert response.json() == report["decisions"][0]
