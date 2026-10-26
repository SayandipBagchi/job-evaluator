# Rubric schema

The rubric is the only description of the role the scorer ever sees. It must carry everything needed to score, and nothing about any candidate. The machine-readable version is `skills/job-evaluator/schemas/rubric.schema.json`.

```json
{
  "rubric_version": "1",
  "role_title": "Senior Product Manager, Payments",
  "jd_source": "https://boards.greenhouse.io/example/jobs/123",
  "jd_hash": "sha256 of the normalised JD text",
  "weighting_note": "Stakeholder-led role: cross-functional delivery outweighs technical depth.",
  "gates": [
    {
      "id": "g1",
      "requirement": "Right to work in India",
      "jd_phrase": "Must be eligible to work in India",
      "verifiable_from_resume": false
    }
  ],
  "signals": [
    {
      "id": "s1",
      "criterion": "Shipped payments or card products end to end",
      "weight": 30,
      "evidence_full": "Owned launch of a card, wallet or payments product to live customers",
      "evidence_partial": "Contributed to a payments launch without owning it",
      "jd_phrase": "Own the roadmap for our card issuing platform",
      "weak_signal": false
    }
  ],
  "dropped": [
    {
      "jd_phrase": "young, energetic team",
      "reason": "Age proxy; not a capability. Not scored."
    }
  ],
  "open_questions": [
    "Is the 3-day office requirement firm for this role?"
  ]
}
```

## Rules the validator and the scorer enforce

- `signals[].weight` sums to exactly 100.
- Every signal with `weak_signal: true` together carries at most 5.
- No gate or signal names a protected attribute or proxy (see the fairness rules).
- `id` values are unique and stable; scorecards refer to them.
- The hash is SHA-256 over the canonical JSON: keys sorted, separators `,` and `:`, UTF-8, with the `rubric_hash` field itself absent.
