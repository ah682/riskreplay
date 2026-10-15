# Executed codebase review — 2026-10-15

## Static hosting preparation

The later portfolio packaging check passes **246 tests** in 39.02s, Ruff and
Python compilation. All 34 Python files pass format checking. `make pages`
generates and exports the 1,800-transaction demo with the dataset and semantic
hashes reported below. Six exporter tests verify file fidelity, synthetic-only
publication, tamper detection, required manifests and safe output ownership.
Hosted workflow and deployment checks are pending.

## Core review

The original prompt and delivered code were re-reviewed. The original 190 tests
passed, but independent source reviews and small failure probes found eight defects.
Those defects were repaired with regression tests. The final source passes **240
automated tests** and **249 browser component assertions**. Independent review of
the repairs found no remaining Critical, Important or Minor findings after its
three reporting follow-ups were resolved. This is evidence for the scoped local
release, not a claim that software is bug-free or merchant-validated.

The [2026-10-14 audit](VERIFICATION_2026-10-14.md) and
[2026-10-13 audit](VERIFICATION_2026-10-13.md) remain historical records. Current
machine-readable evidence is retained locally under
`var/verification/review-2026-10-15/`. Generated audit runs are excluded from the
source repository; the commands below describe how to reproduce the checks.

## Repairs and regression evidence

| Reproduced defect | Repair and verification |
| --- | --- |
| A failed demo marked an unrelated directory as owned, allowing reset to delete it | Demo refuses nonempty unowned and symlink roots; invalid generator arguments create no marker. Reset also rejects symlinked ownership markers. `test_review_regressions.py`, `test_cli_config.py` preserve unrelated files. |
| Interrupted report writes published partial runs and blocked retry | All six exports and manifest are staged, then atomically published. Tests interrupt HTML and manifest writes, inspect the API during writing, and retry successfully. `test_report_recovery.py`. |
| An unreadable manifest crashed the entire run listing | Structured 422 for the damaged run; healthy runs remain available with a partial-failure notice. `test_report_recovery.py`, `test_web.py`. |
| A complete checkpoint after a coverage gap trusted stale list/flag membership | Recovery requires explicit subsequent account state. Offline replay stays incomplete; the independent online reference raises an explicit error. Gap, refresh, account, tie, correction and backfill cases: `test_temporal_recovery.py`. |
| Missing historical state silently moved the frozen test window backwards | Every selected decision remains in its original window, label counts and capacity denominator. Missing features cannot enter fitting/scoring; scores are null and counts/IDs remain visible. Full-missing, partial-missing, missing-first/last-decision and missing-transaction regressions: `test_review_regressions.py`. |
| Nonpositive/noninteger feature windows could yield an apparently valid zero-velocity decision | Archive/build validation rejects invalid windows; imported invalid feature specifications return incomplete with no action/score. `test_temporal_recovery.py`. |
| Malformed port configuration crashed unrelated CLI commands | Port parsing is limited to `serve`, checks 1–65535, gives actionable errors and supports explicit override. `test_cli_config.py`. |
| UI omitted other-unobserved outcomes and scored support under missing state | Separate label/coverage cards, actual scored mature denominators for models and cohorts, and split coverage. A real browser fixture checks nonzero unknown and missing-state categories. Tuning messages and evaluation documentation now describe eligibility accurately. |

All newly identified behavioral failures were observed before their respective
repairs. Changes follow the existing module boundaries, use focused helpers and
plain domain names, and add no product dependencies or speculative abstractions.
All 32 Python source/test/script files pass the formatter. The source scan found
no unfinished application stub; the lone bare `pass` is an exception class body.

## Executed commands and results

