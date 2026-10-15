# Owned sequential simulator

`riskreplay.generator.generate(seed=17, n_transactions=1800)` returns `events`,
`oracle`, and `config`. The dataset is generated locally from owned simulator
code; it includes no merchant, cardholder, provider, or third-party dataset.
The generator uses a private Python RNG, a fixed UTC start of Sunday 5 January
2025, and no wall clock or network. Exactly the requested number of distinct
transactions is generated; duplicated deliveries and corrections add event
records, not transactions. At least eight transactions are required for the
fixed acceptance cases.

The 80-day simulation includes repeated account activity and short bursts,
amounts, countries, device observations, list changes and removals, feature
outages, delayed transaction ingestion, correction deliveries, and delayed
outcomes. Stochastic labels depend on amount, device risk, country, and burst
activity, with a modest distribution shift after day 40. This is a designed
learning problem, not a claim that these relationships describe real fraud.
The original review amount threshold changes from 350 to 250 on day 40;
the decline amount threshold remains 900. The actual recording pipeline also
uses archived blocklist and model/rule state.

## Observation and truth boundary

The separate `oracle` list contains one `oracle_label` for every transaction,
including declines. It is simulator ground truth and must stay outside the
ordinary event store, training inputs, API responses, and observed metrics.
Neither normal event payloads nor configuration contain an oracle label or
generation probability. There are no labels in transaction payloads. The
`logging_declined` payload annotation states the original amount-based logging
eligibility; it is not a modeling feature and remains original metadata when a
later correction changes the amount.

Outcome events are initially emitted only when the original amount rule did
not decline the transaction. Before persistence, the recording pipeline calls
`observe_outcomes(events, actual_declined_transaction_ids)` to remove outcomes
for every actual archived decline, including historical blocklist declines.
A reviewed transaction is assumed to be fulfilled. This assumption is explicit
and is not evidence for a real merchant's reviewed population. The observation
filter preserves delivery sequences; resulting gaps are intentional. Missing
outcomes must not be filled with negative labels.

Stochastic positive outcomes become available 3–16.5 days after the transaction;
negative outcomes usually take 1–7.5 days. Delayed ingestion can extend a
negative label's availability to the transaction's own arrival. The fixed
Monday case becomes known on Friday. Labels must be gated by their own
availability time at each training or evaluation cutoff. The suggested split
boundaries are days 40, 60, and 80; day 84 is a suggested observational reporting
cutoff, so part of the final window remains immature.

## Stable delivery semantics

Every event has a canonical SHA-256 payload hash using UTF-8 JSON with sorted
keys and `(',', ':')` separators. The event identity is `event_id`. Duplicate
deliveries preserve type, transaction identity, event time, source, correction
relationship, and payload; they receive a different positive `delivery_seq`
and may have a different availability time. The schedule is sorted by
availability and original insertion index before assigning that global
sequence. Equal timestamps therefore retain a reproducible total order.

Corrections use a new event ID, the original transaction and event time,
`supersedes` pointing to the original event ID, and a complete replacement
payload. Their later arrival must never rewrite an earlier knowledge state.
The three initial complete checkpoints are dated one day before the first
transaction. They declare that the simulator owns the empty initial blocklist,
flag, and velocity history, including the full lookback before early day-zero
decisions. Missing-checkpoint tests
remove this evidence and must produce incomplete reconstructions.

## Fixed acceptance cases

| Transaction | Evidence supplied |
| --- | --- |
| `t-sunday` | Sunday noon, before Tuesday's blocklist addition for `acct-history`. |
| `t-monday` | Monday transaction whose positive outcome arrives Friday noon. |
| `t-tuesday` | Same account after Tuesday's addition, for archived decline observation filtering. |
| `t-duplicate` | Three deliveries of one Sunday 11:50 transaction, including tied arrival timestamps. |
| `t-late` | Sunday 11:55 event arriving Monday noon, after the Sunday decision. |
| `t-correction` | Sunday 11:45 amount 40 corrected to 740 on Wednesday. |
| `t-outage` | Transaction during the day-20 velocity outage. |
| `t-after-outage` | Transaction after the outage is cleared. |

`flag-history-backfill` happened Sunday morning but arrived Thursday.
There is also an outage on day 56, stochastic duplicates and corrections,
and list removals to exercise more than the named fixtures.

The generator checks are in `tests/test_generator.py`. They validate the
production event contract, exact reproducibility, distinct transaction counts,
duplicate identity, late arrivals, corrections, outage recovery, review-policy
change, outcome separation, and preservation of delivery evidence during
observation filtering. Engine-level acceptance tests verify the resulting
reconstructed decisions, rather than inferring correctness from this schedule.
