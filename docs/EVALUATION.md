# Evaluation protocol

## Reproduction and comparison

`make demo` runs the full workflow; `make evaluate` re-evaluates the most recent
persisted dataset and candidate. `riskreplay compare TRANSACTION --policy-a HASH
--candidate HASH` evaluates arbitrary archived versions against identical original
available information. No label is an input feature.

Three baselines expose distinct historical failure modes:

1. `available`: event-time and availability/sequence cutoffs, identity deduplication.
2. `event_time_only`: correct event-time filtering and deduplication, but retrospective
   access to later ingestion, corrections and backfills. Explicitly hindsight.
3. `current_state`: latest lists/flags/outage/corrections, historical velocity window.
   Deliberately naive hindsight replay.

The report persists action/feature agreement numerators, denominators and IDs of
feature-divergent transactions. Recorded score corruption
is measured separately from action/feature mismatch. Complete pristine originals
are checked before injecting one score defect and one missing model reference.
The saved run retains those defects so all three reproduction states are inspectable.

Changed candidate actions include artifact differences, selected rule traces, and
a first consequential stage under fixed feature→model→rule replacement order.
This diagnostic attribution is order-dependent; interactions are not a causal
explanation or economic effect. A candidate evaluated before its fitted cutoff is
clearly retrospective. Held-out quality claims concern only the frozen test window.

## Model pipeline

Features: amount, historical velocity count/sum, blocklist flag, risk flag, known
outage indicator. Logging uses a labeled deterministic fixture scorer; evaluated
logistic/HistGradientBoosting models are trained on the CPU.

Actual split boundaries are 60/20/20 percent of the complete selected decision-time
span, keeping ties together. Missing historical state never removes a decision
before those boundaries are fixed. Each split retains its total, label counts,
missing-state count and IDs; missing-state test rows have null scores. Only training
rows with complete features and labels available immediately before validation may fit the
base estimators. Preprocessing fits only that training subset. Two predefined
boosted configurations tune on the earlier validation half. Sigmoid calibration
uses the later validation half when it has at least 30 eligible mature labels and 3 per class;
otherwise it is explicitly skipped. Validation labels must be available before
final test starts. No refit uses the test window. The generator's optional calendar
suggestions are not used as split metadata; exact executed cutoffs and row IDs are
recorded in `evaluation.splits` and `training_audit`.

Outcome corrections are resolved as of each split's own cutoff. A later label
correction cannot change an earlier fitting population or target. Tests append
future corrections, change earlier corrections, and mutate test-only outcomes to
verify both invariance and the changes that should occur. Histories stay outside
features and exported test rows. Sigmoid calibration uses two-fold prediction with
a frozen base estimator; its state and raw predictions are independently checked.

At evaluation time, distinguish mature observed labels, immature labels, historical
declines, and other unobserved outcomes. Missing historical state is an orthogonal
coverage measure. A missing label is never zero. Model and cohort `metric_n` records
the mature scored population, which may be smaller than the mature-label count.
Metrics include:

- Average precision (non-interpolated) and PR-AUC (trapezoidal), explicitly distinguished.
- Brier score and 10 fixed reliability bins with counts and observed fraud rates.
- Fixed 10% review capacity uses all held-out decisions as its denominator,
  including missing-state decisions. Slots are allocated only to scoreable rows;
  unavailable features never receive fabricated scores. Precision uses selected
  mature scored labels; recall uses mature scored fraud positives. Selected
  unknown outcomes are reported. Precision for the full selected population is
  unidentified when labels are missing.
- If the entire fixed test period lacks features, all decisions remain in that
  period, no review slots are filled, and model metrics are unavailable.
- Domestic/cross-border cohorts using the same global capacity allocation.
- Amount-weighted observed capture ratios with raw sums; one nominal currency,
  no recovery/net-loss assumption and no economic causal interpretation.

Content-addressed joblib files preserve fitted estimators, fit IDs, seeds, selected
parameters, code/dependency/schema hashes. Tests mutate final test data and maturity
without changing model bytes; repeat fits produce identical artifacts in the lock.

## Integrity and repeatability

The persisted audit looks for unavailable/future input records, outcome-as-feature
leakage, late corrections used retrospectively and inflated/duplicate velocity.
Four known faults are injected into copied evidence; original complete snapshots
are negative controls. Reports retain all case findings and raw TP/FN/FP/TN counts.
Separate probes intentionally propose a future label and an invalid time split,
which must raise. This small injected experiment does not establish a real-world
detection rate.

`make reproduce` runs two complete 600-transaction workflows in fresh temporary
roots, comparing complete semantic reports, decision outputs, metric outputs,
dataset hashes and model hashes. Only run ID, creation timestamp and performance
measurements are excluded as nonsemantic metadata. `var/verification/reproducibility.json`
persists the result. The automated suite repeats two 320-transaction workflows too.
Extended verification also executed two full 1,800-transaction runs and compared
them with a fresh source setup and a wheel installed into a clean PyPI environment;
see `var/verification/reproducibility-full.json` and the verification document.

`.venv/bin/python scripts/verify_models.py --seed 17 --transactions 7200` runs a
predeclared larger synthetic profile. It independently recomputes metrics, denominators,
cohorts, reliability bins and capacity allocation without the application's metric
functions; verifies saved estimator predictions and artifact hashes; and records
whether any oracle file was read. This profile exercises fitted calibration but
has only three positive calibration labels, so it does not establish reliable
merchant probability estimates. It does not replace the smaller default profile
or select a favorable seed.

The report's throughput/latency measures one warm serial original+candidate
comparison pass, including feature building, scoring and staged attribution. It
excludes generation, training, timeline rendering and exports. Hardware and sample
count are attached; timings describe that local run. Recorded features
come from the independent `OnlineReference` implementation, which consumes deliveries
in availability/sequence order and maintains live state without calling `TemporalEngine`.
The replay engine independently reconstructs all original snapshots. Raw recorded
feature vectors are preserved in Parquet; the report includes the matched denominator
and any divergent IDs.

The [Handbook and ARMS](REFERENCES.md) informed the baseline design.
Measured results and commands are in [Verification](VERIFICATION.md).
