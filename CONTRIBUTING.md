# Contributing

Start with the [README](README.md) and [architecture](docs/ARCHITECTURE.md).
For a bug report, include the source revision, Python/OS versions, command,
expected result and actual output. A small synthetic timeline is usually the
most useful reproduction; remove credentials and customer/payment data before
sharing logs or examples. Use private vulnerability reporting when available
for security-sensitive reports.

Keep pull requests focused. Add a regression case for a behavior fix, then run:

```bash
make check
.venv/bin/python -m ruff format --check riskreplay tests scripts
make pages
make reproduce
```

Describe what changed, how it was checked and anything you could not run.
For documentation edits, check commands and relative links. Discuss broad
model or data-contract changes before implementing them.

Preserve original records, provenance and unknown outcomes. Keep development
cases separate from frozen evaluations; use new holdouts when the evaluation
protocol changes. The [independent replay protocol](docs/EXTERNAL_EVALUATION.md)
is available for contributors who want to test the tool on a new investigation.

Original code uses the [MIT licence](LICENSE). Preserve third-party notices
listed in [NOTICE](NOTICE).
