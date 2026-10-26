# Confidence model

Confidence answers one question: how much should a recruiter trust this recommendation without reading the resume themselves? It is not a measure of how good the candidate is. A weak candidate with a clear resume gets High confidence.

## Inputs

| Input | Weight | How it is measured | Range |
| --- | --- | --- | --- |
| Evidence coverage | 0.40 | Share of rubric weight whose criteria have a definite status (met, partial or absent), not unverifiable | 0 to 1 |
| Parse quality | 0.25 | From `resume_parse`: text extracted, dates recovered, roles segmented. Image-only resumes score 0 | 0 to 1 |
| JD specificity | 0.20 | Share of signals whose `evidence_full` names something concrete and checkable | 0 to 1 |
| Gate verifiability | 0.15 | Share of gates confirmable from the resume. No gates counts as 1 | 0 to 1 |

```
confidence = 0.40 × coverage + 0.25 × parse_quality + 0.20 × jd_specificity + 0.15 × gate_verifiability
```

Then subtract 0.15 if the injection scan flagged anything, floored at 0. A resume that tries to steer the model is one the recruiter should read.

## Levels

| Level | Value | What the recruiter should do |
| --- | --- | --- |
| High | ≥ 0.75 | Trust the band; skim the evidence |
| Med | 0.50 to 0.75 | Trust the band; read the gaps and screening items |
| Low | < 0.50 | Read the resume. The band is always Review |

## Calibration

The quantitative eval layer checks that the levels mean what they say: on the labelled set, High-confidence bands should match the recruiter label at least 90% of the time and Med at least 75%. If they do not, the weights above are re-fitted and the change is logged in the CHANGELOG. Do not hand-tune a single candidate's confidence.
