# Executed release verification

This is a historical audit. Generated artifact paths refer to local files excluded
from the source repository. See the [current verification record](VERIFICATION.md)
for the published release and hosted checks.

Verified locally on 2026-10-13. This is an owned synthetic demonstration. No merchant
data, payment connection, public deployment or customer validation was performed.

## Commands and outcomes

| Executed command | Observed result |
| --- | --- |
| `make reset demo` | Clean 1,800-transaction generation, real training, persistence, comparison and reports; 8 integrity checks passed |
| `make check` | Ruff and Python compilation passed; **115 tests passed in 6.49 seconds** |
| `node --check riskreplay/static/app.js` | JavaScript syntax passed |
| `make evaluate` | Same saved-data decisions/metrics; separate immutable run `rr-65e9a2b32f279dd2`, 7 applicable checks passed |
| `make reproduce` | Two fresh 600-transaction runs with identical semantic reports, datasets, decisions, metrics and both fitted model hashes |
| `.venv/bin/python -m riskreplay replay t-sunday` | Matched approval, score 0.033569223281, blocked 0, velocity 2, amount sum 65 |
| `.venv/bin/python -m riskreplay compare t-tuesday` | Original/candidate decline; changed artifacts explained; approval outcome explicitly unknown |
| `.venv/bin/python scripts/browser_qa.py --prepare`, then installed headless Chrome | **38/38** real DOM assertions across actual widths 1,440px and 500px; no JavaScript runtime errors or page overflow |

Setup reused 28 exact-version installed public distributions in an isolated
`.venv`, then verified versions and runtime imports. A fresh network package
download was blocked by environment policy. Python 3.12 and `requirements.lock`
define the environment. External CI was not invoked; its fast-suite configuration
is provided in `.github/workflows/ci.yml`.

The 115 tests comprise 44 temporal invariants, 17 model tests, 16 API cases,
11 generator tests, 11 review regressions, 9 independent streaming checks,
6 pipeline tests and the initial Sunday/Tuesday acceptance test. Parameterized
cases count separately. The evaluation rerun does not receive the pristine
pre-defect recording, so that independent audit is explicitly unavailable there.

## Saved release identity

Seed 17; default run `rr-48ab91e01d6c3783`. Open the
interactive inspector (local artifact: `var/demo/runs/rr-48ab91e01d6c3783/inspector.html`),
readable report (local artifact: `var/demo/runs/rr-48ab91e01d6c3783/report.html`), or
full machine report (local artifact: `var/demo/runs/rr-48ab91e01d6c3783/report.json`).
Generated artifacts are recreated by `make demo`.

| Identity | SHA256 |
| --- | --- |
| Normalized dataset | `29f021717002c4af5b7b933cd3a887b52f5bcf230d60f5a7e2b3f21d292a5b76` |
| Semantic report | `50d07fbbbc52e105631df2cb74a48df946d4fc3506747b0f284a7e49ec043510` |
| Fitted logistic file | `58922202d4824c54f51880babd6741889dc63a243f3670e66cb64cd78899c6fc` |
| Fitted boosted file | `501a5864147a6dcdd9b27d6746cda88c7064bf3fe85ac93daff68a07a96ceb95` |

All policy/feature/rule/model identities, interpreter hashes, fit IDs, seeds and
split boundaries are preserved in the run and artifact manifests.

## Requirement-to-evidence mapping

Every referenced test was executed by `make check`.

