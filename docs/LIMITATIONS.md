# Limits and release gates

The local demonstration is an engineering/evaluation artifact, not a production
fraud decision service. Its measured scores describe one owned simulation and a
selection-biased observed-label population.

- No real merchant transactions, incident, deployment, payment-provider connection,
  partner feedback, business ROI or investigation-time improvement was validated.
- Declines do not identify outcomes under approval. Missing outcomes remain unknown;
  no revenue recovery or counterfactual fraud-loss reduction is estimated.
- The simulator assumes reviews eventually fulfill and amounts use one nominal
  currency. It simplifies settlement, disputes, label uncertainty and chargebacks.
- Model discrimination/calibration rely on modest held-out sample sizes. Calibration
  may be skipped when validation evidence is too small; this is visible in reports.
  The larger 7,200-transaction verification profile fits calibration with 309 labels
  but only three fraud positives; successful execution is not statistical validation.
- Pre-test candidate comparisons are retrospective diagnostics. They cannot establish
  that a future-trained candidate could have been deployed then.
- Historical state requires truthful completeness attestations and retained records.
  Hashes detect alteration, not a malicious or incorrect source. Missing list/model/
  feature/rule history is incomplete, never guessed.
- Only the current feature/rule interpreter versions are executable. Archived code
  hashes reject changed implementations; restore the corresponding source release
  and locked runtime to reproduce older versions. No arbitrary code importer exists.
- Trusted local joblib model artifacts are executable serialization. Do not place
  untrusted downloaded pickle/joblib files in the artifact directory. Normal JSONL
  ingestion and the API do not upload or deserialize arbitrary model files.
- The transparent in-process snapshot engine scans history and has no distributed
  event processing, external feature store, streaming backpressure, auth/tenancy or
  production archival retention guarantees. SQLite is only a derived local index.
- v1 supports one recorded decision per transaction and one linear correction chain.
  Real provider mappings and repeat-decision semantics require an explicit adapter.
- The API is read-only and loopback-only by default. ASGI routes and saved-file
  browser components were checked separately. Live browser-to-local-server
  integration remains a separate gate.
- Hosted release checks and Pages deployment succeeded for `4fd3e1b` on
  15 October 2026; see the dated links in [Verification](VERIFICATION.md).
  This is historical hosted evidence, not a hosted run for every later revision.
  The 26 October local environment reused exact installed public dependency pins;
  fresh network downloads were unavailable. Cross-runtime model-byte identity
  remains unverified.
- Browser component checks use the real UI and actual captured ASGI responses.
  They do not exercise a live HTTP connection, browser downloads or server response
  headers in the browser. Saved-file browser evidence and API byte/header checks
  are recorded separately. No browser/HTTP integration success is inferred from them.
- In the October browser audit, pointer automation and screenshot capture timed out. Browser component
  assertions use DOM interactions and real keyboard events; they do not establish
  successful physical pointer interaction or a fresh visual screenshot review.
- Earlier saved runs without export manifests retain semantic report verification
  but lack file checksums for their other exports. New runs include both checks.

Before claiming real merchant usefulness: obtain permitted genuine deployment and
incident records with original model/rule/feature artifacts and availability logs;
validate provider normalization; reconcile with independently captured online
features; compare investigation time against the team's existing method with
predeclared cases and measurements. Partner data and permission are required.
