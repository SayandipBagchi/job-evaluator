# Scorecard example

Rubric: the card-issuing Senior PM rubric in `skills/jd-to-rubric/examples/worked-rubric.md`. Candidate is redacted as `cand_7f3a`; the name rejoins at render.

---

**Priya R. · Shortlist · 82.5 / 100 · confidence High (0.80)**

Led a co-branded credit card launch end to end and ran its RBI approval with the risk and compliance teams. Roadmap ownership is shown for one product line only, and there is little evidence of hands-on SQL.

**Strengths**
- s1 Shipped card products: "Led launch of co-branded credit card to 180k customers in 9 months (2024)"
- s3 Regulated launch: "Owned RBI submission and remediation for card programme approval"
- s2 Cross-functional delivery: "Ran weekly launch council across risk, compliance, engineering and partner bank"

**Gaps**
- s4 Roadmap ownership (partial): "Prioritised backlog for rewards module"
- s5 Data fluency: no evidence

**Screening-call items**
- g1 Can work 3 days a week from Bengaluru: not stated on the resume

**Flags:** none

Rubric `a41c9e07d2b8` · job-evaluator 0.1.0 · This is a recommendation to support a human reviewer. It is not a hiring decision.

---

## Arithmetic behind it

| ID | Weight | Score | Status | Points |
| --- | --- | --- | --- | --- |
| s1 | 30 | 4 | met | 30.0 |
| s2 | 25 | 4 | met | 25.0 |
| s3 | 20 | 4 | met | 20.0 |
| s4 | 12 | 2 | partial | 6.0 |
| s5 | 10 | 0 | absent | 0.0 |
| s6 | 3 | 2 | partial | 1.5 |
| | | | **Total** | **82.5** |

Confidence: coverage 1.0, parse 0.95, JD specificity 0.83, gate verifiability 0.0 → 0.40 + 0.2375 + 0.166 + 0 = 0.80 (High). The unverifiable gate would put a candidate at or above 75 into Review under rule 3; here the recruiter config marks g1 as a screening-call gate with `shortlist_on_unverifiable: true`, so it stays Shortlist with the item listed. Without that setting the band is Review.
