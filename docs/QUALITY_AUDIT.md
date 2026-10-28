What this repo does: RiskReplay reconstructs payment decisions from evidence available at their recorded cutoff, compares policies, and evaluates classifiers on chronological splits. Authoritative Parquet bundles and immutable reports support a read-only inspector. This audit assumes a local investigation workflow, including interrupted writes and malformed archives, rather than production payment traffic.

**Audit date:** 28 October 2026. **Method:** Ponytail 5.3.2 and relevant Superpowers 7.0.1 skills. Runtime flows were traced, each finding was reproduced, regression tests failed before repair, and focused plus full checks were rerun. Independent integration review found no unresolved issue. Hosted release checks, dependency audits and demo deployment passed.

## Must fix — resolved

1. **Incomplete reports show an obsolete transaction version** ([pipeline.py](../riskreplay/pipeline.py)).
   - **What this is:** A report still displays transaction metadata when an archived policy is unavailable.
   - **Reproduced problem:** An amount corrected from 75 to 150 before the decision cutoff was reported as 75, with its old cohort, because the fallback selected the first delivery.
   - **Small fix and outcome:** Use the transaction visible at the recorded cutoff. [The regression](../tests/test_runtime_audit.py) also includes a later correction and confirms that it remains excluded.
   - **If it regresses:** Missing policy evidence is accompanied by misleading transaction evidence.

2. **Missing feature snapshots are counted as disagreements** ([pipeline.py](../riskreplay/pipeline.py), [app.js](../riskreplay/static/app.js)).
   - **What this is:** Replay baselines compare reconstructed features with optional archived online values.
   - **Reproduced problem:** A valid decision with `feature_values={}` was called a feature mismatch, yielding 0% agreement despite no captured snapshot to compare.
   - **Small fix and outcome:** Count only captured comparisons and expose unavailable counts separately. [Python regressions](../tests/test_runtime_audit.py) and the [saved-browser fixture](../scripts/browser_qa.py) verify absent, mixed and legacy denominators; action comparisons retain their own population.
   - **If it regresses:** Absence of historical evidence falsely appears to prove reconstruction failure.

3. **Interrupted artifact writes prevent retry** ([artifacts.py](../riskreplay/artifacts.py), [modeling.py](../riskreplay/modeling.py)).
   - **What this is:** JSON policies and fitted model bytes have content-addressed final names.
   - **Reproduced problem:** An injected write error after two bytes left a truncated final file. Retrying identical content then failed instead of completing the artifact.
   - **Small fix and outcome:** Stage complete bytes beside the destination and publish exclusively, preserving conflicting existing content. [Recovery tests](../tests/test_artifact_recovery.py) cover interrupted writes, retries and competing publication.
   - **If it regresses:** A recoverable disk error strands the artifact directory until manual intervention.

4. **Malformed archives abort the investigation** ([artifacts.py](../riskreplay/artifacts.py), [policy.py](../riskreplay/policy.py)).
   - **What this is:** A valid hash establishes stored bytes, not that a manifest has the required structure or numeric values.
   - **Reproduced problem:** A feature manifest containing `[]` raised `AttributeError`; a rule with `review_score="not-a-number"` raised `TypeError` outside the incomplete-result path.
   - **Small fix and outcome:** Validate references, object shapes and interpreted numeric fields at the existing boundaries. [Parameterized regressions](../tests/test_runtime_audit.py) now produce explicit incomplete results with null action and score.
   - **If it regresses:** One malformed historical artifact stops replay rather than identifying unavailable evidence for that decision.

5. **Offline setup writes through shared package-cache files** ([setup.py](../scripts/setup.py)).
   - **What this is:** Offline installation copies exact-version distributions into the local environment; uv may already have hard-linked that environment to its cache.
   - **Reproduced problem:** Final `make pages` verification reached a `SameFileError` when source and destination shared an inode. Copying different bytes onto another hard-linked destination could also change the package used by another environment. A matching setup marker did not detect missing or incorrect installed versions. Review then reproduced an upgrade blocked by obsolete metadata and files, plus failures from damaged setup markers.
   - **Small fix and outcome:** Copy to a temporary sibling and replace the destination entry, including package trees, top-level modules and the Ruff launcher. Use uv or pip to remove obsolete installed versions before copying; their shared cache bytes remain intact. Validate installed versions before trusting the marker, treat damaged markers as stale, and clear prior readiness before repair. [The 17 setup regressions](../tests/test_setup.py) cover actual uv/pip removal, old and duplicate metadata, obsolete files, hard links, interrupted copies and marker recovery.
   - **If it regresses:** A routine rebuild can fail or modify a shared cache and another environment's package bytes.

