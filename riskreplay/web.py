"""Read-only local inspection of persisted replay runs.

This API never generates decisions, trains models, or reveals generator oracle data.
Only artifacts below ``data_dir/runs/<safe-run-id>`` can be served.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .reporting import validate_report, validate_run_files

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_EXPORTS = {
    "json": ("report.json", "application/json"),
    "csv": ("decisions.csv", "text/csv"),
    "html": ("report.html", "text/html"),
}


def create_app(data_dir: Path) -> FastAPI:
    """Create a read-only report app; the CLI binds it to the loopback interface."""
    runs_dir = Path(data_dir).resolve() / "runs"
    static_dir = Path(__file__).with_name("static")
    app = FastAPI(
        title="RiskReplay local report API", version="0.1.1", docs_url=None, redoc_url=None
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if not isinstance(detail, dict):
            detail = {
                "code": "not_found" if exc.status_code == 404 else "request_failed",
                "message": str(detail),
            }
        return JSONResponse({"error": detail}, status_code=exc.status_code)

    @app.middleware("http")
    async def local_response_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    def fail(status: int, code: str, message: str) -> None:
        raise HTTPException(status_code=status, detail={"code": code, "message": message})

    def validate_id(value: str, kind: str) -> None:
        if not _SAFE_ID.fullmatch(value):
            fail(400, "invalid_id", f"Invalid {kind}: use letters, numbers, '.', '_' or '-'.")

    def artifact_path(run_id: str, filename: str) -> Path:
        validate_id(run_id, "run ID")
        run_path = runs_dir / run_id
        artifact = run_path / filename
        # Reject symlinked directories and artifacts, including links into another run.
        if runs_dir.is_symlink() or run_path.is_symlink() or artifact.is_symlink():
            fail(404, "artifact_not_found", "The requested run artifact is unavailable.")
        if artifact.resolve().parent != run_path.resolve() or run_path.resolve().parent != runs_dir:
            fail(404, "artifact_not_found", "The requested run artifact is unavailable.")
        if not artifact.is_file():
            fail(404, "artifact_not_found", f"{filename} is not available for run {run_id}.")
        return artifact

    def read_report(run_id: str) -> dict[str, Any]:
        report_path = artifact_path(run_id, "report.json")
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            fail(422, "invalid_report", f"The persisted report for {run_id} cannot be read.")
        if not isinstance(report, dict):
            fail(422, "invalid_report", f"The persisted report for {run_id} is not an object.")
        if report.get("run_id", run_id) != run_id:
            fail(422, "invalid_report", "The report identity does not match its run directory.")
        try:
            validate_report(report)
            validate_run_files(report_path.parent, "report.json")
        except (OSError, ValueError):
            fail(422, "invalid_report", "The persisted report failed its semantic integrity check.")
        return report

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": "local_read_only"}

    @app.get("/api/runs")
    async def list_runs() -> dict[str, Any]:
        runs: list[dict[str, Any]] = []
        unavailable: list[dict[str, str]] = []
        if runs_dir.is_dir() and not runs_dir.is_symlink():
            for run_path in sorted(runs_dir.iterdir()):
                if not run_path.is_dir() or not _SAFE_ID.fullmatch(run_path.name):
                    continue
                try:
                    report = read_report(run_path.name)
                except HTTPException as exc:
                    unavailable.append({"run_id": run_path.name, "reason": exc.detail["message"]})
                    continue
                runs.append(
                    {
                        "run_id": run_path.name,
                        "created_at": report.get("created_at"),
                        "mode": report.get("mode", "unavailable"),
                        "information_regime": report.get("information_regime"),
                        "dataset_hash": report.get("dataset_hash"),
                        "summary": report.get("summary", {}),
                    }
                )
        runs.sort(
            key=lambda item: (str(item.get("created_at") or ""), item["run_id"]), reverse=True
        )
        return {"runs": runs, "unavailable": unavailable, "count": len(runs)}

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        return read_report(run_id)

    @app.get("/api/runs/{run_id}/transactions/{transaction_id:path}")
    async def get_transaction(run_id: str, transaction_id: str) -> dict[str, Any]:
        # Transaction IDs are data, never filesystem paths. Preserve the normalized
        # import contract, including provider IDs containing colons, spaces or slashes.
        if not transaction_id:
            fail(400, "invalid_id", "Transaction ID must not be empty.")
        report = read_report(run_id)
        decisions = report.get("decisions", [])
        if not isinstance(decisions, list):
            fail(422, "invalid_report", "The persisted report does not contain a decision list.")
        for decision in decisions:
            if isinstance(decision, dict) and decision.get("transaction_id") == transaction_id:
                return decision
        fail(404, "transaction_not_found", f"Transaction {transaction_id} is not in run {run_id}.")

    @app.get("/api/runs/{run_id}/export")
    async def export_run(run_id: str, format: str = "json") -> Response:
        if format not in _EXPORTS:
            fail(400, "invalid_format", "Export format must be json, csv, or html.")
        read_report(run_id)
        filename, media_type = _EXPORTS[format]
        artifact = artifact_path(run_id, filename)
        try:
            validate_run_files(artifact.parent, filename)
        except (OSError, ValueError):
            fail(422, "invalid_artifact", "The requested export failed its integrity check.")
        return Response(
            artifact.read_bytes(),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{run_id}-{filename}"'},
        )

    @app.get("/", include_in_schema=False)
    async def index() -> Response:
        return Response((static_dir / "index.html").read_bytes(), media_type="text/html")

    @app.get("/static/{filename}", include_in_schema=False)
    async def static_file(filename: str) -> Response:
        media_types = {"app.js": "text/javascript", "styles.css": "text/css"}
        if filename not in media_types:
            fail(404, "not_found", "The requested viewer asset does not exist.")
        return Response((static_dir / filename).read_bytes(), media_type=media_types[filename])

    return app
