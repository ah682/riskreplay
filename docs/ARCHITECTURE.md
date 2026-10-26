# Architecture

## Flow

`generator → validated deliveries → independent live feature recorder → archived logging decisions → observation boundary
→ Parquet dataset → historical features → CPU training → candidate comparison
→ immutable run reports → saved inspector / read-only API`

The original logging scorer is a deterministic fixture. The candidate uses a
fitted scikit-learn HistGradientBoostingClassifier, evaluated alongside logistic
regression and fixed rules. `policy.score_model` provides the scorer interface.
Provider-specific imports need an adapter and validation against source records.

## Modules

| Module | Responsibility |
| --- | --- |
| `schema.py` | UTC timestamps, immutable normalized Event/Decision records, IDs, timestamps, hashes, duplicate identity, correction chains and outcome references |
| `artifacts.py` | Hash-addressed JSON feature/rule/model/policy manifests; missing/corrupt artifacts are explicit errors |
| `engine.py` | Event-time and availability cutoffs; identity deduplication; supersession; historical checkpoints, lists, flags, outages, velocity; evidence provenance |
| `online.py` | Independent forward-only delivery reference, with live account/register state; records features without calling the historical replay engine |
| `policy.py` | Archived version checks, scorer interface, ordered rules, reproduction states and staged feature/model/rule comparison |
| `generator.py` | Seeded 80-day deliveries and separate oracle; observation filtering follows actual archived declines |
| `modeling.py` | Temporal splits, label gating, train-only preprocessing, validation tuning/calibration, fitted artifacts and held-out metrics |
| `storage.py` | Immutable Parquet manifests/checksums, strict JSONL import, rebuildable SQLite schema v1 |
| `checks.py` | Provenance audit and four labeled injected faults with complete historical negative controls |
| `pipeline.py` | End-to-end orchestration, label support, baselines, performance and run identity |
| `reporting.py` | JSON/CSV/readable HTML plus self-contained interactive inspector; escaping prevents imported content becoming code |
| `web.py`, `static/` | Read-only run inspection, local exports, accessible responsive incident workflow |
| `cli.py` | Demo, replay, compare, import, train, evaluate, reproduce, serve and guarded reset |

## Identity, state and versioning

Canonical JSON uses sorted keys, compact separators, finite numbers and UTF-8.
Payload, normalized dataset, JSON artifact and trained-model hashes are SHA256.
Repeated event deliveries keep independent sequence numbers and ingestion times;
only one eligible identity contributes to features. Corrections are new identities
with an explicit predecessor and cannot branch ambiguously.

Feature and rule manifests pin interpreter implementation IDs and source hashes.
This release does not execute archived arbitrary Python code. If source changes,
old code-hash artifacts produce incomplete until the corresponding historical
release is restored. The locked environment plus archived source preserve the
reproduction path. Trained files include feature schema, fit IDs, code/dependency
versions and seeds. Hash checks detect alteration; they do not establish trust in
an external pickle.

Chronological boundaries use all selected decisions before evidence filtering.
Missing-state rows remain in their windows and coverage/capacity totals, with null
predictions; only complete features enter fitting or scoring. Model and cohort
metrics report their actual scored mature denominator.

Training resolves observed outcome corrections separately at each split's label
cutoff. Outcome history is never a feature and unavailable corrections cannot
change historical fit membership or fitted-row hashes. Exported test targets are
resolved at evaluation time, separately from the immutable training audit.

Run exports are staged in a hidden sibling directory and published atomically
after all files are complete, so an interrupted write can be retried safely.
Each new run has a manifest with checksums for all six report/export files. Run
reuse verifies every file; API reads recompute report semantics and verify the
requested artifact. Evaluation reads metrics from the verified canonical report,
not an unchecked sidecar. Earlier runs without a file manifest retain semantic
report checks but cannot provide export checksum verification.
Run identity includes the presentation asset hash. Updating HTML/CSS/JavaScript
therefore creates a new inspector instead of silently reusing an older saved UI;
the original report files remain immutable.

Parquet bundles are authoritative. SQLite schema v1 (`PRAGMA user_version=1`)
indexes deliveries and decisions for local queries; rebuilding it drops only its
derived tables. No migration of authoritative history is performed. Dataset schema
versions other than 1 fail explicitly. An incompatible schema needs an explicit
future migration, never silent reinterpretation.

## Execution and failure handling

Everything runs on one CPU process with model thread limits. The current state
engine deliberately favors transparent Python reconstruction over a scalable
stream processor. Candidate and original use the same Cutoff. The two hindsight
baselines explicitly relax that information rule.

Missing historical checkpoints, feature code, rules or model artifacts yield
`incomplete`, absent action/score, and reasons. A recorded outage is different:
it is known state, uses the archived -1 velocity sentinel and review fallback.
Present artifacts yielding a different action, score or recorded feature vector
produce `mismatched`. Invalid normalized input is rejected with a field/event or
JSONL line error before persistence.

The API has only GET routes, path validation, no oracle route, no uploads or live
payment writes. Static file and JSON reads are bounded by local saved reports.
Transaction IDs remain data and may contain provider punctuation, Unicode or
slashes; only run IDs and artifact names select filesystem paths.
The inspector supports asynchronous request timeout/retry controls, empty/invalid
runs, partial unavailable-run notices, filtering, pagination, keyboard tabs,
selection, provenance and export. Saved inspectors contain real report data and
need no HTTP server.