## Should fix — resolved

6. **A damaged convenience pointer blocks an explicitly selected dataset** ([cli.py](../riskreplay/cli.py), [storage.py](../riskreplay/storage.py)).
   - **What this is:** `latest.json` supplies convenient defaults; it is not the authoritative dataset.
   - **Reproduced problem:** A truncated pointer stopped `replay --dataset <healthy-bundle>` before the explicitly selected bundle was read.
   - **Small fix and outcome:** Write mutable pointers atomically and bypass optional defaults when explicit selections suffice. [CLI regressions](../tests/test_runtime_audit.py) and [pointer interruption tests](../tests/test_artifact_recovery.py) preserve both recovery and error reporting when defaults are required.
   - **If it regresses:** Users cannot recover a healthy investigation through the documented explicit-selection command.

## Verification and process changes

| Check | Baseline | After repairs |
| --- | --- | --- |
| `.venv/bin/python -m pytest -q` | 246 passed | 297 passed with the updated dependencies, including 17 setup regressions |
| Ruff, Python compilation, JavaScript syntax | Existing checks | Passed |
| Two fresh 80-transaction workflows | Not a baseline accuracy comparison | Identical dataset, semantic and model-byte hashes within the updated runtime |
| `.venv/bin/python scripts/browser_qa.py --baseline-evidence` | Missing/mixed-denominator assertions failed | 5/5 checks passed in actual Chrome at 768px |
| `make setup` and `make pages` | Offline copy failed on shared cache links | All 28 exact-pin distributions copied, runtime imports passed, and the 1,800-transaction demo rebuilt as `rr-c5ae292e4c488950` with its static site |
| `.venv/bin/python scripts/browser_qa.py` | Existing saved-inspector checks | 19/19 checks at 1440px and 19/19 at 500px on the rebuilt demo; no JavaScript errors |

The repair scope and outcomes are recorded in the [runtime plan](superpowers/plans/2026-10-28-runtime-audit.md). Reproduce the bounded checks with:

```sh
make check
.venv/bin/python -m ruff format --check riskreplay tests scripts
.venv/bin/python -m riskreplay verify-reproducibility --transactions 80 --output var/verification/audit-reproducibility.json
.venv/bin/python scripts/browser_qa.py --baseline-evidence
```

The portable browser fixture needs installed Chrome but no trained demo, Node dependency or running server. For the full saved-inspector check, the final audit also ran:

```sh
make setup
make pages
.venv/bin/python scripts/browser_qa.py
```

[CI](../.github/workflows/ci.yml) runs both browser modes and additionally uses `make reproduce` for two 600-transaction workflows. That repeatability workload is separate from this audit's two 80-transaction runs and the rebuilt 1,800-transaction demo.

Default dependency fixes pin PyArrow 23.0.1, AnyIO 4.14.2, Starlette 1.3.1 and certifi 2026.10.19. The bounded repeatability checks and final 297-test suite passed with that stack; both browser modes passed after the setup repair and demo rebuild. Verification jobs use pinned action commits, read-only repository permissions, time limits, cancellation of superseded runs, browser checks and actionlint. [Dependency audits](../.github/workflows/dependencies.yml) run on pushes, pull requests and weekly schedules, with [Dependabot](../.github/dependabot.yml) proposing action updates.

Hosted verification of commit `b4db01bdf77cdcfa0b98c2f213ebf7b7fdd834c2` passed:

- [Release checks](https://github.com/ah682/riskreplay/actions/runs/40672845435): 296 tests passed; the installed-launcher test skipped before project setup. Formatting/static checks, a fresh demo, paired 600-transaction repeatability, both browser modes and workflow validation passed. The `replay-verification` artifact retains the generated evidence for 14 days.
- [Dependency audit](https://github.com/ah682/riskreplay/actions/runs/40672845459): the installed pinned environment has no known reported advisories.
- [Pages deployment](https://github.com/ah682/riskreplay/actions/runs/40672845546): `make check` passed all 297 tests after project setup, including the installed launcher, and the rebuilt [saved inspector](https://ah682.github.io/riskreplay/) was published successfully.

Subsequent documentation-only commits do not change this tested implementation.

Verdict: All six reproduced evidence, recovery and setup defects are repaired within the existing architecture. Historical saved reports remain inspectable; replay with an unavailable historical interpreter must still report incomplete rather than silently substitute current code.

Not checked: A fresh 7,200-transaction experiment, real partner data, live browser-to-server integration, physical download interaction, power-loss durability, or model-byte equality across runtimes. Existing dated model results are not reclassified as a new experiment. MIT and third-party notices are preserved.
