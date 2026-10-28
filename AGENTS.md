# Working on RiskReplay

Read [CONTRIBUTING.md](CONTRIBUTING.md), [ARCHITECTURE.md](docs/ARCHITECTURE.md), and [DATA.md](docs/DATA.md). The latest scoped audit is [QUALITY_AUDIT.md](docs/QUALITY_AUDIT.md).

- When available, use Ponytail and relevant Superpowers skills: reproduce the failure, add a small failing regression, fix the shared cause, run relevant checks, and obtain a fresh independent review of substantive behavior or workflow changes. Use existing authorization and review arrangements; do not add approval gates or required agent counts.
- Trace event time, delivery time, sequence and correction ancestry before changing a replay. Only evidence visible at the recorded cutoff may explain the original decision; later outcomes and hindsight must stay separate.
- Preserve explicit incomplete results, null unknown counterfactuals and separate denominators for available evidence. A hash validates bytes, not manifest structure or policy meaning.
- Treat Parquet bundles and archived artifacts as authoritative. Indexes/latest pointers may be rebuilt or bypassed; do not overwrite conflicting immutable content or substitute current code for missing historical interpreters.
- Use existing atomic publication and recovery patterns. Exercise interrupted writes with temporary data, not retained investigations. The API and saved inspector remain read-only.
- Environment setup must not write through hard links into a shared package cache. Stage and replace copied files, and check installed versions against the lock before trusting a setup marker. Use temporary package fixtures for these regressions.
- Run the relevant tests, then `make check` for runtime changes. Add the bounded 80-transaction repeatability command in CONTRIBUTING when replay/storage changes; use `scripts/browser_qa.py --baseline-evidence` for baseline display changes. Broader demo/model publication uses the existing full release checks.
- Docs-only edits need checked links, commands and claims, not retraining. Keep historical experiments dated and distinguish same-runtime reproducibility from cross-runtime byte equality. Hosted CI is a separate observation from local checks.
- Preserve MIT licensing, NOTICE, provenance and data permissions. Do not introduce live payment actions, external data transfer or untrusted model loading as part of a local repair.
