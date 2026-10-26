# Verification

## Local maintenance checks — 26 October 2026, v0.1.1

Executed in a fresh checkout using Python 3.12.3, uv 0.11.28 and Node 24.16.0.
`make setup` created an owned `.venv` by copying 28 exact-version public
packages available locally; it verified pinned versions and imports. This run
does not establish a fresh network download or independent user onboarding.

| Command/check | Observed result |
| --- | --- |
| `make check` | 246 tests passed in 51.40s; Ruff and Python compilation passed. |
| `.venv/bin/python -m ruff format --check riskreplay tests scripts` | All 34 files formatted. |
| `node --check riskreplay/static/app.js` | Passed. |
| `make pages` | Default 1,800-transaction replay and seven-file static export completed; 1,798 matched, one deliberate mismatch and one incomplete decision. |
| `make reproduce` | Two fresh 600-transaction workflows: equal datasets, semantic reports and both fitted model artifacts. |
| `uv build --offline` with an owned cache containing the pinned backend | Built wheel and source archive with Hatchling 1.27.0. |
| Installed wheel, isolated Python from `/tmp`: `python -I -m riskreplay --data-dir … demo` | Full 1,800-transaction demo completed outside source; source/wheel semantic hash and run identity agree. |
| `uv pip check` in the wheel environment | All 29 installed distributions compatible. |
| Archive inspection | README/URLs in metadata, static assets in wheel, source test/build instructions included; no generated data, caches or virtual environment. |

Default run: `rr-762d521240360bc6`; dataset
`5af04809e8506f384562b1af7f5a090469e9b86c7dbc83a2aab34422edb87e69`;
semantic hash `c618bffc9b74e3488e31d038a7ea86523cd66e787e0a233e2968140f8fdad25d`.
The default test window contains 359 transactions, 321 mature observed labels
and 26 observed fraud labels. The 600-row reproducibility semantic hash is
`859fd2a390c71c822076e1e63c4023da4e26552f4b82e6a6b9cb6b40d9bf5543`.
These identities describe this pinned runtime, not cross-machine model equality.
Jobs overlapped; elapsed times are not isolated performance measurements.

## Historical hosted and browser evidence

[Release checks](https://github.com/ah682/riskreplay/actions/runs/38818317655)
and [Pages deployment](https://github.com/ah682/riskreplay/actions/runs/38818317662)
succeeded for source `4fd3e1b` on 15 October. The
[dated record](VERIFICATION_2026-10-16.md) and
[release evidence](evidence/pages-release.json) preserve the earlier suite,
7,200-row model audit and browser component/static-site measurements.
Those browser/model audits were not rerun in this maintenance pass; their counts
must not be presented as fresh checks of v0.1.1. No new hosted CI run or GitHub
Release is claimed by this local record.

## Remaining gates

Project-wide licensing awaits the owner decision. Live browser-to-local-API
integration, physical pointer/native download behavior, cross-runtime model-byte
identity and independent onboarding remain unverified in this pass. No permitted
merchant dataset, external incident investigation or productivity trial was run.
Use the [independent challenge protocol](EXTERNAL_EVALUATION.md) for future work
and retain all [product limitations](LIMITATIONS.md).