| Capability / acceptance case | Implementation and test evidence | Observed result / boundary |
| --- | --- | --- |
| Validated immutable import | `schema.py`, `storage.py`; invariant ID/hash/time/correction tests and review import/mutation/outcome regressions | Invalid records rejected; missing policy may import but cannot fully replay; no provider adapter validated |
| Tuesday list cannot affect Sunday | `engine.py`; `test_temporal.py::test_tuesday_blocklist_cannot_change_sunday` | Sunday blocked 0, Tuesday blocked 1 |
| Friday outcome unavailable on Monday | `test_modeling.py::test_friday_fraud_cannot_enter_monday_training` and generator/invariant counterparts | Future label rejected/immature, never filled with zero |
| Duplicate delivery counts once | Duplicate invariant and independent streaming tests | Deliveries retained in audit, one identity in velocity |
| Earlier event arriving late | `test_earlier_event_delivered_late_distinguishes_availability_from_event_time` | Original excludes it; event-time hindsight admits it |
| Corrections/backfills preserve history | `test_correction_and_backfill_change_hindsight_without_rewriting_history` | Earlier snapshot retains original, later uses successor |
| Missing list/model/feature state | Parameterized checkpoint, missing/corrupt artifact and unavailable implementation tests | Typed incomplete with absent action/score and explicit reason |
| Timestamps/window ordering | Cutoff sequence, open window-start and shuffled-input invariants | Inclusive tuple boundary, stable tie-breaking and window semantics |
| Archived originals and online/offline agreement | `online.py`, `pipeline.py`; full-stream and end-to-end tests | 1,800/1,800 pristine originals and independent feature snapshots match |
| Candidate changes with unknown outcomes | `test_candidate_approval_of_historical_decline_has_unknown_outcome` | Action changes without inventing approval outcome; default run changes 229 actions |
| Feature/model/rule attribution | Parameterized `test_candidate_trace_identifies_the_consequential_artifact` | Each component distinguished under the documented replacement order |
| Chronological/label leakage | Model split, future provenance, oracle exclusion and held-out mutation tests | Leaky fits rejected; changed final test values cannot affect trained artifacts |
| Repeatable outputs | Pipeline/model clean-run tests; `make reproduce` | Identical semantic results and model bytes in locked environment |
| Genuine models and metrics | `modeling.py`; real-estimator, preprocessing and raw-denominator tests | Fitted logistic/boosted; rules, PR metrics, Brier, reliability, capacity/cohorts persisted |
| Integrity detection/false alarms | `checks.py`; four labeled injected faults and complete negative controls | 4/4 detected, 0/1,799 false alarms; controlled synthetic cases only |
| Parquet/SQL/exports | Storage/reporting and pipeline roundtrip/identity tests | Hash-verified Parquet, derived SQLite v1, JSON/CSV/HTML and self-contained inspector |
| Read-only API/error states | `test_web.py`, actual FastAPI ASGI handlers through HTTPX | 16 cases pass: empty/corrupt/missing, exports, identity/path/symlink checks, method rejection |
| Incident UI/accessibility | `static/`, `scripts/browser_qa.py`, Chrome | Search/filter/pagination, missing artifact, provenance/timeline, keyboard tabs, comparison, models/calibration and integrity pass |
| Reset/unknown audit state | Pipeline reset and untrained/deduplicated import tests | Unowned reset refused; absent training evidence marked unavailable |

## Temporal results

The saved dataset deliberately contains one perturbed Monday score and one archived
policy referencing an absent model. Before injecting these defects, all 1,800
independently recorded original decisions reproduced.

| Evidence | Count |
| --- | ---: |
| Matched | 1,798 |
| Mismatched | 1 |
| Incomplete / missing historical state | 1 |
| Reconstructable denominator | 1,799 |
| Candidate action changes | 229 |
| Mature observed labels | 1,696 |
| Immature labels | 25 |
| Declined / unobserved under approval | 79 |
| Other unobserved | 0 |
| Independent streaming/offline feature agreement before defects | 1,800 / 1,800 |

The streaming recorder maintains its own account/register state without calling
the historical replay engine. Raw original vectors are saved in Parquet and the
agreement denominator/divergent IDs in `integrity.online_offline`. This is an
independent local implementation comparison, not a production feature-store check.

| Information regime | Action matches / 1,799 | Feature matches / 1,799 | Feature divergences |
| --- | ---: | ---: | ---: |
| Availability and event time | 1,799 | 1,799 | 0 |
| Event time only | 1,797 | 1,761 | 38 |
| Naive current state | 1,718 | 1,631 | 168 |

Action agreement differs from full replay agreement: the corrupted score makes one
record mismatched although its action agrees. Each baseline excludes the same one
incomplete artifact. Divergent transaction IDs are retained in the report.

## Held-out model results

Both learned models fit 956 mature training rows (98 fraud). The actual frozen test
begins 2025-03-10T02:12:18Z and contains 359 transactions. At evaluation on March 30,
321 have mature observed labels: 26 fraud, 295 genuine. The other 25 immature and
13 declined outcomes are excluded from label-based metrics.

