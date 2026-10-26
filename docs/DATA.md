# Data contract and provenance

## Events: schema version 1

Every JSONL line contains exactly an `Event` constructor record:

| Field | Meaning |
| --- | --- |
| `event_id` | Nonempty stable string identity for one fact/version |
| `transaction_id` | Transaction string; nullable for global state events |
| `event_type` | `transaction`, `blocklist`, `flag`, `outage`, `checkpoint`, `outcome` |
| `event_time` | When the fact happened/became effective, timezone-aware ISO8601 |
| `available_at` | When this delivery became available to the decision system |
| `delivery_seq` | Globally unique positive integer per delivery, stable across exports |
| `payload` | Type-specific JSON object; frozen internally |
| `payload_hash` | SHA256 of canonical payload JSON |
| `source` | Nonempty source identifier |
| `supersedes` | Previous event ID for a correction, otherwise null |
| `schema_version` | Integer 1 |

Availability cannot precede event time. Duplicate `event_id` deliveries must retain
source, type, transaction, occurrence time, payload hash and predecessor; only
ingestion time and delivery sequence may differ. A changed payload must use a new
identity and explicit supersession. Corrections require a known earlier delivery,
retain type and transaction identity, and cannot create ambiguous branches.

Payloads:

- `transaction`: `account_id` string, finite nonnegative `amount`. The simulator also
  includes country/cohort/device risk and logging eligibility metadata; only the six
  declared features enter modeling. Amounts share one nominal currency.
- `blocklist`: `account_id`, boolean `blocked`.
- `flag`: `account_id`, boolean `flagged`.
- `outage`: `feature: "velocity"`, boolean `active`.
- `checkpoint`: `scope: "blocklist" | "flags" | "velocity"`, boolean `complete`.
  A complete checkpoint attests to coverage from that event time; it cannot
  restore missing earlier facts. Initial simulator checkpoints attest
  to known empty state on 2025-01-04. A later incomplete marker invalidates coverage.
  For lists/flags, the first complete marker after the latest incomplete marker
  starts a recovery period; refreshes do not move its start. Each account stays
  incomplete until its active value is strictly later than that recovery marker
  in effective-time/availability/sequence order. A late pre-recovery backfill or
  another account's value cannot repair the missing state. Provenance retains the
  gap, recovery marker and relevant account value.
- `outcome`: integer `label: 0 | 1`, with a separate event time and label availability
  in `available_at`. It must reference a transaction and cannot occur before it.

## Decisions

Each record stores `transaction_id`, `decision_time`, `cutoff_seq`, `policy_hash`,
`original_score` (0–1), `original_action` (`approve`, `review`, `decline`),
`feature_values` (optional archived online values), and `schema_version:1`.
The policy manifest points to exact feature, rule and model manifests. Decision IDs
are unique per transaction in v1; retry/multiple-decision imports need explicit
upstream normalization. A recorded decision must have a transaction visible by
its cutoff. Missing artifacts do not invalidate ingestion; they invalidate complete
reconstruction, which is returned as typed incomplete.

`schema_version` must be integer 1, not a boolean or float. Scores and recorded
features must be finite numeric values, not booleans. `feature_values` is an object
with nonempty string names: an empty object means no captured feature evidence;
zero-valued features are actual evidence and are checked during reproduction.

## Exact temporal semantics

Available facts satisfy both:

```text
event_time <= decision_time
(available_at, delivery_seq) <= (decision_time, cutoff_seq)
```

Timestamp comparison is normalized to UTC microseconds. The cutoff tuple is
inclusive. At a shared ingestion timestamp, the recorded sequence determines the
last visible delivery; timestamps alone never order deliveries. The first eligible
delivery of an event identity contributes. Visible corrections remove predecessors;
entity updates select latest effective time, then availability, then sequence.

Velocity uses `(decision_time - window_seconds, decision_time]`, excludes the
current transaction, and counts distinct transaction facts after deduplication and
visible corrections. The normal feature spec is a 3,600-second window. Experimental
feature versions may specify another positive integer window (not a boolean);
invalid archived feature specifications produce incomplete evaluation. The manifest and explanation make
that difference explicit. No correction/backfill is visible before its ingestion.

Known outage features are velocity -1 and outage 1, with a persisted outage event.
Absent coverage is incomplete, never interpreted as an empty list or zero velocity.
Feature provenance lists exact contributing event IDs, including coverage and
outage records. Timelines retain duplicate deliveries and excluded later facts.

## Generated data and observation

All records come from the project's 80-day sequential generator. It combines fixed named
acceptance cases with seeded account bursts, amount/cohort variation, a policy
shift, delayed transactions, duplicate deliveries, corrections, flags and outages.
Labels arrive independently after the transaction; fraud delays are generally
longer. The normal observed stream contains no outcome events for actual archived
declines. Reviewed transactions are assumed eventually fulfilled in this simulator.

`simulation_oracle/` contains the generator's isolated latent truth. No training,
report, API or replay reads it.
Development acceptance cases are the named `t-*` examples and seed-controlled test
runs; model metrics use only the frozen final chronological window. There are no
partner transactions or downloaded third-party datasets in the release.

`manifest.json` records source, permission, generator/version/seed, schedule,
transformation assumptions, injected record defects and dataset/file hashes.
Parquet files use string UTC timestamps and canonical-JSON payload/feature columns.
The data can be inspected with PyArrow, or the derived `index.sqlite` query tables.
Loading checks file hashes, normalized content identity and manifest record counts.
Provenance must be an object with nonempty string source and permission fields;
its optional reserved `config` member must also be an object.

Run reports have a separate semantic hash and, for new runs, file checksums covering
JSON, CSV and both HTML views. Normal JSON preserves imported text exactly. CSV
prefixes formula-like strings with an apostrophe for spreadsheet safety; this
documented transformation does not alter the original JSON or Parquet records.
New runs are written in a hidden staging directory and published by atomic rename
only after every export and checksum is complete. A failed write is retryable;
an unreadable persisted manifest makes that run unavailable without hiding healthy runs.

For an import from your own simulator, use provenance such as:

```json
{"kind":"owned_synthetic","source":"my local simulator","permission":"owned fixture"}
```
