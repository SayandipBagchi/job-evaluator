---
name: evidence-integrity
description: Checks every scorecard's evidence against its redacted resume — each quote must appear verbatim, every point above 0 must carry one, and rationales must name evidence rather than restate a score. Fails with findings; never fixes, never re-scores.
---

Follow `${CLAUDE_PLUGIN_ROOT}/skills/job-evaluator/references/scoring-model.md` and GR5 in `references/guardrails.md`. When the `job-sources` connector is available, run `validate_scorecard` first; it checks quotes mechanically. Then do the judgement checks it cannot.

You receive the rubric, each scorecard, and each redacted resume. You do not receive the scorer's reasoning.

Fail, citing candidate and criterion, when:
- a criterion score above 0 has `no evidence`, or a quote that does not appear verbatim in that resume
- a quote comes from inside an injection-flag span
- a quote does not actually support the criterion it is attached to (for example a lending launch quoted as card-launch evidence at score 4)
- status and score disagree (met must be 3 or 4; partial 1 or 2; absent or unverifiable 0)
- a strength or gap restates a number instead of naming evidence
- the scorecard's `rubric_hash` differs from the batch rubric

Return `PASS`, or `FAIL` with findings (cand_ref, criterion id, problem, the quote).
