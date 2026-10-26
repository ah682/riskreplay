# References

These sources informed the temporal evaluation and storage design. The linked
projects' code, data and published scores are separate from RiskReplay's synthetic
experiments. References were initially consulted on 13 October 2026 and the
starting references and pinned scikit-learn APIs were checked again on 15 October.

| Source | Relevance |
| --- | --- |
| [Fraud Detection Handbook: baseline modeling](https://fraud-detection-handbook.github.io/fraud-detection-handbook/Chapter_3_GettingStarted/BaselineModeling.html) | Chronological evaluation and delayed feedback. RiskReplay checks each label's actual availability. |
| [Feedzai ARMS](https://github.com/feedzai/research-arms) | A reference for evaluating rule priorities and configurations. RiskReplay has not run or reproduced its optimization experiments. |
| [Stripe webhooks](https://docs.stripe.com/webhooks) | Event identities and delivery ordering motivate deduplication and an explicit ingestion sequence. |
| [SEON custom rules and parameters](https://docs.seon.io/knowledge-base/transactions-scoring/custom-rules-and-parameters) | Rule versioning and velocity aggregates. |
| [Tecton / Taktile feature and logic deployment](https://taktile.com/articles/tecton-x-taktile-unlocking-faster-risk-modeling-with-rapid-feature-and-logic-deployment) | Inspecting feature and policy changes together. |
| [scikit-learn 1.8 HistGradientBoostingClassifier](https://scikit-learn.org/1.8/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html) | The CPU boosted classifier, explicit seeds and early-stopping configuration. |
| [Apache Arrow 20: Parquet](https://arrow.apache.org/docs/20.0/python/parquet.html) | Persisting event and decision bundles. |
| [Python 3.12 sqlite3](https://docs.python.org/3.12/library/sqlite3.html) | The rebuildable local query index. |

Python and package versions are recorded in `requirements.lock`. See
[verification](VERIFICATION.md) for setup, build and installed-wheel results,
and [NOTICE](../NOTICE) for third-party terms.
