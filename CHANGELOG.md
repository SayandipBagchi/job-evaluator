# Changelog

## Unreleased

- Relicensed from proprietary to MIT; repository made public.

## 0.1.0 (2026-10-25)

First build: P0 (skills, references, schemas, evals) plus the P1 harness (job-sources MCP, Greenhouse read adapter, audit log).

### Added

- `jd-to-rubric` skill: JD to frozen rubric with hard gates, weighted signals totalling 100, a weak-signal cap of 5, dropped and translated JD lines, and a SHA-256 hash.
- `job-evaluator` skill: six-phase workflow (rubric, prepare, score, band, review, return) with six band rules in a fixed precedence order. Low confidence never yields Not recommended, and an unverifiable gate never lowers a score.
- Confidence model from four inputs (evidence coverage, parse quality, JD specificity, gate verifiability), with a penalty for steering content.
- Thirteen guardrails across input, process, output, action and compliance, all failing closed.
- Context contract: per-phase visibility, blind scoring through redaction, one fresh subagent context per resume.
- Compliance matrix for EU AI Act Annex III, NYC Local Law 144, UK GDPR Article 22, India DPDP Act, and other US states.
- Four commands: evaluate, shortlist, rubric, explain.
- Four subagents: resume-scorer, eval-runner, and the fairness-audit and evidence-integrity reviewers.
- `job-sources` MCP server, 19 tools: JD fetch (Greenhouse and Lever public posting APIs first), resume parse with parse quality and DOCX hidden-text detection, injection scan, redaction with a sealed identity store, deterministic score and band, scorecard and wording validators, Greenhouse Harvest adapter, confirm-gated note write-back, append-only audit log with retention pruning, human decision record.
- Evals: structural validator; 24 behavioural cases in five groups generated from `evals/cases.json`; quantitative suite with six deterministic checks and four live gates; 80 harness tests including a stdio end-to-end test against the real MCP SDK; synthetic fixtures of 3 JDs and 15 resumes with reference scorecards and labels.

### Fixed before release (independent review and first live eval runs)

- Injection scan runs on normalised text: zero-width and soft-hyphen characters can no longer split an instruction and reassemble after cleaning.
- Injection is neutralised at sentence level, not line level, so a one-line pasted resume keeps its evidence.
- Instruction patterns require the candidate, applicant or resume as the object, so "rank the top 500 merchants" is no longer flagged. More steering phrasings are covered (`[INST]`, "if you are an LLM", "AI reviewers:", "forget your guidelines").
- Keyword stuffing detected by repeated word pairs and low variety; genuine comma-separated skills lists pass. Hex hashes no longer read as encoded payloads.
- Redaction: name found after title lines (RESUME, Curriculum Vitae), in capitals, with credentials, and at the start of one-line resumes. Contact details are removed before names. Name parts are kept when they belong to an organisation or award (Smith & Wesson, Grace Hopper Fellowship). Labelled fields are matched mid-line. Added S/O, D/O and W/O lines, UK postcodes, handle-only profiles, family phrases, inline education years and more section headings. Pronoun matching ignores all-caps acronyms (SHE Teams, HER).
- A rubric gate missing from a scorecard counts as unverifiable and is reported, instead of silently passing.
- `score_and_band` takes parse quality and injection status from `prepare_resume`, so the scorer cannot set the values that decide its own band.
- Audit log uses an allowlist of fields, refuses emails and phone numbers in any value, requires `resume_hash`, non-empty `jurisdictions` and `guardrails_not_run`, and can prune by retention.
- Skill: degraded mode, so missing references, hash tool or connector lower what the evaluation promises instead of stopping it. Phase 2 uses `prepare_resume`. Caveats never name which personal details were removed. ATS notes need explicit approval of the shown text. NYC candidates prompt for the bias audit date at once. Years of experience are not a rubric criterion.
- Eval cases rebuilt to the `claude plugin eval` format (prompt.md frontmatter, `llm` and `tool_used: Skill` graders); the judge's criteria carry the checklist; the skill-fired grader accepts the plugin's commands.

### Eval baseline (25 Oct 2026, one run per case, Sonnet judge)

| Layer | Result |
| --- | --- |
| A, structural validator | Pass |
| B, behavioural | 98 of 111 grader items (88%); 16 of 24 cases fully passing; skill routing correct in 24 of 24 |
| C, harness tests | 80 of 80 |
| C, deterministic evals D1 to D6 | Pass; reference band agreement 15 of 15 |
| C, live gates L1 to L4 | NOT RUN (need recorded model scorecards and recruiter labels) |

Open layer B misses to work next, each from a single run: rubric-before-resume (the judge sees only the last message, so a rubric shown earlier in the reply is invisible), photo-ignored and gap-neutral (scoring credit drawn from a job title; recency wording), evidence-quoted (absent criteria not always written as "no evidence"), institution-weak-signal (no explicit reason given for not filtering on college tier). Run three times per case before treating any of these as a regression.

### Known gaps

- Lever adapter is a stub.
- In the `claude plugin eval` sandbox used for this release, the plugin's MCP server was not started even with `--allow-real-servers` and `--mocks off`, so layer B ran in degraded mode. The harness is proven by the stdio end-to-end test instead.
- Live eval gates (L1 to L4) are NOT RUN until model scorecards are recorded and recruiter-labelled pairs replace the synthetic labels.
- PDF hidden-text detection is not implemented; DOCX is.
