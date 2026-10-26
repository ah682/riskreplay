# Independent replay challenge protocol

This protocol is ready for an independent evaluator. No trials have been
completed yet.

1. Recruit a data/ML engineer who did not implement the tool or author its cases.
   Agree permission to use inputs and publish anonymized findings before starting.
2. Freeze a source revision and locked runtime. Have the evaluator follow the
   README unaided on a clean machine. Record setup commands, errors, elapsed time
   and any maintainer help. Record a setup failure before offering help.
3. Before showing the implementation, let the evaluator define a previously
   unseen timeline incident: delayed label, correction, missing archived state,
   duplicated delivery, tied cutoff or a combination. They retain expected
   evidence and outcomes separately. Use permitted original records where
   available; label independently authored synthetic inputs explicitly.
4. Freeze input hashes, expected cutoffs, pass/fail rules and review budget before
   running. Do not amend the holdout to fit the tool. Preserve unsupported cases.
5. Ask the evaluator to reconstruct the incident with their normal method and
   with RiskReplay. Balance order across cases if possible. Record wrong/missed
   conclusions, unknown outcomes treated as known, evidence traceability,
   corrections, completion time and assistance. Synthetic ground truth does not
   establish merchant-level model benefit or counterfactual loss reduction.
6. Publish permissioned inputs/annotations or a reproducible redacted synthetic
   equivalent, exact source/runtime/configuration, hashes, commands, outputs and
   all failures. Separate first-attempt results from fixes and subsequent reruns.

Success means the evaluator can explain a previously unseen temporal failure and
trace the conclusion to the original evidence. Record the sample size and how cases were selected; a single successful
investigation is a case study.

Suggested record: evaluator independence/consent, source SHA, runtime/OS, dataset
permission/hash, predeclared expected result, baseline method, commands, assistance,
observed result, errors/unknowns, timings, proposed fixes and publication permission.
