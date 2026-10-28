# Runtime Audit Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans and test-driven-development to implement these tasks in order. Root performs the independent integration review and publication.

**Goal:** Correct the five reproduced report, archive and recovery defects without changing the temporal or model protocol.

**Architecture:** Reuse the existing temporal engine for report metadata. Keep unavailable feature evidence out of agreement denominators. Stage file bytes beside their destination, with exclusive publication for immutable artifacts and replacement only for mutable JSON pointers; validate archived settings before interpreting them.

**Tech Stack:** Python 3.12, pathlib/tempfile/os, existing pytest and JavaScript browser harness. No dependency changes.

**Spec:** The five confirmed cases and expected behaviors specified in Tasks 1–5 below, from the runtime audit and root's implementation instructions dated 2026-10-28.

## Global Constraints

- Preserve absent evidence as unknown and preserve conflicting immutable bytes.
- No full model retraining, dependencies, workflows, CONTRIBUTING or publication changes.
- Existing branch `quality/ponytail-audit-2026-10-28`; only explicitly owned files are staged.
- Implementation is already authorized; no additional plan approval or agent delegation.

## Review Focus

- Corrections arriving after a decision must not enter its displayed metadata (Task 1).
- Zero-valued captured features remain evidence; only an empty snapshot is absent (Task 2).
- Competing writers must never replace different immutable bytes (Task 3).
- Boolean/string/nonfinite settings and malformed JSON objects must not produce an action (Task 4).
- Explicit selection can recover without defaults, while implicit selection still reports damaged defaults (Task 5).

### Task 1: Correct incomplete report metadata

Files: `riskreplay/pipeline.py`, `tests/test_runtime_audit.py`.
Interface: `evaluate_run(...)` keeps its report schema; fallback metadata comes from `engine.visible(decision.cutoff)`.

- [x] Add `test_incomplete_report_uses_transaction_version_at_cutoff`, with a 75 → 150 correction before cutoff and a 900 correction after cutoff; assert amount 150 and corrected cohort.
- [x] Run `.venv/bin/python -m pytest tests/test_runtime_audit.py -k transaction_version -q`; expect failure (75 instead of 150).
- [x] Replace oldest-delivery fallback with the visible transaction version.
- [x] Repeat the test; expect pass.

### Task 2: Separate missing archived feature evidence

Files: `riskreplay/pipeline.py`, `riskreplay/static/app.js`, `tests/test_runtime_audit.py`, browser harness if practical, `docs/DATA.md`.
Interface: baselines add `feature_comparisons` and `feature_unavailable`; `feature_agreement` is null with zero comparisons. `n` remains the action denominator. UI uses the new feature denominator with a fallback for older reports.

- [x] Add `test_baseline_feature_agreement_requires_captured_evidence` for absent, mixed and zero-valued captured evidence; assert literal comparison/mismatch counts, null/real agreement and divergent IDs.
- [x] Run `.venv/bin/python -m pytest tests/test_runtime_audit.py -k baseline -q`; expect failures for absent evidence.
- [x] Implement the separate counts and update the rendered feature denominator; document the output fields.
- [x] Repeat the tests and run a controlled real-UI browser assertion for `0 / 0 · Unavailable` and mixed evidence where practical; record any unavailable integration honestly.

### Task 3: Publish immutable artifacts only when complete

Files: `riskreplay/artifacts.py`, `riskreplay/modeling.py`, `tests/test_artifact_recovery.py`, `docs/ARCHITECTURE.md`.
Interface: a small shared byte-publication helper writes a sibling temporary file, then uses an exclusive filesystem operation to publish immutable content. Existing artifact writer return values and conflict exceptions remain unchanged.

- [x] Add interrupted JSON/joblib write/retry tests and identical/conflicting competing-publisher cases.
- [x] Run `.venv/bin/python -m pytest tests/test_artifact_recovery.py -q`; expect interrupted retry failures before implementation.
- [x] Stage complete bytes, publish without replacement, clean temporary files, and preserve checksum/conflict checks.
- [x] Repeat recovery tests; expect pass. Reuse the helper for Task 5 only if that keeps mutable and immutable intent explicit.

### Task 4: Reject malformed archived manifests as incomplete

Files: `riskreplay/artifacts.py`, `riskreplay/policy.py`, `tests/test_runtime_audit.py`.
Interface: invalid artifact references/objects and unsupported interpreter inputs raise `MissingArtifact` or `ContractError`; `evaluate`/`replay` return missing reasons and null score/action.

- [x] Add `test_malformed_archive_returns_incomplete` over invalid reference/object shapes, rule numeric values and fixture-model numeric values.
- [x] Run `.venv/bin/python -m pytest tests/test_runtime_audit.py -k malformed -q`; expect exceptions or fabricated actions.
- [x] Validate only required interpreted fields, using existing typed failure paths; retain valid policy behavior.
- [x] Repeat those tests plus `tests/test_invariants.py` and `tests/test_temporal_recovery.py`; expect pass.

### Task 5: Recover explicit selections and mutable pointer writes

Files: `riskreplay/cli.py`, `riskreplay/storage.py` or the existing pointer call, `tests/test_runtime_audit.py`, `tests/test_artifact_recovery.py`, `docs/ARCHITECTURE.md`.
Interface: fully explicit replay/train or compare/evaluate selection does not require valid `latest.json`; implicit defaults continue to fail actionably. The previous valid pointer remains intact if its replacement write fails.

- [x] Add `test_explicit_dataset_ignores_damaged_latest_pointer` and `test_interrupted_latest_write_preserves_previous_pointer`.
- [x] Run focused tests; expect explicit selection to exit 2 and a failed write to truncate the old pointer.
- [x] Skip damaged optional defaults when arguments already select the needed data/policy; publish mutable JSON by atomic replacement.
- [x] Repeat focused tests and existing CLI/report recovery tests; expect pass.