| Command / protocol | Actual result |
| --- | --- |
| `make check` | Ruff and Python compilation passed; 240 tests passed in 39.68s after integration |
| Final frozen source: `.venv/bin/python -m pytest -q --junitxml=var/verification/review-2026-10-15/tests.xml` | 240 passed in 46.51s; no failures or skips |
| Clean source: `make check` in `/tmp/riskreplay-review-clean-source` | 240 passed in 48.04s; lint and compilation passed |
| `ruff format --check riskreplay tests scripts` | All 32 files formatted |
| `node --check riskreplay/static/app.js` and `node --check scripts/browser_audit.js` | Passed |
| Clean source with no environment/data: `RISKREPLAY_PACKAGE_SOURCE=…/.venv/lib/python3.12/site-packages make demo` | Copied 28 exact-version public distributions; real imports verified; full 1,800-transaction workflow completed |
| Working source: `make demo` | Full default demo completed; eight integrity checks passed |
| Actual hatchling 1.27.0 wheel build, local wheel installation, `uv pip check` | All 29 distributions compatible; all 18 installed production files match frozen source |
| Installed wheel from `/tmp`: `python -I -m riskreplay --data-dir /tmp/riskreplay-review-wheel-demo demo --seed 17 --transactions 1800` | Full default workflow outside source; identical report, dataset and trained model bytes |
| `make evaluate` | Reused verified persisted data and evaluation; same decisions/metrics, seven applicable checks |
| `verify-reproducibility --transactions 600 --output var/verification/review-2026-10-15/reproducibility.json` | Two fresh workflows: identical datasets, semantic reports and both trained model files |
| `scripts/verify_models.py --seed 17 --transactions 7200 --root var/verification/review-2026-10-15/calibrated-demo --output var/verification/review-2026-10-15/model-audit.json` | Passed in 300.98s total; 630 independent metric checks; all held-out predictions verified; no oracle reads or source changes |
| `scripts/verify_browser.py --prepare --output-dir var/verification/review-2026-10-15`, generated Playwright controllers, then `--collect` | 249/249 component assertions over 11 cases; actual 390/768/1440px viewports; no runtime errors |
| Exact-version package metadata and physical artifact checks | All 28 pins match; all six exports validated in each of three default runs; six trained model files hash-verified; 33 prior report files unchanged |

Test and demo jobs ran concurrently; durations are not isolated performance
benchmarks. There is no separate configured static type checker, and none is claimed.

The fresh uncached PyPI installation attempt failed at DNS resolution on
`pypi.org`. The new clean environments therefore used exact locally available
public distributions. The wheel was built with the declared cached hatchling
1.27.0 backend, installed normally without an editable import, and executed in
isolation. This does not repeat the successful uncached PyPI download recorded
on 2026-10-14. No security restriction was bypassed.

## Requirement-to-evidence mapping

All test modules below ran in the final 240-case suite. The original 12 mandatory
cases are numbered explicitly.

| Prompt requirement | Implementation and fresh evidence | Boundary |
| --- | --- | --- |
| CPU library/CLI, simple UI/API, Parquet and equivalent SQL engine, GBDT | `riskreplay/`, clean setup, installed-wheel demo, pipeline/API tests | SQLite is the permitted local SQL equivalent; TCP listener unavailable here |
| Validated temporal contract, immutable IDs/hashes, source, corrections and duplicates | `schema.py`, `storage.py`, invariant and delivery tests | Imported provenance must be truthful; hashes do not establish authenticity |
| Original reproduction and explicit candidate evaluation modes | `policy.py`, `cli.py`, actual subprocess workflow tests | Candidate pre-test comparisons are retrospective diagnostics |
| **1. Tuesday list does not affect Sunday** | `test_temporal.py`, Sunday/Tuesday invariants | Original knowledge excludes the later addition |
| **2. Friday outcome unavailable to Monday training** | Delayed-label, training-cutoff and generator tests | Unavailable labels cannot become targets |
| **3. Duplicate delivery does not inflate velocity** | Identity invariants and `test_online.py` | Duplicate delivery remains in audit evidence |
| **4. Earlier event arriving late is excluded** | Availability-versus-event-time baseline test | Hindsight baseline is labeled explicitly |
| **5. Corrections/backfills preserve prior history** | Invariants and `test_full_verification.py` | Future suffix, correction chains, account moves and redelivery checked |
| **6. Missing list/model/feature state is incomplete** | Artifact/coverage tests and new temporal recovery regressions | Gap recovery cannot fabricate state; no replacement action/score |
| **7. Tied timestamps are reproducible** | Cutoff tuple, boundary, shuffled input, recovery and split tests | Availability plus stable sequence, never time alone |
| **8. Archived originals reproduce on complete fixtures** | Independent live recorder and both fresh profiles | 1,800/1,800 and 7,200/7,200 before deliberate defects |
| **9. Candidate changes retain unknown counterfactuals** | Decline/approval regression, generator, CLI and browser cases | Default run has 229 differences; no ROI claim |
| **10. Feature/model/rule changes distinguished** | Consequential-artifact trace tests and incident UI | Ordered diagnostic attribution, not causal attribution |
| **11. Chronological and label leakage caught** | Training-only preprocessing, oracle/label/provenance tests, injected split checks, frozen-window regressions | Missing evidence cannot shift the final test period |
| **12. Repeated semantic outputs identical** | Two 600-row reruns; three full 1,800-row source/wheel workflows | Runtime metadata excluded as documented |
| Genuine logistic/boosted/rules baselines and artifacts | Estimator tests, wheel run, independent larger audit | Fixed logging scorer is explicitly a fixture; evaluated classifiers are trained |
| Validation tuning/calibration, frozen test, seeds | Modeling tests and fitted-calibration profile | Thin calibration support disclosed; missing fitting evidence may reject training |
| PR-AUC/AP, calibration, capacity, cohorts, amount measures | 630 independent formula checks, saved-prediction verification, raw-score tests | `metric_n` means mature scored rows; capacity denominator includes all test decisions |
| Separate mature/immature/declined/other-unobserved/missing-state reporting | Modeling, full-missing-period regressions, API and new browser evidence fixture | Missing state overlaps label status; it is not a fifth label category |
| Baselines, faults, false alarms, online/offline agreement and performance | `checks.py`, pipeline, both full profiles and attached hardware measurements | Synthetic controls, not production incident captures |
| Sequential seeded generator, schedules, policy changes, outages, isolated oracle | Generator tests and audited larger workflow | Owned synthetic data only; no normal-pipeline oracle reads |
| JSON/CSV/readable HTML, hashes and reproducible run identity | Storage/report/export/API tests, physical file checks, interruption/retry regressions | Unsigned integrity; legacy runs may lack export manifests |
| Incident timeline, provenance, first divergence, policy comparison | Persisted report tests and real browser component interactions | Live HTTP and physical-pointer limits below |
| Run selection, loading/empty/error/partial/retry, responsive/keyboard UI | Eleven browser scenarios and actual ASGI response captures | 249 assertions; no browser-download or screenshot success inferred |
| Readable contrast and safe untrusted text | Twenty rendered contrast scans, literal-HTML fixture, JSON/CSV tests | Minimum measured ratio 4.68:1; not a full WCAG audit |
| Credential-free core, read-only defaults, provider distinction | CLI/API method/path/symlink tests and isolated wheel demo | No connected provider, paid service, external write or LLM |
| Setup, pins, environment configuration and safe reset | Clean setup, package compatibility, config/reset regressions | Fresh network install blocked; offline exact-pin installation passed |
| CI, docs, walkthrough, baseline references and data permissions | CI-equivalent checks, maintained docs/README; starting references reopened | Hosted CI not invoked; upstream code/data/scores not represented as our own |
| Genuine merchant incident/deployment and investigation-time validation | Explicit separate partner gate | Not performed: permitted records, production captures and baseline measurements absent |

