# References and dependency verification

Initially consulted on 2026-10-13; the five starting references and pinned
scikit-learn 1.8 API documentation were reopened on 2026-10-15. No third-party transaction data, training weights, source
code, or reference implementation was copied into this release. The owned generator
and all measured results are synthetic. References inform comparison protocols;
we do not claim to have rerun ARMS or reproduced the Handbook's published results.

| Primary source | Applied idea and boundary |
| --- | --- |
| [Fraud Detection Handbook baseline modeling](https://fraud-detection-handbook.github.io/fraud-detection-handbook/Chapter_3_GettingStarted/BaselineModeling.html) | Chronological evaluation and delayed feedback; RiskReplay checks actual label availability rather than assuming every label arrives after a fixed delay. Its published scores and data are not our benchmarks. |
| [Handbook source license](https://github.com/Fraud-Detection-Handbook/fraud-detection-handbook/blob/main/LICENSE) | Upstream license is retained upstream; no code/data was imported or redistributed. |
| [Feedzai ARMS official repository](https://github.com/feedzai/research-arms) | Rules-priority/configuration evaluation is a baseline reference. The repository exposes a binary, separate license, and synthetic examples; none were run, copied, or bundled. RiskReplay does not implement or benchmark the ARMS optimization algorithms. |
| [Stripe webhook documentation](https://docs.stripe.com/webhooks) | Delivery order and event identity cannot be inferred from occurrence timestamps. We retain deliveries, deduplicate event identities, and use an explicit ingestion sequence. No Stripe connection is configured. |
| [SEON custom rules and parameters](https://docs.seon.io/knowledge-base/transactions-scoring/custom-rules-and-parameters) | Versioned action rules and velocity aggregate semantics. Our fixed local rules are independent, not SEON exports. |
| [Tecton / Taktile article](https://taktile.com/articles/tecton-x-taktile-unlocking-faster-risk-modeling-with-rapid-feature-and-logic-deployment) | Feature and policy iteration motivates inspectable version differences. No Taktile/Tecton integration or performance comparison is claimed. |
| [scikit-learn 1.8 HistGradientBoostingClassifier](https://scikit-learn.org/1.8/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html) | Genuine CPU boosted classifier, explicit numeric schema, deterministic seed and disabled automatic early stopping. Actual installed signatures and fitted objects are tested. |
| [Apache Arrow 20 Parquet documentation](https://arrow.apache.org/docs/20.0/python/parquet.html) | Immutable Parquet event and decision bundles, round-trip verified with installed PyArrow 20.0.0. |
| [Python 3.12 sqlite3](https://docs.python.org/3.12/library/sqlite3.html) | SQLite provides the local query index. Parquet and content hashes are authoritative; the SQL index is rebuildable. |

The selected environment pins Python 3.12 and all runtime/test distributions in
`requirements.lock`. The environment initially blocked network installs; setup reused
28 exact-version installed public Python distributions, copied to an isolated local
virtual environment without modifying their source environments. No sandbox bypass
was used. On 2026-10-14 the extended audit downloaded all 28 pins from PyPI without a
package cache into an empty virtual environment, checked compatibility, built and
installed the declared wheel, and reproduced the default demonstration outside the
source tree. That historical check remains valid for its date. On 2026-10-15 a fresh PyPI
installation failed at DNS resolution. The new review instead verified clean offline
setup from the same 28 exact pins, built a new wheel using cached hatchling 1.27.0,
checked all 29 installed distributions, and compared full default runs across the
working source, clean source and isolated installed wheel.
