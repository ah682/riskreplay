# Verification — 14 October 2026

This is a historical audit. Generated artifact paths refer to local files excluded
from the source repository. See the [current verification record](VERIFICATION.md)
for later local and hosted checks.

The temporal replay contract was audited, including all 12 acceptance cases.
The audit found and fixed temporal target handling, input-validation and integrity
defects. The final automated suite passes in both the documented local environment
and a fresh PyPI environment. The run used synthetic data; live browser/HTTP
integration, hosted CI and merchant evaluation were still to be done.

The [2026-10-13 verification record](VERIFICATION_2026-10-13.md) and its artifacts
record the preceding run.

## Executed commands

| Command / protocol | Observed result |
| --- | --- |
| `make demo` in a new source directory with no `.venv` or data | Exact 28 local distributions copied into an isolated environment; complete 1,800-transaction generation, training and reporting; eight integrity checks passed |
| `make demo` in the working source | Same dataset, semantic report and fitted model hashes as clean source |
| Empty virtualenv, uncached PyPI installation, actual wheel build/install | All 28 pins installed; 29 packages compatible including RiskReplay; all 18 production Python/static files match the installed wheel |
| Installed wheel: `python -I -m riskreplay --data-dir …/clean-wheel-final demo --transactions 1800 --seed 17`, from `/tmp` | Full default demo outside source directory; same semantic report and models as both source runs |
| `make check` | Ruff and compilation passed; **190 tests passed in 48.63 seconds**, no failures or skips |
| Fresh PyPI interpreter: `python -m pytest -q --junitxml=var/verification/final-pypi-tests.xml` | **190 tests passed in 48.75 seconds**; Ruff and compilation also passed in that environment |
| `node --check riskreplay/static/app.js` | JavaScript syntax passed |
| `scripts/verify_browser.py --prepare`, generated Playwright controllers, then `--collect` | **232/232 browser component assertions** across ten cases; full final report at 390/768/1440px; zero recorded JavaScript errors |
| `make evaluate` | Same saved-data decisions and model metrics; run `rr-3573af4cfe2dfa7b`; seven applicable integrity checks passed |
| `.venv/bin/python -m riskreplay verify-reproducibility --transactions 1800 --output var/verification/reproducibility-full.json` | Two fresh full-size workflows: identical semantic reports, datasets and both model files |
| `.venv/bin/python scripts/verify_models.py --seed 17 --transactions 7200` | Completed in 272.26 seconds; 603 independent metric assertions passed; every held-out prediction matched its saved estimator; both calibration branches fitted |
| Actual subprocess import/replay/compare/evaluate/reset and malformed-input audit | 60 delivery tests passed; fresh owned 64-decision import reproduced 64/64 originals and exposed 28 candidate changes |

After the contrast/presentation changes, the rebuilt installed wheel also executed
`evaluate` successfully: run `rr-7c24754f4ad246eb`, unchanged decisions and metrics,
seven applicable checks. The working directory retains the full demo as latest.

The full test suites ran concurrently; their durations are not isolated benchmarks.
The 190 cases comprise 60 delivery, 44 temporal invariant, 21 API, 17 model,
11 generator, 11 review regression, nine online, nine extended temporal/model,
seven pipeline and one initial Sunday/Tuesday case. Parameterized cases count
separately. No separate static type checker is configured.

Fresh installation commands:

```bash
python3 -m venv --without-pip /tmp/riskreplay-clean-20261014
uv pip install --python /tmp/riskreplay-clean-20261014/bin/python \
  --no-cache --index-url https://pypi.org/simple -r requirements.lock
uv pip install --python /tmp/riskreplay-clean-20261014/bin/python \
  --no-deps --no-cache --index-url https://pypi.org/simple .
uv pip check --python /tmp/riskreplay-clean-20261014/bin/python --no-cache
```

The wheel was rebuilt after production fixes. The clean source directory was
`/tmp/riskreplay-clean-source-20261014`. The PyPI/wheel branch used no package cache,
donor copying or editable source import. The documented `make demo` branch
separately verified copying exact installed public distributions.