## Representative measurements

Default seed 17, 1,800 transactions, run **`rr-5ac1cc7243268812`**:

- 1,798 matched; one deliberately perturbed score and one deliberately absent model.
- 1,799 reconstructable decisions; pristine online/offline agreement 1,800/1,800.
- 229 candidate action changes; 1,696 mature labels, 25 immature and 79 declined.
- Test population 359; 321 mature scored labels: 26 fraud and 295 genuine;
  25 immature and 13 declined. Training uses pristine pre-injection evidence.
- Logistic AP 0.479215, PR-AUC 0.469964, Brier 0.055426.
  Boosted AP 0.427729, PR-AUC 0.425497, Brier 0.055032.
- One serial comparison pass on AMD Ryzen 7 9700X: 308.84 comparisons/s,
  median 3.057ms, p95 4.537ms. Other audit jobs ran concurrently; no SLA claim.
- Dataset hash `5af04809e8506f384562b1af7f5a090469e9b86c7dbc83a2aab34422edb87e69`;
  semantic hash `44b75b0a874717de0cff70535388754065a499db78f93a827d6ef749e75a8827`.

Larger seed-17 profile, 7,200 transactions, run **`rr-78c1bc02dac8ba9b`**:

- 7,200/7,200 pristine online/offline matches; 4/4 injected faults detected;
  0 false alarms among 7,199 complete controls.
- 1,263 held-out predictions per model verified against actual saved estimators.
- 1,124 mature scored test labels, including 48 fraud; 100 immature, 39 declined.
- Both calibrators fit 309 labels, including only three fraud positives. Execution
  is verified; reliable merchant calibration is not established.
- 630 independently recomputed metric assertions; no oracle reads; all 18
  production Python/static files unchanged during the 300.98-second audit.

## Explicitly uncompleted checks

Loopback binding still fails with `EPERM`. Actual ASGI requests and browser
components were tested separately; live HTTP, HTTP deep links, browser export
downloads and browser enforcement of server headers remain unverified. Browser
file navigation was blocked in the earlier audit and was not bypassed here.
Fresh pointer automation timed out waiting for stable rendering (2.5s); fresh
screenshot capture timed out after fonts loaded (5s). Programmatic DOM clicks,
real keyboard events, accessibility snapshots and rendered layout/contrast checks
passed; no new screenshot or physical-pointer success is claimed.

The browser collector deliberately records `fully_verified: false` despite all
component assertions passing. Hosted CI was not run, and a real Git repository is
not configured. Fresh uncached package downloads were blocked. Genuine merchant
usefulness still requires the permitted data and comparison described in
[LIMITATIONS](LIMITATIONS.md). No push, deployment, payment change or external
message was performed.
