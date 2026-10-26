# Evals

Three layers. A suite that cannot run is reported as NOT RUN, never as passed.

| Layer | What | Run | Needs |
| --- | --- | --- | --- |
| A | Structural validator | `python3 scripts/validate_skill.py` | Python 3.9+ |
| B | 24 behavioural cases, graded by checklist | `claude plugin eval .` | Claude CLI |
| C | Harness unit and stdio integration tests, and the quantitative suite | `python3 -m pytest mcp/job-sources/tests` then `python3 scripts/run_quant_evals.py` | pytest; `python-docx` for one test |

## Layer B cases

Each case folder holds `prompt.md` (frontmatter: name, tags for group, should-fire or should-not-fire, and target skill; runs, max_turns, timeout_seconds) and one `type: llm` judge per criterion (`graders/c1.md`, `c2.md`, ..., so a failure names the exact item) and `graders/skill-fired.md` (`type: tool_used`, `tool: Skill`; `min: 0, max: 0` for a should-not-fire case). There is no `case.yaml`: the CLI reserves it for scaffolds. The folders are generated: edit `evals/cases.json`, then run `python3 scripts/build_eval_cases.py`.

Run with `--allow-tools Read Glob Grep` so the skill can read its references inside the eval sandbox. Filter with `--tag security`, `--tag should-not-fire` and so on.

| Group | Cases | What a pass proves |
| --- | --- | --- |
| core (6) | shortlist, failed gate, low confidence, unverifiable gate, rubric before resume, evidence quoted | The band rules and evidence discipline hold end to end |
| fairness (6) | name swap, pronoun swap, gap, graduation year, institution, photo | Identity and proxies never reach a score or a rationale |
| security (3) | resume injection, keyword stuffing, JD injection | Text inside a document never steers the evaluation |
| boundaries (5) | no hire verdict, title-only JD, candidate mode, bulk pool, unrelated | The skill fires when it should, and only then |
| harness (4) | write-back confirm, ATS unreachable, blocked URL, NYC jurisdiction | Connector failure and compliance paths degrade safely |

## Layer C checks

Deterministic (always run over `evals/fixtures/`):

| ID | Check |
| --- | --- |
| D1 | Mock rubrics are valid and each `jd_hash` matches its JD |
| D2 | Reference scorecards pass `validate_scorecard` against the redacted resume and land in the labelled band and rule |
| D3 | Name, pronoun and graduation-year swaps produce byte-identical redacted text |
| D4 | Five runs give identical scores, confidence and bands |
| D5 | A shuffled batch gives the same band per candidate |
| D6 | Steering content is flagged and absent from the scorer's text |

Live (need model scorecards saved as `evals/results/runs/<run-id>/<jd>/<slot>.json`, one folder per run):

| ID | Metric | Gate |
| --- | --- | --- |
| L1 | Band agreement with labels | ≥ 0.80 |
| L2 | Spearman rank, score vs label band | ≥ 0.70 |
| L3 | Determinism across runs | score sd ≤ 2, band identical |
| L4 | Calibration by confidence level | High ≥ 0.90, Med ≥ 0.75 |

The mock labels are author labels on synthetic data. The PRD's open question on recruiter-labelled pairs decides when L1 to L4 become release gates.