## Requirement-to-evidence mapping

All referenced test modules ran in the final 190-case suite through `make check`.
The larger profile and environment audit provide additional checks.

| Requirement / mandatory case | Implementation and executed evidence | Result and boundary |
| --- | --- | --- |
| CPU library, CLI, API/UI, immutable Parquet, local SQL, GBDT | `riskreplay/`, clean setup, built-wheel demo, pipeline/API tests | Complete local workflow; SQLite is the permitted equivalent engine; TCP listener blocked here |
| Validated IDs, timestamps, sequence, hashes, source, correction lineage | `schema.py`, `storage.py`; invariant and delivery tests | Actionable invalid-input errors before persistence; exact valid roundtrips |
| Separate original and candidate modes | `policy.py`, `cli.py`; real replay/compare/two-policy CLI tests | Matched/mismatched/incomplete; explicit candidate knowledge and retrospective regime |
| **1. Tuesday list cannot affect Sunday** | `test_temporal.py`, invariant Sunday/Tuesday cases | Sunday unblocked, Tuesday sees addition |
| **2. Friday outcome unavailable Monday** | `test_friday_fraud_cannot_enter_monday_training` and generator/invariant cases | Future targets excluded; missing never becomes zero |
| **3. Duplicate delivery cannot inflate velocity** | Identity invariants and `test_online.py` | Deliveries retained; one eligible event identity contributes |
| **4. Earlier event arriving late is excluded** | `test_earlier_event_delivered_late_distinguishes_availability_from_event_time` | Original excludes; labeled event-time hindsight admits it |
| **5. Corrections/backfills preserve history** | Invariants and `test_full_verification.py` | Future suffix leaves original unchanged; correction chains/account moves/old redeliveries agree online/offline |
| **6. Missing list/model/feature state is incomplete** | Coverage/artifact/interpreter tests and actual CLI imports without archives | No fabricated action/score; explicit missing reason |
| **7. Ties are reproducible** | Cutoff tuple, window boundary, shuffled input and split tests | Inclusive availability/sequence cutoff; stable ties within split |
| **8. Archived originals reproduce** | Independent `OnlineReference`, pristine audits, pipeline tests | 1,800/1,800 default and 7,200/7,200 larger profile before defects |
| **9. Candidate changes retain unknown outcomes** | Declined-approval counterfactual test, generator/CLI tests | 229 default action changes; approval outcomes remain unknown |
| **10. Feature/model/rule attribution** | Parameterized consequential-artifact trace tests | Explicit feature → model → rule order; diagnostic, not causal attribution |
| **11. Chronological/label leakage caught** | Model leakage, future provenance, oracle exclusion, injected split/label tests | Train-only preprocessing and frozen-test isolation pass; leaky fits rejected |
| **12. Identical semantic reruns** | Full 1,800-row reproduce command and source/wheel comparison | Decisions, metrics, datasets and both model files identical in pinned runtime |
| Historical labels survive later corrections | Split-local target resolution; nine extended tests | Later correction cannot remove/change earlier fit targets or model bytes; earlier corrections affect appropriate targets; test-only corrections change metrics without refitting |
| Genuine rules/logistic/boosted baselines | Estimator/artifact tests, independent larger audit | Real CPU fitting; archived parameters/seeds; logging fixture explicitly identified |
| Validation tuning/calibration/frozen test | Model tests and 7,200-row profile | Disjoint fit/tune/calibration/test sets; frozen estimator unchanged; thin calibration support disclosed |
| PR metrics, reliability, capacity, cohorts, amount denominators | `verify_models.py` independent formulas and extended raw-score test | 603 final-score checks plus 134 raw diagnostic checks; all held-out scores match archived estimators |
| Mature/immature/declined/unknown/missing-state separation | Generator/model/report/CLI/API tests | Missing labels never genuine; coverage is separate from label maturity |
| Availability/current-state/event-time baselines | Engine/pipeline baseline tests and reports | Same reconstructable denominator; raw divergences retained |
| Integrity faults, false alarms, online/offline agreement | `checks.py`, independent streaming tests, both full runs | 4/4 faults; zero false alarms on complete synthetic controls; no production capture comparison |
| Seeded generator, delayed labels, policy shifts, flags/outages, oracle isolation | Generator tests and audited larger run | Fixed schedule/seed; zero oracle reads in normal larger workflow |
| JSON/CSV/HTML, hashes/configuration/identity | Storage/report/CLI tests and environment audit | Six-file checksums on new runs; lossless JSON; documented CSV formula neutralization |
| Untrusted text, corrupt artifacts, invalid inputs | Delivery/API/review regression tests | Altered bytes, missing semantic hashes, malformed provenance/schema, markup and quoting handled |
| Incident timeline, provenance, versions, first divergence | Report persistence/API tests and browser audits | Full inspectable evidence; browser scope below |
| Run selection, loading/empty/error/partial/retry, responsive/keyboard UI | `static/`, ASGI tests, browser scripts | 232/232 component assertions across ten cases; actual keyboard and DOM event handling; live HTTP/pointer/screenshot limits below |
| Readable text contrast and immutable viewer updates | Computed-style contrast scans; new pipeline regression | All 19 final scans pass, minimum 4.68:1; changed viewer creates new inspector while preserving prior bytes and decisions/metrics |
| Read-only defaults; credential-free core; provider distinction | CLI/API design, method/path/symlink tests, offline installed-wheel demo | No live provider write, paid service or LLM; real integrations not simulated as successes |
| Setup, lock, environment/configuration and reset | Makefile, lock, `.env.example`, actual clean demo and reset tests | Both install paths pass; unowned reset refused |
| Tests and CI configuration | 190 cases, `.github/workflows/ci.yml`, fresh-environment checks | CI-equivalent commands passed locally; hosted CI not invoked |
| Docs, walkthrough, references and data permissions | README and required docs updated; reference/source review | Owned synthetic data identified; no upstream code/data/scores relabeled as our result |
| Real incident/deployment and investigation-time comparison | Separate explicit partner gate | Not performed; permitted partner records and baseline measurements absent |