| Model | Average precision | PR-AUC, trapezoidal | Brier | Review precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fixed rules | 0.352393 | 0.601062 | 0.058929 | 13 / 24 = 0.541667 | 13 / 26 = 0.500000 |
| Fitted logistic | 0.479215 | 0.469964 | 0.055426 | 11 / 23 = 0.478261 | 11 / 26 = 0.423077 |
| Fitted gradient boosted | 0.427729 | 0.425497 | 0.055032 | 11 / 23 = 0.478261 | 11 / 26 = 0.423077 |

Review capacity is floor(10% × 359) = 35, allocated before label filtering.
Trained models select 23 mature rows and 12 unknown outcomes; rules select
24 mature and 11 unknown. Precision for all selected transactions is unidentified.
Average precision and trapezoidal PR-AUC differ in interpolation; coarse rule-score
ties produce notably different results. No universal winner is claimed.

Validation was used for model selection. Separate sigmoid calibration was **skipped**:
the later validation half did not satisfy 30 labels and 3 per class. This status is
visible verbatim in UI/artifacts. Ten held-out reliability bins and Brier remain
available; empty bin rates are null. Rules are labeled uncalibrated heuristic scores.
Cohorts separately report 223 mature domestic rows (6 fraud) and 98 cross-border
rows (20 fraud), with unknown support and amount-weighting assumptions.

These metrics describe one synthetic, selected observed population. They do not
identify merchant performance, prevented loss, revenue recovery or declined
outcomes under approval.

## Performance and reproducibility

One warm serial comparison pass: **1,800 transactions in 4.996852 seconds**,
**360.23 comparisons/second**, median **2.669 ms**, p95 **3.852 ms**.
Hardware: AMD Ryzen 7 9700X 8-Core Processor, 16 logical CPUs; Linux x86_64,
Python 3.12.3; model numerical thread limits 1. Timing includes feature construction,
scoring and staged attribution, excluding training, timelines and exports.
This is one local measurement, not an SLA.

The two fresh 600-row runs both yielded semantic SHA256
`fb033342d46a7df67f39d9bc7596f9bfb33123b2b5b54aed42534e4919f19ac9`.
Machine evidence (local artifact: `var/verification/reproducibility.json`) records identical
datasets and both model files. Run ID, creation time, performance and the derived
semantic-hash field are excluded from semantic comparison. Tests also repeat two
320-row workflows and mutate held-out data to verify fitting isolation.

## Browser evidence and environment limits

Browser evidence (local artifact: `var/verification/browser.json`) contains all 38 assertions.
The desktop (local artifact: `var/verification/inspector-1440.png`) and
narrow (local artifact: `var/verification/inspector-500.png`) screenshots were visually inspected:
readable type/contrast, responsive navigation/cards/table and retained incident
detail. The desktop explicitly shows the missing-model reason. The actual narrow
viewport was 500px; Chrome imposed a minimum width, so 390px is not claimed.

The browser uses real embedded report data, an isolated profile and installed
Chrome, without a mock API or browser download. Direct Chrome calls succeeded for
the recorded checks. Nested Python launches and some extra capture invocations
were blocked by socket restrictions. The successful desktop command was:

```bash
.venv/bin/python scripts/browser_qa.py --prepare
google-chrome --headless=new --disable-gpu --disable-dev-shm-usage --no-first-run \
  --user-data-dir=/tmp/riskreplay-release-desktop --window-size=1440,1100 \
  --virtual-time-budget=3000 \
  --screenshot=/home/ava/Desktop/fraud-replay-lab-prompt/var/verification/inspector-1440.png \
  --dump-dom file:///home/ava/Desktop/fraud-replay-lab-prompt/var/verification/browser-instrumented.html
```

The narrow run used a separate profile, 500×1200 and its own screenshot. On a
normal host, `.venv/bin/python scripts/browser_qa.py` automates both and writes
the result. No HTTP listener started in that audit environment: loopback binding was denied.
Actual API handlers were tested in process, and the saved UI was rendered and
exercised in Chrome.

Remaining external gates: permitted genuine incident/deployment records, accurate
provider normalization/archive coverage, production online feature comparison,
and measured investigation time against the partner's current method. External
CI, fresh network installation, customer feedback and payment integration remain
unperformed; none is represented as a success.

