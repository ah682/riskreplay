# Changelog

## 0.1.1 — 2026-10-26 (prepared; release publication pending)

- Complete clone/cd setup, contribution guidance and an independent replay
  challenge protocol. No outside challenge or user trial is claimed.
- Replace obsolete build-state claims with one current verification record;
  keep earlier audits dated and distinguish current hosted software checks from
  historical browser/model audits.
- Add README/project URLs to package metadata and source distribution contents
  needed to reproduce tests, setup and static export. No product/API contract change.

Verified locally: 246 tests, Ruff/format/compile/JS checks, default replay and
static export, two-run reproducibility, wheel/source build and isolated installed
wheel demo. See [commands, identities and boundaries](docs/VERIFICATION.md).

No data migration is required. Rebuild generated demos to display the new package
version; old immutable reports retain their original identities. Project-wide
licensing remains a release-publication gate. The ordinary hosted acceptance job
passed at `96b1c869d88f1b838312986db4cb0bbfc4e2babf`; exact run links and scope are
recorded in verification. Later source revisions require their own checks.

## 0.1.0 — initial implementation

Temporal replay, classical model evaluation and the saved synthetic inspector.
Earlier [verification](docs/VERIFICATION_2026-10-16.md) records local and hosted checks.
No GitHub Release publication date is implied by this entry.