## Defects fixed

1. Later outcome corrections could hide earlier mature training targets. Targets
   now resolve independently at each split cutoff, preserving historical fit
   membership, targets and model bytes.
2. Malformed timestamp types, boolean scores/schema versions, invalid feature
   containers and malformed provenance could bypass checks or raise unhelpful
   errors. The normalized contract rejects them explicitly.
3. Dataset manifest counts were unchecked. Loading reconciles them with records,
   in addition to file hashes and normalized content identity.
4. Altered reports could retain old semantic hashes, and exports lacked complete
   checksum checks. Semantics are recomputed; new manifests cover all six exports;
   API reads and run reuse verify the relevant bytes.
5. Evaluation could consume an altered sidecar. It now reads evaluation evidence
   from the verified canonical report and checks its dataset identity.
6. Valid provider transaction IDs containing punctuation, spaces, Unicode or slashes
   were rejected by the API. They are now treated as data; run/file restrictions remain.
7. Implicit five-fold calibration prediction warned with three positive labels.
   Explicit two-fold prediction removes that warning, not the small-sample limitation.
8. Small muted labels fell below 4.5:1 contrast on their actual backgrounds. Text
   colors were corrected without changing layout or font sizes; measured final
   contrast checks pass across all four product views.
9. Run identity omitted presentation assets, allowing an existing inspector to
   retain older UI source. It now includes a presentation hash. A real stylesheet
   revision test verifies a new inspector, unchanged decisions/metrics and preserved
   old report bytes.

## Default results and identity

Seed 17; run **`rr-3d76233462ac420b`**. Open the
inspector (local artifact: `var/demo/runs/rr-3d76233462ac420b/inspector.html`),
readable report (local artifact: `var/demo/runs/rr-3d76233462ac420b/report.html`) or
machine report (local artifact: `var/demo/runs/rr-3d76233462ac420b/report.json`).

