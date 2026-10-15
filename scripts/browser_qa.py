#!/usr/bin/env python3
"""Exercise the real saved inspector in installed headless Chrome, with no sockets.

No mock API, extra packages, remote browser, personal profile or downloaded browser.
HTML copies instrument only local DOM interactions; canonical reports are untouched.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "var/verification"
QA = r"""
<script>
window.addEventListener('load', () => setTimeout(() => {
 const results=[]; const q=s=>document.querySelector(s);
 const assert=(name,value)=>{results.push({name,passed:!!value});};
 try {
  assert('saved report loaded', !q('#report-content').hidden);
  assert('owned synthetic mode',q('#dataset-kind').textContent.includes('SYNTHETIC'));
  q('[data-filter="incomplete"]').click();
  assert('incomplete filter',q('#decision-rows').children.length===1 && q('#decision-rows').textContent.includes('t-after-outage'));
  assert('missing model reason visible',q('#incident-trace').textContent.includes('Missing historical models'));
  q('[data-filter="mismatched"]').click();
  assert('mismatched filter',q('#decision-rows').children.length===1 && q('#decision-rows').textContent.includes('t-monday'));
  q('[data-filter="all"]').click();
  q('#transaction-search').value='t-sunday';
  q('#transaction-search').dispatchEvent(new Event('input',{bubbles:true}));
  q('#decision-rows tr').click();
  assert('search and select Sunday',q('#incident-id').textContent==='t-sunday');
  q('[data-detail="features"]').click();
  assert('feature provenance',!q('#incident-features').hidden && q('#incident-features').textContent.includes('checkpoint-blocklist-start'));
  q('[data-detail="timeline"]').click();
  assert('late evidence timeline',!q('#incident-timeline').hidden && q('#incident-timeline').textContent.includes('Unavailable at decision cutoff'));
  q('[data-detail="trace"]').focus();
  q('[data-detail="trace"]').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
  assert('keyboard evidence tabs',q('#tab-features').getAttribute('aria-selected')==='true');
  q('#transaction-search').value='no-such-transaction';
  q('#transaction-search').dispatchEvent(new Event('input',{bubbles:true}));
  assert('empty search state',!q('#table-empty').hidden);
  q('#clear-filters').click();
  const first=q('#pagination-label').textContent;
  q('#page-next').click();
  assert('pagination',q('#pagination-label').textContent!==first);
  q('[data-view="comparison"]').click();
  assert('policy comparison',!q('#view-comparison').hidden && q('#comparison-content').textContent.includes('229'));
  assert('all archived policies counted',q('.policy-card h3').textContent.startsWith('3 ') && q('.policy-card .payload-details').textContent.includes('Inspect 3 version identities'));
  q('[data-view="models"]').click();
  assert('model labels and heldout population',!q('#view-models').hidden && q('#model-content').textContent.includes('321') && q('#model-content').textContent.includes('359'));
  assert('calibration fitting status visible',q('#model-content').textContent.includes('skipped: later validation half'));
  q('[data-view="integrity"]').click();
  assert('integrity actual checks',!q('#view-integrity').hidden && q('#integrity-content').textContent.includes('Injected temporal faults detected'));
  assert('offline exports',q('#export-json').getAttribute('href')==='report.json' && q('#export-csv').getAttribute('href')==='decisions.csv');
  q('[data-view="review"]').click();
  q('[data-filter="incomplete"]').click();
  q('[data-detail="trace"]').click();
  window.scrollTo(0,0);
  assert('no horizontal page overflow',document.documentElement.scrollWidth<=window.innerWidth+1);
  assert('no JS runtime errors',!(window.__qaErrors||[]).length);
 } catch(error) {results.push({name:'runtime exception',passed:false,error:String(error)});}
 const output=document.createElement('output');output.id='browser-verification';output.hidden=true;
 output.textContent=JSON.stringify({width:innerWidth,results,errors:window.__qaErrors||[]});document.body.append(output);
},200));
</script>
"""


def main():
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if chrome is None:
        raise SystemExit(
            "No installed headless Chrome available; browser verification not performed."
        )
    latest = json.loads((ROOT / "var/demo/latest.json").read_text())
    source = ROOT / "var/demo/runs" / latest["run_id"] / "inspector.html"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if "--prepare" in sys.argv:
        markup = source.read_text().replace(
            "<head>",
            "<head><script>window.__qaErrors=[];addEventListener('error',e=>window.__qaErrors.push(e.message));addEventListener('unhandledrejection',e=>window.__qaErrors.push(String(e.reason)));</script>",
        )
        path = OUTPUT / "browser-instrumented.html"
        path.write_text(markup.replace("</body>", QA + "</body>"))
        print(path.as_uri())
        return
    if "--collect" in sys.argv:
        checks = []
        for width in (1440, 500):
            text = (OUTPUT / f"browser-dom-{width}.html").read_text()
            match = re.search(r'<output id="browser-verification"[^>]*>(.*?)</output>', text, re.S)
            if not match:
                raise RuntimeError(f"No completed UI checks at viewport {width}")
            checks.append(json.loads(html.unescape(match.group(1))))
        evidence = {
            "run_id": latest["run_id"],
            "protocol": "Installed Chrome, saved-file inspector, real DOM interactions; no HTTP server",
            "viewports": checks,
        }
        (OUTPUT / "browser.json").write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence, indent=2))
        if not all(item["passed"] for view in checks for item in view["results"]):
            raise SystemExit(1)
        return
    checks = []
    with tempfile.TemporaryDirectory(prefix="riskreplay-browser-") as temp:
        temp = Path(temp)
        markup = source.read_text().replace(
            "<head>",
            "<head><script>window.__qaErrors=[];addEventListener('error',e=>window.__qaErrors.push(e.message));addEventListener('unhandledrejection',e=>window.__qaErrors.push(String(e.reason)));</script>",
        )
        test_page = temp / "inspector.html"
        test_page.write_text(markup.replace("</body>", QA + "</body>"))
        for width, height in [(1440, 1100), (500, 1200)]:
            result = subprocess.run(
                [
                    chrome,
                    "--headless=new",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--no-first-run",
                    f"--user-data-dir={temp / f'profile-{width}'}",
                    f"--window-size={width},{height}",
                    "--virtual-time-budget=3000",
                    f"--screenshot={OUTPUT / f'inspector-{width}.png'}",
                    "--dump-dom",
                    test_page.as_uri(),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            match = re.search(
                r'<output id="browser-verification"[^>]*>(.*?)</output>', result.stdout, re.S
            )
            if not match:
                raise RuntimeError(
                    "Browser did not finish the UI interaction checks: " + result.stderr[-1000:]
                )
            checks.append(json.loads(html.unescape(match.group(1))))
        subprocess.run(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                f"--user-data-dir={temp / 'profile-models'}",
                "--window-size=1440,1300",
                "--virtual-time-budget=3000",
                f"--screenshot={OUTPUT / 'model-evidence.png'}",
                source.as_uri() + "?view=models",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    evidence = {
        "run_id": latest["run_id"],
        "protocol": "Installed Chrome, saved-file inspector, real DOM interactions; no HTTP server",
        "viewports": checks,
    }
    (OUTPUT / "browser.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))
    if not all(item["passed"] for view in checks for item in view["results"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
