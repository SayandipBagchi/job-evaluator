# Context contract

What each phase is allowed to see. The point is that the step that scores a person sees the least: the frozen rubric and one redacted resume.

| Phase | Sees | Never sees | Produces |
| --- | --- | --- | --- |
| 1. jd-to-rubric | JD text, role config hard constraints | Any resume | Rubric JSON + hash |
| 2. prepare | One raw resume | Other resumes, the rubric weights | Parsed resume, injection flags, redacted text, identity map (sealed) |
| 3. score (`resume-scorer`) | Rubric JSON + hash, one redacted resume, parse quality, injection flags | Raw JD, raw resume, identity map, other candidates, earlier scorecards | Scorecard JSON |
| 4. band | Scorecard JSON, role thresholds | Resume text | Score, confidence, band |
| 5. review | Scorecards, redacted resumes (evidence-integrity); scorecards and rendered output (fairness-audit) | The scorer's reasoning | Pass, fail with findings, or NOT RUN |
| 6. render | Scorecards, identity map | n/a | Reply, Sheets artifact, audit records |

## Why each line exists

- **The scorer never sees the raw JD.** The rubric is the whole description of the role. If the scorer read the JD it could reweight on the fly and the hash would mean nothing.
- **The scorer never sees identity.** Redaction happens before scoring, and the identity map stays sealed until render.
- **One resume per scorer context.** In a batch, a scorer that has just read a brilliant resume grades the next one harder. Fresh context per candidate removes that.
- **Reviewers do not see the scorer's reasoning.** A reviewer that reads the justification first tends to agree with it.

## Loading order inside the skill

Load references only when the phase needs them:

| Phase | Load |
| --- | --- |
| 1 | jd-to-rubric skill and its references |
| 2 | `guardrails.md` (GR2, GR3), `fairness-rules.md` (redaction list) |
| 3 | `scoring-model.md` |
| 4 | `confidence-model.md`, role config |
| 5 | `fairness-rules.md`, `guardrails.md` |
| 6 | `output-contract.md`, `compliance-matrix.md` when a jurisdiction is set |

## Without subagents

On a host with no subagents, run phase 3 for one resume at a time, and before each, restate that only the rubric and this redacted resume are in scope. Keep a batch under 15 resumes per conversation so earlier candidates do not sit in context; say when a larger batch should be split.