| Identity | SHA256 |
| --- | --- |
| Dataset | `29eb40a35d78f29e722cbdc0c71e975ebe421affa479e6eb1b4d1307e7bed833` |
| Semantic report | `5d46dd4abb6e6e193a6d5c56af2bb81eb972d7a20844f0ea211a6070bfdd1e16` |
| Logistic file | `a93e4d2ccf93f708727ac632b20c7a8a9d62cc7ea71529146380c505e531cc89` |
| Boosted file | `c9cccffc14affebbdb86fb0ae60532b7fbb50cc757d1db748e96dc6fb013dc5b` |

The 1,800-row report has 1,798 matched, one deliberately perturbed score (`t-monday`),
one missing model (`t-after-outage`), 1,799 reconstructable cases and 229 candidate
changes. Label support: 1,696 mature, 25 immature, 79 declined/unobserved. Before
defects, 1,800/1,800 original decisions and independent feature snapshots agreed.
Fault detection: 4/4; false alarms: 0/1,799.

| Information regime | Action matches / 1,799 | Feature matches / 1,799 |
| --- | ---: | ---: |
| Availability and event time | 1,799 | 1,799 |
| Event-time-only hindsight | 1,797 | 1,761 |
| Naive current-state hindsight | 1,718 | 1,631 |

Full replay differs from action agreement because the intentional score corruption
does not change that transaction's action. Raw divergent IDs are preserved.

The final test has 359 transactions: 321 mature (26 fraud, 295 genuine), 25 immature
and 13 declined/unknown. Each model fits 956 mature training targets, including
98 fraud. Capacity is 35 of all 359 test transactions before label filtering.

| Model | Average precision | Trapezoidal PR-AUC | Brier | Observed review precision | Observed recall |
| --- | ---: | ---: | ---: | --- | --- |
| Fixed rules | 0.352393 | 0.601062 | 0.058929 | 13/24 = 0.541667 | 13/26 = 0.500000 |
| Logistic | 0.479215 | 0.469964 | 0.055426 | 11/23 = 0.478261 | 11/26 = 0.423077 |
| Gradient boosted | 0.427729 | 0.425497 | 0.055032 | 11/23 = 0.478261 | 11/26 = 0.423077 |

Rules select 11 unknown outcomes; learned models select 12 each. Precision for
the full selected population is unidentified. The small default calibration window
lacks required class support, so separate fitting is explicitly skipped; held-out
Brier and reliability bins remain reported.

## Larger calibration and independent metric audit

The fixed seed-17, 7,200-row profile was declared before running; no favorable seed
search was performed. Run `rr-9ef879d487a5d71f` passed all eight integrity checks:
7,198 matched plus two intentional defects; online/offline agreement 7,200/7,200;
four true-positive faults, zero false negatives, zero false positives, 7,199 controls.
No production source changed during the final run and no oracle file was read.

Training used 3,933 mature targets. Every one of 1,263 test predictions per model
matched the archived estimator. Test labels: 1,124 mature (48 fraud, 1,076 genuine),
100 immature, 39 declined/unknown. Both sigmoid calibrators fit 309 later-validation
rows: **306 genuine and only three fraud positives**, with no base-estimator refit.
This verifies execution and separation, not reliable merchant calibration.

| Model | Average precision | Trapezoidal PR-AUC | Brier |
| --- | ---: | ---: | ---: |
| Rules | 0.161977 | 0.381632 | 0.044500 |
| Logistic | 0.181291 | 0.172925 | 0.039816 |
| Gradient boosted | 0.175702 | 0.166935 | 0.039675 |

At global review capacity, rules capture 21 observed fraud cases, logistic 19 and
boosted 17. No universal model superiority is shown. Independent formulas check
ties, PR metrics, reliability bins, Brier, cohorts, review allocation and amounts.
Separate tests also verify raw uncalibrated predictions and 134 metric assertions.

