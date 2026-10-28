# Contributing

Start with the [README](README.md) and [architecture](docs/ARCHITECTURE.md).
For a bug report, include the source revision, Python/OS versions, command,
expected result and actual output. A small synthetic timeline is usually the
most useful reproduction; remove credentials and customer/payment data before
sharing logs or examples. Use private vulnerability reporting when available
for security-sensitive reports.

Keep pull requests focused. First reproduce the failure with the relevant cutoff,
delivery sequence and archived artifacts. Add a small failing regression, fix the
shared cause, and run the affected checks. Obtain a fresh independent review for
substantive behavior or workflow changes after verification. When available, use
Ponytail and the relevant Superpowers skills for diagnosis, tests, verification and
review; existing user authorization governs routine work.

The standard local checks are:

```bash
make check
.venv/bin/python -m ruff format --check riskreplay tests scripts
.venv/bin/python scripts/browser_qa.py --baseline-evidence
```

The browser fixture requires Chrome but no trained demo or server. Storage,
artifact or replay changes can also use a bounded repeatability check:

```bash
.venv/bin/python -m riskreplay verify-reproducibility --transactions 80 --output var/verification/audit-reproducibility.json
```

Release verification and [CI](.github/workflows/ci.yml) additionally run `make pages`,
`make reproduce` (two 600-transaction workflows), and
`.venv/bin/python scripts/browser_qa.py` against the generated saved inspector.
Run those broader checks when the change affects the published demo or model
protocol; do not imply that a small smoke established full-size model quality.
Workflow changes should also pass actionlint.

Describe what changed, how it was checked and anything you could not run. For
documentation-only edits, check commands, relative links and factual claims;
there is no need to train models or regenerate reports just to change prose.
Make intentional model or data-contract changes explicit in the patch and review.

Preserve original records, provenance and unknown outcomes. Keep development
cases separate from frozen evaluations; use new holdouts when the evaluation
protocol changes. The [independent replay protocol](docs/EXTERNAL_EVALUATION.md)
is available for contributors who want to test the tool on a new investigation.

Parquet bundles and archived artifacts are authoritative; SQLite indexes and
latest pointers are conveniences. Preserve cutoff-visible correction chains,
typed incomplete results, null unknown counterfactuals and evidence denominators.
Do not repair unavailable historical code by substituting the current interpreter.
Keep saved reports immutable, stage writes before publication, and retain conflicting
content instead of overwriting it. Use disposable data for interruption tests and
leave retained investigations untouched.

Environment repair must preserve shared package caches. Copy package bytes to a
temporary sibling before replacing a destination, and verify installed versions
against the lock instead of relying only on a previous setup marker. Keep setup
regressions independent of the user's actual cache.

Original code uses the [MIT licence](LICENSE). Preserve third-party notices
listed in [NOTICE](NOTICE).
