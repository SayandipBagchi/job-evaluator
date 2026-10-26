---
description: Rank a batch of resumes against one JD into Shortlist, Review and Not recommended
argument-hint: "[JD url, file, text or ATS job id] [resume files, or 'ats'] [optional: role config id]"
---

Use the `job-evaluator` skill in batch mode for the JD and resumes below.

Freeze the rubric once with `jd-to-rubric` and show it before any scoring. Score each resume in its own fresh context through the `resume-scorer` subagent, passing only the rubric, its hash and one redacted resume. Stop the batch if any scorecard returns a different rubric hash.

If the input is `ats` or an ATS job id, pull applicants and resumes with the `job-sources` connector, read-only.

If the pool is larger than about 200, recommend running `jd-applicant-screen` first and offer to evaluate its top N instead.

Return the counts per band, the ranked Shortlist with one evidence line each, the main reasons for Review, and the caveats block in the reply. Build the full rows as a Sheets artifact with Shortlist, Review, Not recommended and Method & Rubric tabs. Never include email or phone columns.

Inputs:

$ARGUMENTS