## Performance

The final separate warm serial pass processed 1,800 original/candidate comparisons
in **4.879101 seconds**, **368.92 comparisons/second**, median **2.664 ms**, p95
**3.769 ms**, after ten untimed warmups. It ran after model and pytest processes
completed. Hardware: AMD Ryzen 7 9700X, 16 logical CPUs, Linux x86_64, Python 3.12.3;
model numerical threads limited to one. Raw individual durations are saved.

Timing includes features, scoring and attribution; excludes training, timelines
and exports. Other saved runs have different measured timings. None is an SLA.

## Browser and external limits

The earlier full saved-file Chrome audit passed **38/38 assertions** at actual
1,440px and 500px widths. Layout and JavaScript remain unchanged; current text
colors were improved after contrast measurement. The historical screenshots
were visually inspected again: responsive layout, visible focus and explicit
missing-model evidence. They show historical run `rr-48ab91e01d6c3783`.

The expanded current browser audit uses actual product markup/CSS/JS and explicit
ASGI response captures, mounted through Playwright's supported `page.setContent`.
It passed **232/232 assertions** on the final run across ten cases: full reports
at 390/768/1440px, empty records, untrusted HTML, no saved runs, partial unavailable
runs and switching, corrupt reports, transport failure/retry, and timeout/retry.
There were no recorded runtime errors or horizontal page overflows. The 19 final
contrast scans pass with minimum 4.68:1. Thirteen actual ASGI responses were
captured, with seven explicit API/byte checks including all three export formats.

Interactions use programmatic DOM clicks/input and real Playwright keyboard
events; physical pointer automation stalled while waiting for stable frames.
The timeout fixture shortens only the 20-second deadline to 250ms and exercises
the actual AbortController cancellation and recovery. Address-bar changes are
captured rather than applied to the `about:blank` origin. These tests do not verify
HTTP deep links, browser downloads or a live connection. Initial failed/stalled
attempts and pre-contrast results are preserved separately and are not counted in
the final pass. Fresh screenshot attempts timed out even after bringing the page
to the foreground.

Live Uvicorn serving cannot bind even an ephemeral loopback socket:
`PermissionError: [Errno 1] Operation not permitted`. `serve --port 8765` exits
without a listener; curl cannot connect. Native Chrome currently exits on a socket
restriction, and Playwright file navigation is blocked. No security control was
bypassed. Actual ASGI application methods, headers, errors and export bytes pass;
browser-to-server integration, downloads and browser header enforcement remain
unverified. Fresh browser screenshot capture also times out.

At this date, hosted CI and public deployment had not been configured; equivalent
workflow commands passed locally. Merchant evaluation still needed permitted
incident records, archives, ingestion logs, provider mappings, online feature
captures and investigation-time comparisons.

Earlier runs without export manifests retain semantic report checks but lack
checksums for other exports. New final runs have verified six-file manifests.

## Machine evidence

Final aggregate audit (local artifact: `var/verification/final-audit.json`) reconciles all final source, report and evidence identities.

- Fresh installation (local artifact: `var/verification/installation.json`) and environment/source/wheel audit (local artifact: `var/verification/environment-audit.json`)
- Final fresh-environment JUnit (local artifact: `var/verification/final-pypi-tests.xml`)
- Full-size reproducibility (local artifact: `var/verification/reproducibility-full.json`)
- Delivery/storage/CLI audit (local artifact: `var/verification/storage-audit.json`)
- Independent model audit (local artifact: `var/verification/model-audit.json`)
- Raw final performance (local artifact: `var/verification/performance-final.json`)
- TCP capability (local artifact: `var/verification/tcp-capability.json`)
- Current browser component and ASGI audit (local artifact: `var/verification/ui-audit.json`)
- Historical browser assertions (local artifact: `var/verification/browser.json`), desktop (local artifact: `var/verification/inspector-1440.png`), 500px screenshot (local artifact: `var/verification/inspector-500.png`)
