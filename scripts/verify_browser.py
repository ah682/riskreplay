#!/usr/bin/env python3
"""Prepare and collect repeatable RiskReplay browser component verification.

The actual UI sources and owned report are mounted in memory through Playwright's
supported ``page.setContent`` API. API-state scenarios use responses captured from
the actual FastAPI ASGI app. They are intentionally NOT live HTTP or file-navigation
tests. This path remains useful when local socket binding or file: navigation is
unavailable. No sandbox-disabling browser flags or alternate network listener is used.

Run ``python scripts/verify_browser.py --prepare`` then execute the generated
controller files through an available Playwright runner. Save each returned JSON
result as the manifest's ``result_path``. ``--collect`` writes ui-audit.json and
fails if any declared case is missing or any assertion failed.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from riskreplay.reporting import semantic_report  # noqa: E402
from riskreplay.schema import digest  # noqa: E402
from riskreplay.web import create_app  # noqa: E402

DEFAULT_OUTPUT = ROOT / "var" / "verification"
SOURCE_DIR = ROOT / "riskreplay" / "static"
DRIVER = ROOT / "scripts" / "browser_audit.js"


def script_json(value: Any) -> str:
    """Prevent an imported value from terminating an inert inline JSON script."""
    return json.dumps(value, allow_nan=False).replace("<", "\\u003c")


def sign_report(report: dict) -> dict:
    result = copy.deepcopy(report)
    result["semantic_hash"] = digest(semantic_report(result))
    return result


def render_component(
    report: dict | None = None, *, responses: dict | None = None, transport: str = "captured"
) -> str:
    """Use unchanged product markup, CSS and JS; only fixture transport is injected."""
    markup = (SOURCE_DIR / "index.html").read_text()
    markup = markup.replace(
        '<link rel="stylesheet" href="/static/styles.css">',
        "<style>" + (SOURCE_DIR / "styles.css").read_text() + "</style>",
    ).replace('<script src="/static/app.js" defer></script>', "")
    fixture = ""
    if report is not None:
        fixture = (
            '<script type="application/json" id="riskreplay-bundle">'
            + script_json(report)
            + "</script>"
        )
    else:
        # about:blank has no routable origin. The address-bar side effect is outside
        # this component test; ordinary DOM state and request paths are exercised.
        fixture = '<script type="application/json" id="qa-response-capture">'
        fixture += script_json({"responses": responses or {}, "transport": transport})
        fixture += (
            "</script><script>"
            + r"""