### Task 6: Verify and hand off

- [x] Run `.venv/bin/python -m pytest -q`, `.venv/bin/python -m ruff check riskreplay tests scripts`, `.venv/bin/python -m compileall -q riskreplay scripts`, and `node --check riskreplay/static/app.js`; expect success.
- [x] Run `.venv/bin/python -m riskreplay verify-reproducibility --transactions 80 --output /tmp/riskreplay-runtime-reproducibility.json`; expect identical semantic/dataset/model hashes or record why a larger small fixture is required.
- [x] Review the owned diff, record red/green evidence and limitations in `/tmp/riskreplay-ponytail-audit.md`, commit only owned files, then send the SHA and evidence to root. No push.

## Execution record

- Task 1: regression failed with amount 75 instead of 150, then passed; later correction remained excluded.
- Task 2: three output cases failed, then passed. Chrome fixture failed absent/mixed denominator checks, then passed all 9 checks. Portable `browser_qa.py --baseline-evidence` passed all 5 checks.
- Task 3: six artifact interruption/publication cases failed, then passed; existing modeling tests also passed (23 total). Publication uses `os.link`, which cannot replace a competing final path.
- Task 4: fourteen malformed archive cases failed, then passed with invariant and recovery coverage (98 total). No catch-all exception suppression added.
- Task 5: interrupted pointer and explicit-selection cases failed, then all 50 focused runtime/artifact/CLI/report-recovery tests passed.
- Ruling: preserve healthy latest-pointer evaluation reuse, but disregard malformed optional pointer data when the dataset and required candidate are explicit; implicit defaults still fail. This keeps existing metric reuse behavior.
- Ruling: root performs the independent final integration review; no nested agents or separate branch were created because root assigned this bounded implementation in the existing audit branch.
- Final verification: 280 tests passed in 40.05s before dependency updates and 43.69s with PyArrow 23.0.1, AnyIO 4.14.2, Starlette 1.3.1 and certifi 2026.10.19. Ruff, Python compilation and both JavaScript syntax checks passed.
- Fresh 80-transaction reproducibility: dataset identity, both fitted artifact byte hashes and semantic reports agreed between two temporary roots in the updated pinned runtime. This is not a cross-runtime byte-identity claim.
- No fresh full-size training, live browser-to-server integration or native download verification was performed by this implementation worker. Root owns the final full-demo publication checks.

## Follow-up: offline setup with shared package-cache files

Root's final `make pages` exposed `SameFileError` after `uv pip sync`: installed files and offline reuse sources can share an inode. In-place copies can also modify another environment or cached version when their contents differ. This follow-up is authorized to refresh the full 1,800-transaction demo after the setup repair.

Files: `scripts/setup.py`, `tests/test_setup.py`, this plan appendix. Root subsequently authorized format-only changes to the seven earlier runtime files rejected by the newly required CI format check: `riskreplay/cli.py`, `riskreplay/pipeline.py`, `riskreplay/policy.py`, `scripts/browser_qa.py`, `scripts/verify_browser.py`, `tests/test_artifact_recovery.py`, `tests/test_runtime_audit.py`.

- [x] Add real temporary hard-link cases for package-tree files, top-level files and the Ruff launcher, covering identical cache links and different source content; verify source/cache bytes remain intact.
- [x] Add an interrupted-copy case that preserves the old destination and propagates the failure, plus marker cases proving exact installed versions are checked before trusting a matching lock marker.
- [x] Run `.venv/bin/python -m pytest tests/test_setup.py -q` and observe the original copy/marker failures.
- [x] Copy into sibling temporary files and replace destination directory entries, retaining offline discovery and post-install version/import checks. Validate installed versions before the marker fast path.
- [x] Rerun setup regressions, `make setup`, `make pages`, the complete pytest/static checks, and both installed-Chrome modes of `scripts/browser_qa.py` against the refreshed demo.
- [x] Commit only the owned repair and authorized formatting paths; send the sixth finding, exact verification and source-hash scope to root for independent review/publication.

Follow-up outcomes:

- All nine setup regressions failed against the original implementation, then passed. Actual temporary venv interpreters check installed metadata; file-copy tests use real hard links. Only the unrelated scientific import smoke test is substituted in those package fixtures.
- `make setup` reused all 28 pinned distributions and passed real runtime imports. `make pages` then succeeded, including the repeated setup fast path. After authorized formatting changed `policy.py`'s archived rules hash, the demo was generated again from the final source: 1,800 transactions, run `rr-c5ae292e4c488950`.
- Final `make check`: all 289 tests passed in 41.07s, plus Ruff and Python compilation. Whole-tree `ruff format --check` passed for all 37 Python files; both JavaScript syntax checks and `git diff --check` passed.
- Final installed-Chrome checks passed 19/19 at 1440px and 19/19 at 500px against that fresh run, plus 5/5 baseline-evidence checks at 768px.
- Two fresh 80-transaction workflows were repeated after formatting: dataset identity, both model byte hashes and semantic hash `cffed450bb8a094ed8236e012698d2462953403444cf6467c2bf2462b2cb986f` agreed within the current pinned runtime.
- Source-hash scope: setup changes are outside archived interpreter hashes. Formatting changed only `policy.py` among the feature/rules/model/online hash inputs; its final SHA-256 is `d8cd5794422a4d312ca0f1d664e9517805166f32e98a1f0970c25caf972ab20e`. Historical interpreter mismatches remain explicit. Root owns independent final review and publication.
