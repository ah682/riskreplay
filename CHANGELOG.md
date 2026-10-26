# Changelog

## 0.1.1 — 2026-10-26

- Add complete setup instructions, contribution guidance and a protocol for
  independent replay trials.
- Consolidate the build status and keep earlier browser and model results in
  dated verification records.
- Add README/project URLs to package metadata and source distribution contents
  needed to reproduce tests, setup and static export.

Verified locally: 246 tests, Ruff/format/compile/JS checks, default replay and
static export, two-run reproducibility, wheel/source build and isolated installed
wheel demo. See the [verification record](docs/VERIFICATION.md).

No data migration is required. Rebuild generated demos to display the new package
version; old immutable reports retain their original identities. The hosted
acceptance job passed at `96b1c869d88f1b838312986db4cb0bbfc4e2babf`; run links are
in the verification record. Original code is now licensed under MIT, with
third-party terms in NOTICE.

## 0.1.0 — initial implementation

Temporal replay, classical model evaluation and the saved synthetic inspector.
Earlier [verification](docs/VERIFICATION_2026-10-16.md) records local and hosted checks.
