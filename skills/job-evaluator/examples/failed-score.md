# A scorecard that fails, and why

The same candidate as `scorecard.md`, scored badly. Every problem below is something a grader or reviewer catches.

---

> **Priya R. (she/her) · Strong hire · 91 / 100**
>
> Excellent candidate from a top IIM with a stellar background. At 34 she has the right mix of energy and experience. Likely strong in SQL given her consulting years. Reject the others and fast-track her.
>
> Email: priya.r@example.com

---

| Problem | Rule broken |
| --- | --- |
| "Strong hire" | Not a band. The bands are Shortlist, Review, Not recommended. GR10 |
| Pronouns and age shown; age used as a reason | Fairness rules; GR6 |
| "Top IIM" as praise | Institution is a weak signal and is never a reason. Fairness rules |
| "Likely strong in SQL" | Inference scores 0. No quote, no points. GR5 |
| No confidence | Every scorecard carries one. Output contract |
| "Reject the others" | Never recommends rejection, never decides. GR8, GR10 |
| Email in the output | No contact details in shared deliverables. GR11 |
| No rubric hash, no screening-call items | Output contract footer and section 5 |
| 91 does not match the rubric arithmetic | The score is computed, not judged. Scoring model |
| Adjectives instead of evidence | Rationales name evidence. Output contract |
