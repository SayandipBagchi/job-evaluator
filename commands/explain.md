---
description: Explain an existing score criterion by criterion, without re-scoring
argument-hint: "[candidate ref or name] [optional: criterion id]"
---

Use the `job-evaluator` skill in explain mode. Do not re-score and do not change the rubric.

For the candidate named below, show the full per-criterion table from their scorecard: criterion, weight, score, status, quoted evidence or "no evidence", and points. Then show how the score, confidence and band were computed, naming the band rule that matched.

If the user disagrees with a criterion score, say what evidence would change it and that a human can override the recommendation. Record an override only if the user asks, through the audit log's human decision field.

If no scorecard for this candidate exists in this conversation or the audit log, say so and offer to run `/job-evaluator:evaluate`.

Candidate:

$ARGUMENTS
