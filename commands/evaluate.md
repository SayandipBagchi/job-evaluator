---
description: Score one resume against a JD and return an evidence-backed scorecard
argument-hint: "[JD url, file or text] [resume file or text] [optional: role config id]"
---

Use the `job-evaluator` skill to evaluate one resume against the JD below.

Follow its full workflow in order: build and freeze the rubric with `jd-to-rubric` and show it, then parse, scan and redact the resume, score it against the frozen rubric with a quote for every point, compute score, confidence and band, run the evidence-integrity and fairness-audit checks, and return the scorecard in the output contract's order.

If the JD, the resume, or the candidates' jurisdiction is missing, ask for it before scoring. Never default a jurisdiction.

The result is a recommendation for a human reviewer. Do not state a hiring decision.

Inputs:

$ARGUMENTS
