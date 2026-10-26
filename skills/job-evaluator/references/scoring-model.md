# Scoring model

The deterministic parts of this model are implemented in `mcp/job-sources/job_sources/scoring.py`. When the connector is available, compute the final score and band with `score_and_band` rather than by hand, so the arithmetic is identical across runs.

## Per-criterion scale

| Score | Meaning | Example against "shipped card products end to end" |
| --- | --- | --- |
| 4 | Direct evidence at or above the required level, within the last 5 years | "Led launch of a co-branded credit card to 180k customers (2024)" |
| 3 | Direct evidence slightly below level, or older than 5 years | Same launch, but in 2017; or owned one module of the launch |
| 2 | Adjacent or transferable evidence | Launched a lending product, not a card |
| 1 | Mentioned without demonstrated use | "Familiar with card issuing" |
| 0 | No evidence, or only inference | Nothing on the resume speaks to it |

Rules:

- A score above 0 needs a quoted span from the redacted resume. The quote is short, verbatim, and appears exactly in the text.
- Recency is applied once, as the step from 4 to 3. It is not applied again elsewhere.
- Self-description ("results-driven leader") is not evidence. A described outcome is.
- When two spans support a criterion, quote the strongest one.

## Status

| Status | When |
| --- | --- |
| met | Score 3 or 4 |
| partial | Score 1 or 2 |
| absent | Score 0 and the resume would normally show this if true |
| unverifiable | The resume could not be expected to show it (notice period, right to work) |

An unverifiable signal scores 0 for arithmetic but is reported separately, and it reduces confidence rather than signalling a weak candidate. Signals should rarely be unverifiable; if many are, the rubric is asking the wrong questions of a resume.

## Match score

```
score = sum over signals of  weight × (criterion_score / 4)
```

Weights sum to 100, so the score runs from 0 to 100. Round to one decimal for display. Gates contribute nothing to the score.

## Bands

Thresholds come from the role config; these are the defaults.

| Setting | Default |
| --- | --- |
| `shortlist_min_score` | 75 |
| `review_min_score` | 60 |
| `shortlist_min_confidence` | 0.5 (Med) |
| `low_confidence_below` | 0.5 |
| `parse_quality_min` | 0.6 |

Precedence, first match wins:

1. Any gate `failed` → Not recommended
2. Confidence below `low_confidence_below`, or parse quality below `parse_quality_min` → Review
3. Any gate `unverifiable` and score ≥ `shortlist_min_score` → Review, unless the role config sets `shortlist_on_unverifiable: true`
4. Score ≥ `shortlist_min_score` and confidence ≥ `shortlist_min_confidence` → Shortlist
5. Score ≥ `review_min_score` → Review
6. Otherwise → Not recommended

Rule 2 comes before rule 6 on purpose: a candidate the tool could not read properly is never recommended against.

## Ranking inside a band

Sort by score, then by confidence, then by `cand_ref` for a stable tie order. Never break ties on any identity field.
