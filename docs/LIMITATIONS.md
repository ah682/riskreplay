# Limitations

RiskReplay currently evaluates an 80-day synthetic payment simulation. Merchant
accuracy, investigation time and business impact need separate trials with real
records; the [trial protocol](EXTERNAL_EVALUATION.md) describes that work.

## Data and models

- Historical declines leave approval outcomes unknown. The reports therefore do
  not estimate recovered revenue or counterfactual fraud-loss reduction.
- The simulator assumes reviewed transactions eventually fulfill and amounts use
  one nominal currency. Settlement, disputes and chargebacks are simplified.
- Held-out samples are small. Calibration is skipped when validation has too few
  eligible labels. The larger 7,200-transaction profile has 309 calibration labels
  but only three fraud positives, so calibration quality remains uncertain.
- Candidate comparisons before the candidate's training cutoff are retrospective.
  Feature/model/rule traces use a fixed replacement order and are not causal attribution.
- Replay depends on accurate completeness records and retained artifacts. Hashes
  detect changes to recorded bytes but cannot establish whether the source was true.
  Missing list, model, feature or rule history produces an incomplete result.
- Version 1 supports one decision per transaction and a single correction chain.
  Provider mappings and repeat decisions need an explicit import adapter.

## Runtime and storage

The snapshot engine scans history in one process. It has no distributed event
processing, external feature store, streaming backpressure, authentication or
tenant isolation. The API is read-only and binds to loopback by default. SQLite
is a rebuildable local index; Parquet and manifests retain the source history.

Only the current feature/rule interpreters are executable. To reproduce older
code hashes, restore the matching source release and locked runtime. The system
does not import arbitrary historical Python implementations.

Model artifacts use joblib, which can execute Python during loading. Use only
artifacts trained by this application; never place untrusted pickle/joblib files
in its artifact directory. JSONL imports and the API do not accept model uploads.

New runs have checksums for each export. Older runs without an export manifest
retain semantic report checks but lack checksums for their other files.

## Test coverage

The [verification record](VERIFICATION.md) separates dated local, hosted, model
and browser runs. Browser component tests use the UI with captured ASGI responses;
the API and saved-file browser checks were also run separately. A live connection
from the browser to the local server, browser enforcement of response headers,
physical pointer interactions and native downloads still need an integration run.
Pointer automation and screenshot capture timed out during the October audit.

The 26 October local checks reused exact installed dependency versions because
network downloads were unavailable. Model-byte equality has been checked within
the pinned runtime, but not across Python, numerical-library or CPU versions.

## Evaluating real investigations

Use permitted deployment and incident records with original model, rule and
feature artifacts and availability logs. Validate provider normalization and
compare replayed features with independently captured online features. To measure
usefulness, compare investigation time and errors against the team's existing
method on cases selected before either run.