(() => {
 const fixture=JSON.parse(document.getElementById('qa-response-capture').textContent);
 window.__qaRequests=[]; window.__qaAddressUpdates=[]; let attempts=0;
 window.__qaAbortObserved=false;
 if(fixture.transport==='timeout_once') {
  const nativeSetTimeout=window.setTimeout.bind(window);
  window.setTimeout=(callback,delay,...rest)=>nativeSetTimeout(callback,delay===20000?250:delay,...rest);
 }
 history.replaceState=(_state,_unused,url)=>window.__qaAddressUpdates.push(String(url));
 window.fetch=async(input,options={})=>{
  const path=String(input); window.__qaRequests.push(path); attempts+=1;
  if(fixture.transport==='timeout_once' && attempts===1) return new Promise((resolve,reject)=>{
   options.signal.addEventListener('abort',()=>{window.__qaAbortObserved=true;reject(new DOMException('Aborted','AbortError'));},{once:true});
  });
  await new Promise(resolve=>setTimeout(resolve,70));
  if(fixture.transport==='fail_once' && attempts===1) throw new TypeError('Injected transport outage');
  if(options.signal?.aborted) throw new DOMException('Aborted','AbortError');
  const item=fixture.responses[path];
  if(!item) return new Response(JSON.stringify({error:{code:'unrecorded_fixture_request',message:'No captured response for '+path}}),{status:404,headers:{'content-type':'application/json'}});
  return new Response(JSON.stringify(item.body),{status:item.status,headers:{'content-type':'application/json'}});
 };
})();
"""
            + "</script>"
        )
    fixture += "<script>" + (SOURCE_DIR / "app.js").read_text() + "</script>"
    return markup.replace("</body>", fixture + "</body>")


async def capture_api_states(report: dict, export_dir: Path | None) -> tuple[dict, list[dict]]:
    """Capture actual success, missing-data and corrupted-data responses in isolation."""
    evidence: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="riskreplay-ui-api-") as temp:
        root = Path(temp)
        app = create_app(root)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://asgi.test") as client:

            async def get(path: str) -> dict:
                response = await client.get(path)
                item = {"status": response.status_code, "body": response.json()}
                evidence.append(
                    {
                        "request": path,
                        "status": response.status_code,
                        "response_sha256": hashlib.sha256(response.content).hexdigest(),
                    }
                )
                return item

            empty = {"/api/runs": await get("/api/runs")}
            valid = sign_report(report)
            run_id = valid["run_id"]
            folder = root / "runs" / run_id
            folder.mkdir(parents=True)
            (folder / "report.json").write_text(json.dumps(valid))
            report_response = await get(f"/api/runs/{run_id}")
            full = {"/api/runs": await get("/api/runs"), f"/api/runs/{run_id}": report_response}
            if valid.get("decisions"):
                transaction_id = valid["decisions"][0]["transaction_id"]
                response = await get(f"/api/runs/{run_id}/transactions/{transaction_id}")
                evidence[-1]["passed"] = response["body"] == valid["decisions"][0]

            # Actual export route and bytes are verified separately from browser
            # downloads, which require a routable origin or allowed file navigation.
            for format, filename in (
                ("json", "report.json"),
                ("csv", "decisions.csv"),
                ("html", "report.html"),
            ):
                if format != "json":
                    if export_dir is None or not (export_dir / filename).is_file():
                        continue
                    (folder / filename).write_bytes((export_dir / filename).read_bytes())
                response = await client.get(f"/api/runs/{run_id}/export?format={format}")
                expected = (folder / filename).read_bytes()
                evidence.append(
                    {
                        "request": f"/api/runs/{run_id}/export?format={format}",
                        "status": response.status_code,
                        "bytes": len(response.content),
                        "response_sha256": hashlib.sha256(response.content).hexdigest(),
                        "passed": response.status_code == 200
                        and response.content == expected
                        and "attachment" in response.headers.get("content-disposition", ""),
                        "scope": "Actual ASGI export bytes; browser download not exercised",
                    }
                )

            second = sign_report(
                {**valid, "run_id": "ui-second-saved-run", "created_at": "2000-01-01T00:00:00Z"}
            )
            second_dir = root / "runs" / second["run_id"]
            second_dir.mkdir()
            (second_dir / "report.json").write_text(json.dumps(second))
            broken = root / "runs" / "ui-broken-report"
            broken.mkdir()
            (broken / "report.json").write_text("{invalid report JSON")
            partial = {
                "/api/runs": await get("/api/runs"),
                f"/api/runs/{run_id}": report_response,
                f"/api/runs/{second['run_id']}": await get(f"/api/runs/{second['run_id']}"),
            }
            # Captured list first, then an actual report corruption between requests.
            (folder / "report.json").write_text("{corrupted after listing")
            detail_error = {
                "/api/runs": full["/api/runs"],
                f"/api/runs/{run_id}": await get(f"/api/runs/{run_id}"),
            }
            for path, expected_status in (
                ("/api/runs/not-found", 404),
                (f"/api/runs/{run_id}/export?format=invalid", 400),
                ("/api/runs/%2E%2E", 400),
            ):
                response = await get(path)
                evidence[-1]["passed"] = response["status"] == expected_status and bool(
                    response["body"].get("error", {}).get("message")
                )
            return {
                "empty": empty,
                "full": full,
                "partial": partial,
                "detail_error": detail_error,
            }, evidence


def prepare(data_dir: Path, output_dir: Path) -> dict:
    latest = json.loads((data_dir / "latest.json").read_text())
    export_dir = data_dir / "runs" / latest["run_id"]
    report = json.loads((export_dir / "report.json").read_text())
    cases_dir = output_dir / "ui-cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    responses, api_evidence = asyncio.run(capture_api_states(report, export_dir))
    fixture_report = sign_report(
        {
            **report,
            "run_id": "ui-empty-records-fixture",
            "mode": "test_fixture",
            "decisions": [],
            "summary": {name: 0 for name in report.get("summary", {})},
            "evaluation": {},
            "integrity": {},
        }
    )
    injection_report = copy.deepcopy(report)
    injection_report["run_id"] = "ui-untrusted-text-fixture"
    injection_report["mode"] = "test_fixture"
    selected = next(
        (row for row in injection_report["decisions"] if row["status"] == "incomplete"),
        injection_report["decisions"][0],
    )
    injection_text = (
        '<img src=x onerror="window.__qaInjected=true"><script>window.__qaInjected=true</script>'
    )
    selected.setdefault("explanation", []).append({"kind": "evidence", "message": injection_text})
    injection_report = sign_report(injection_report)
    # Explicit display fixture: label status and missing feature coverage are
    # independent dimensions, including unknown outcomes outside declines.
    evidence_counts = {
        "total": 7,
        "mature_observed": 2,
        "immature": 1,
        "declined_unobserved": 1,
        "unobserved": 3,
        "missing_state": 2,
    }
    evidence_report = sign_report(
        {
            **fixture_report,
            "run_id": "ui-evidence-counts-fixture",
            "summary": {**fixture_report["summary"], **evidence_counts, "mature": 2},
            "evaluation": {
                "splits": {"test": evidence_counts},
                "models": {
                    "gradient_boosted": {
                        "metrics": {"counts": evidence_counts, "metric_n": 1},
                        "cohorts": {"fixture": {"counts": evidence_counts, "metric_n": 1}},
                    }
                },
            },
        }
    )
    html_by_case = {
        "saved": render_component(report),
        "empty_records": render_component(fixture_report),
        "untrusted_text": render_component(injection_report),
        "evidence_counts": render_component(evidence_report),
        "no_runs": render_component(responses=responses["empty"]),
        "partial_runs": render_component(responses=responses["partial"]),
        "report_error": render_component(responses=responses["detail_error"]),
        "transport_retry": render_component(responses=responses["full"], transport="fail_once"),
        "transport_timeout": render_component(
            responses=responses["full"], transport="timeout_once"
        ),
    }
    specifications = [
        ("saved-desktop", "saved", 1440, 1100),
        ("saved-tablet", "saved", 768, 1024),
        ("saved-mobile", "saved", 390, 844),
        ("empty-records", "empty_records", 390, 844),
        ("untrusted-text", "untrusted_text", 1440, 1100),
        ("evidence-counts", "evidence_counts", 390, 844),
        ("no-runs", "no_runs", 390, 844),
        ("partial-runs", "partial_runs", 1440, 1100),
        ("report-error", "report_error", 390, 844),
        ("transport-retry", "transport_retry", 768, 1024),
        ("transport-timeout", "transport_timeout", 390, 844),
    ]
    driver = DRIVER.read_text()
    source_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in SOURCE_DIR.iterdir()
        if path.is_file()
    }
    cases = []
    for name, scenario, width, height in specifications:
        config = {
            "name": name,
            "scenario": scenario,
            "width": width,
            "height": height,
            "canonical_run_id": report["run_id"],
            "report_semantic_hash": report.get("semantic_hash"),
            "source_hashes": source_hashes,
            "html": html_by_case[scenario],
            "expected_report": report if scenario != "empty_records" else fixture_report,
            "injection_transaction": selected["transaction_id"],
            "injection_text": injection_text,
            "screenshot_path": str(cases_dir / f"{name}.png"),
        }
        controller = cases_dir / f"{name}.js"
        controller.write_text(
            driver.replace(
                "const config = null; // __QA_CONFIG__",
                "const config = " + script_json(config) + ";",
            )
        )
        cases.append(
            {
                "name": name,
                "scenario": scenario,
                "viewport": {"width": width, "height": height},
                "controller": str(controller),
                "result_path": str(cases_dir / f"{name}.json"),
                "screenshot_path": config["screenshot_path"],
                "provenance": "Owned report loaded in memory; unmodified UI source"
                if scenario == "saved"
                else "Explicit UI test fixture; captured ASGI responses or modified owned report",
            }
        )
    manifest = {
        "schema_version": 1,
        "prepared_at": datetime.now(UTC).isoformat(),
        "run_id": report["run_id"],
        "report_semantic_hash": report.get("semantic_hash"),
        "source_hashes": source_hashes,
        "protocol": "Real Playwright browser component integration via page.setContent; no file navigation or live HTTP",
        "api_protocol": "Actual FastAPI ASGITransport responses and raw export bytes",
        "api_evidence": api_evidence,
        "cases": cases,
        "limitations": [
            "Local loopback server cannot bind in this sandbox; live HTTP browser integration is not verified.",
            "Playwright MCP file: navigation is blocked; saved-file navigation is not verified in this audit.",
            "Native Chrome probe exited 133 before page load: crashpad setsockopt: Operation not permitted (1).",
            "Browser export download is not verified; actual ASGI export bytes and browser href/menu behavior are checked separately.",
            "API fixture address-bar updates are recorded instead of changing about:blank origin; normal HTTP deep-link behavior is outside component-test scope.",
            "Timeout fixture accelerates only the 20-second request deadline to 250ms; actual AbortController cancellation, message and retry are exercised.",
            "Pointer automation stalled waiting for stable rendering; later checks use programmatic DOM clicks/input with real Playwright keyboard events.",
            "Fresh screenshot attempts timed out after fonts loaded, including after bringToFront; no current screenshot verification is claimed.",
        ],
    }
    (output_dir / "ui-manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def collect(manifest: dict, output_dir: Path) -> dict:
    cases = []
    for specification in manifest["cases"]:
        result_path = Path(specification["result_path"])
        try:
            result = json.loads(result_path.read_text())
            if result.get("case") != specification["name"] or not result.get("checks"):
                raise ValueError("Case identity or assertion list is missing")
            if result.get("viewport") != specification["viewport"]:
                raise ValueError("Actual browser viewport does not match the declared viewport")
            if (
                result.get("run_id") != manifest["run_id"]
                or result.get("report_semantic_hash") != manifest["report_semantic_hash"]
            ):
                raise ValueError("Browser evidence belongs to another report identity")
            if result.get("source_hashes") != manifest["source_hashes"]:
                raise ValueError("Browser evidence was produced from different UI sources")
            result["passed"] = all(check.get("passed") is True for check in result["checks"])
        except (OSError, ValueError, TypeError) as error:
            result = {
                "case": specification["name"],
                "passed": False,
                "status": "not_verified",
                "reason": str(error),
                "checks": [],
            }
        result["provenance"] = specification["provenance"]
        cases.append(result)
    api_passed = all(item.get("passed", True) for item in manifest["api_evidence"])
    passed = all(case["passed"] for case in cases) and api_passed
    report = {
        **{key: value for key, value in manifest.items() if key != "cases"},
        "collected_at": datetime.now(UTC).isoformat(),
        "component_checks_passed": passed,
        "fully_verified": False,
        "fully_verified_reason": "Component and ASGI checks do not remove the recorded file-navigation, live HTTP, or browser-download limitations.",
        "assertions_passed": sum(
            check.get("passed") is True for case in cases for check in case["checks"]
        ),
        "assertions_total": sum(len(case["checks"]) for case in cases),
        "cases": cases,
    }
    (output_dir / "ui-audit.json").write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "var" / "demo")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--collect", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.prepare:
        report = prepare(args.data_dir, args.output_dir)
        print(json.dumps({"run_id": report["run_id"], "cases": report["cases"]}, indent=2))
    else:
        manifest = json.loads((args.output_dir / "ui-manifest.json").read_text())
        report = collect(manifest, args.output_dir)
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "run_id",
                        "component_checks_passed",
                        "fully_verified",
                        "assertions_passed",
                        "assertions_total",
                        "limitations",
                    )
                },
                indent=2,
            )
        )
        if not report["component_checks_passed"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
