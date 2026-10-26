# Output contract

## Single candidate scorecard (in the reply)

Order is fixed. The recruiter should be able to stop after the first line.

1. **Headline line:** recommendation, score, confidence. "Shortlist · 82.5 / 100 · confidence High (0.81)".
2. **Why, in two or three sentences**, naming evidence: "Led a co-branded card launch to 180k customers and ran the RBI approval; no evidence of roadmap ownership beyond one product."
3. **Strengths:** up to three, each with its criterion id and a short quote.
4. **Gaps:** up to three, each with its criterion id and either a partial quote or "no evidence".
5. **Screening-call items:** every unverifiable gate and anything over-levelled or flagged.
6. **Flags:** injection findings, parse problems, guardrails NOT RUN.
7. **Footer:** rubric hash (first 12 characters), plugin version, and the line "This is a recommendation to support a human reviewer. It is not a hiring decision."

The full per-criterion table follows only when the user asks for detail, or in `/job-evaluator:explain`.

The scorecard JSON shape is `schemas/scorecard.schema.json`.

## Batch shortlist

**In the reply:** counts per band, then the Shortlist in rank order with one evidence line each, then how many are in Review and the most common reason, then the caveats block.

**As a Sheets artifact** (the Sheets artifact type when listed; an .xlsx only if asked):

| Tab | Columns |
| --- | --- |
| Shortlist | Rank, Candidate, Profile link, Score, Confidence, Top evidence, Gaps, Screening-call items |
| Review | Same, plus Reason for review |
| Not recommended | Same, plus Reason, plus a Human decision column left blank |
| Method & Rubric | Rubric table, weights, hash, thresholds, counts per band, caveats |

Never include email or phone columns.

## Caveats block (every batch)

- **Coverage:** "N resumes evaluated; M could not be parsed and are in Review."
- **Method:** full resume read against a frozen rubric, blind to identity.
- **Unverified gates:** list each and how many candidates it affects.
- **Guardrails NOT RUN:** each one, or "none".
- **Reviewers:** evidence-integrity and fairness-audit results, or NOT RUN.
- **Not a decision:** the recommendation line.

## Wording

- Use "Shortlist", "Review", "Not recommended". Never "reject", "hire", "do not hire", "unqualified" as a label for a candidate. A gate can be "failed"; a person is never "a fail".
- Every Not recommended line carries the words "recommendation; a human confirms", in the reply and in the sheet.
- Rationales name evidence ("ran the RBI approval for a card launch"), never restate a number ("scored 4 on s3").
- No praise or apology wrappers.
