# Build state

## Status — 2026-10-15

Static hosting is prepared for the public `ah682/riskreplay` repository. The
portfolio README now describes the ML engineering decisions and measured limits.
`make check` passes 246 tests, lint and compilation; all 34 Python files pass
format checking. `make pages` exports the verified 1,800-transaction run with the
same dataset and semantic hashes recorded below. Hosted deployment is pending.

Six new exporter tests cover report fidelity, synthetic-only publication, source
tampering, missing manifests, unrelated directories and symlink/overlap safety.
Independent review found the missing-manifest case; its regression failed before
the exporter was tightened. The Pages workflow checks and generates the demo
before deployment, with no additional application dependencies.

## Earlier codebase review

The requested codebase re-review and repairs are complete for the available local
checks. All 12 original mandatory acceptance cases pass. The final source passes
240 automated tests in both the working and clean source environments, plus 249
real-browser component assertions. Independent review of the repairs has no
remaining findings. Environment and genuine merchant gates remain explicit below.

## What changed in this review

Eight reproduced defects were fixed: demo/reset ownership, partial report
publication, unreadable-manifest isolation, stale list/flag state after gaps,
missing-state decisions shifting evaluation windows, invalid feature windows,
port configuration breaking unrelated commands, and hidden UI evidence counts.

Every selected decision now stays in its fixed chronological window and coverage/
capacity denominator. Missing features cannot enter fitting or scoring. Reports
retain explicit missing-state reasons and null scores; model and cohort metrics
show their actual scored mature denominator. Label maturity remains separate.
Recovery from a list/flags coverage gap requires explicit subsequent account state.
Report files publish atomically after all exports and checksums are complete.

New regression tests first reproduced the failures. Follow-up review corrected
cohort/split support display, tuning eligibility wording and metric documentation.
All Python files pass the formatter. Changes follow existing module boundaries;
no new product dependencies or broad cosmetic rewrite was introduced.

## Fresh executed evidence

- `make check`: lint/compilation passed; 240 tests passed. Final frozen-source
  suite: 240 passed in 46.51s; clean-source suite: 240 passed in 48.04s.
- Default run `rr-5ac1cc7243268812`: 1,800 transactions, 1,798 matched, one
  intentional mismatch and one intentional missing model; 229 candidate changes.
  Pristine independent online/offline agreement: 1,800/1,800; eight checks pass.
- Working source, clean source and actual installed wheel produce identical
  default semantic reports, datasets and both model files. All 18 installed
  production files match source; 33 earlier report files remain unchanged.
- Clean setup copied 28 exact public dependency pins. The hatchling 1.27.0 wheel
  ran outside source using isolated Python; all 29 distributions are compatible.
- Two fresh 600-transaction reproducibility runs agree on datasets, semantic
  reports and both model files. `make evaluate` preserves decisions and metrics.
- Larger run `rr-78c1bc02dac8ba9b`: 7,200 transactions, 300.98s total, 630
  independent metric assertions, all 1,263 held-out predictions per model checked,
  7,200/7,200 online/offline matches, 4/4 faults detected, zero false alarms and
  no oracle reads. Frozen source did not change during the audit.
- Calibration executed on 309 labels, only three fraud-positive. This verifies
  implementation, not statistical reliability for a merchant.
- Browser: 249/249 assertions across 11 cases at 390/768/1440px, including
  unknown labels, missing state, cohort support, keyboard/focus, responsive layout,
  contrast, safe text and error/timeout/retry behavior. Actual ASGI exports match
  bytes. JavaScript syntax, Ruff, formatting and compilation pass.

Current evidence is under `var/verification/review-2026-10-15/`; its aggregate is
`review-summary.json`. [VERIFICATION](VERIFICATION.md) maps every original
requirement to executed checks and records exact identities and measurements.
Earlier audits remain historical evidence.

## Remaining gates

Fresh uncached PyPI installation was blocked by DNS in this session; exact-pin
offline setup and the built wheel were verified instead. The successful
2026-10-14 PyPI installation remains a separate historical result.

Loopback sockets still cannot bind (`EPERM`). Browser components and actual ASGI
requests pass separately; live browser/HTTP integration, downloads, HTTP deep links
and browser enforcement of server headers remain unverified. Fresh pointer and
screenshot attempts timed out; no fresh screenshot or physical-pointer success
is claimed. The browser audit deliberately retains `fully_verified: false`.

The public repository has been created; source upload and hosted workflow
verification are pending. Genuine merchant validation requires permitted incidents,
original archives, availability logs, independent production feature captures and
measured investigation time against the team's current method. Those inputs were
not supplied. Further external validation depends on those capabilities
or partner inputs; no additional synthetic result can substitute for them.
