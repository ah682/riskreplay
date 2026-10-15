# Model protocol

`riskreplay.modeling.train_models` consumes observed transaction rows with historical
features supplied by the replay engine. It does not read generator oracle files.
Known oracle columns and observed approval labels attached to declined transactions
are rejected. Features are allowlisted; missing blocklist/flag/outage state raises
an error. Unavailable velocity uses the explicit numeric sentinel `-1`.

Decision times determine fixed windows over 60%, 20%, and 20% of their time span.
The train/validation/test windows have inclusive starts and exclusive next starts;
the last test decision is included. Tied timestamps remain in the same window and
transaction IDs provide stable ordering within a timestamp. Training labels must
be available by one microsecond before validation starts. Validation labels must
be available by one microsecond before test starts. Labels at each cutoff are
inclusive. All cutoff values and the frozen test IDs/hash are exported.

Observed outcome history is resolved independently at the training, validation,
and evaluation cutoffs. A future correction cannot remove an earlier mature target
or rewrite the label used for an earlier fit. History records stay outside the
feature matrix; unavailable corrections stay outside fitted-row hashes. The
training audit records the exact target and availability used for each fitted row.
Exported test rows omit outcome histories and hide unavailable target values.

A real logistic regression uses a training-fitted median imputer and standard
scaler. A real CPU histogram gradient-boosted classifier fits two recorded parameter
configurations on the training set. The first chronological half of validation
selects by average precision, then Brier score, then declared grid order. Internal
random validation/early stopping is disabled. A sigmoid calibrator fits only the
second validation half with a frozen base estimator when that half contains at
least 30 mature labels and at least three examples of each class. Insufficient
calibration evidence is reported explicitly. There is no final refit on validation
or test. Model artifacts record actual estimators, calibration, seed, software
versions, feature/code hashes and the exact fit/tuning/calibration transaction IDs.
Calibration uses explicit two-fold prediction with `FrozenEstimator`; tests verify
that its base estimator's state and predictions do not change. Metadata includes
class counts, prediction folds and whether the base estimator was refitted. The
larger verification profile exercises calibration with 309 rows but only three
fraud positives; this verifies execution, not strong statistical calibration evidence.

The test evaluation cutoff defaults to the last decision time. An explicitly later
cutoff can reveal delayed observed labels without changing model training. Future
labels are hidden in exported test rows and counted as immature. Never-observed
outcomes and declined transactions remain separate. A missing label is never zero.

## Metric interpretation

- `average_precision` is non-interpolated recall-increment weighted precision.
  `pr_auc` separately reports trapezoidal precision–recall area; these are not
  interchangeable. Both are null when there are no mature observed positives.
- Brier score and ten fixed reliability bins describe probability calibration on
  mature observed labels. Bin counts, observed fraud counts, mean predictions and
  observed rates are exported. A fixed rules baseline uses declared heuristic
  scores and is clearly identified as uncalibrated.
- Review capacity is `floor(0.10 × all test transactions)`. Score ties break by
  decision time then transaction ID. Precision divides observed selected fraud by
  selected mature observed transactions. Recall divides observed selected fraud
  by all mature observed fraud. Unknown selected outcomes have their own count:
  full-population review precision is not identified when they exist.
- Cohort metrics retain the same global review allocation. Capacity is not silently
  reallocated separately to each cohort.
- Amount weights assume nonnegative amounts in one nominal currency and include
  only mature observed transactions. Transaction amount does not equal realized
  loss. The measures do not estimate recovered revenue or prevented fraud loss.
- Observational selection by the original policy limits all metrics. Declined
  outcomes under approval remain unknown. Synthetic data is not real merchant
  validation, and this pipeline does not run a synthetic oracle estimator.

## Artifact trust and reproducibility

Artifacts live at `models/<sha256>.joblib` below the supplied artifact root. Writes
are exclusive; an existing path with different bytes is an error. Predictions
verify bytes every time, even when deserialization is cached. A hash establishes
integrity, not trust: joblib may execute Python, so only this application's locally
trained artifacts are supported. Do not import arbitrary external joblib files.

Native numerical work runs with one thread and explicit seeds. Exact repeatability
is tested for the pinned environment; identical bytes across different numerical
libraries, Python releases or CPU architectures are not promised. The final test
mutation test changes test features and labels and verifies that fitted artifacts
and tuning remain identical.

## API references checked

The locally available pinned runtime is scikit-learn 1.8.0, NumPy 2.4.6,
SciPy 1.17.1 and joblib 1.5.3. On 2026-10-14 all 28 locked distributions were
downloaded from PyPI into an empty environment and the project wheel was built,
installed and executed. The documented bootstrap can also reuse matching installed
public distributions in an isolated environment.
The installed signatures and official version-specific documentation were checked:

- [Histogram gradient boosting](https://scikit-learn.org/1.8/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html)
- [Calibration and FrozenEstimator](https://scikit-learn.org/1.8/modules/generated/sklearn.calibration.CalibratedClassifierCV.html)
- [Average precision definition](https://scikit-learn.org/1.8/modules/generated/sklearn.metrics.average_precision_score.html)

Model-specific verification: `.venv/bin/python -m pytest tests/test_modeling.py -q`.
Executed results belong in `docs/VERIFICATION.md` after integration, rather than
being inferred from these protocol descriptions.
