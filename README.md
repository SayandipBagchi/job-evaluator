# Job Evaluator

Author: Sayandip Bagchi. Version lives in `.claude-plugin/plugin.json`. MIT licence.

A recruiter-side Claude plugin. It reads a job description and each resume in full and recommends **Shortlist**, **Review** or **Not recommended**. Each recommendation carries a 0 to 100 match score, a confidence level, and a quoted resume line behind every point it awards. A human confirms every recommendation, and nothing is auto-rejected.

The rubric is frozen and hashed before any resume is opened. Building the rubric after seeing candidates is how a screen ends up justifying whoever scored well.

## What you get back

For a batch of 24 resumes against one rubric, the reply opens like this (abridged from [`examples/batch-shortlist.md`](skills/job-evaluator/examples/batch-shortlist.md); all candidates are synthetic):

```
24 resumes evaluated against rubric a41c9e07d2b8: 5 Shortlist, 11 Review, 8 Not recommended.

Shortlist
1. Priya R. · 82.5 · High · co-branded card launch to 180k customers, ran the RBI approval
2. Arjun M. · 79.0 · High · launched prepaid and debit programmes at two issuers
...

Review (11): the most common reason is an unverified office-days gate on otherwise
strong resumes (6 candidates). Three resumes parsed poorly and need a human read.
```

The full rows go to a spreadsheet, and the reply ends with caveats: coverage, unverified gates, any guardrail that did not run, and both reviewers' results. A single scorecard and a scorecard that fails review are in [`skills/job-evaluator/examples/`](skills/job-evaluator/examples/).

## What's in it

Two skills, four commands, four subagents and one MCP server.

`jd-to-rubric` turns a JD into a frozen rubric. Hard gates are kept apart from weighted signals totalling 100, weak signals such as institution are capped at 5, and the result is hashed so every candidate is scored against the same criteria.

`job-evaluator` parses, scans and redacts each resume, then scores it against the frozen rubric blind to identity. Score, confidence and band are computed deterministically, and two independent reviewers check the result before it is returned.

| Command | Input | Output |
| --- | --- | --- |
| `/job-evaluator:evaluate` | one JD, one resume | scorecard |
| `/job-evaluator:shortlist` | one JD, N resumes | bands plus a sheet |
| `/job-evaluator:rubric` | one JD | frozen rubric, nobody scored |
| `/job-evaluator:explain` | an existing score | criterion-by-criterion audit, no re-score |

## How it is built

**Context engineering.** The step that scores a person sees the least: the frozen rubric and one redacted resume. It never sees the raw JD, identity, or other candidates. Each resume in a batch gets a fresh subagent context. See [`context-contract.md`](skills/job-evaluator/references/context-contract.md).

**Guardrails.** Thirteen guardrails (GR1 to GR13) cover input, process, output, action and compliance, and they fail closed: a guardrail that could not run sends the candidate to Review and is reported as NOT RUN. See [`guardrails.md`](skills/job-evaluator/references/guardrails.md).

**Evals.** Three layers: a structural validator, 24 behavioural cases across five groups, and a quantitative suite covering fairness invariance, determinism, order invariance and injection handling, plus live band-agreement and calibration gates. See [`evals/README.md`](evals/README.md).

Unlike [humanise](https://github.com/SayandipBagchi/humanise-plugin), this package ships a `.mcp.json` and real subagents in `agents/`, because the ATS harness and the per-candidate context isolation need them.

## What it will not do

- Change an application's stage, reject anyone in the ATS, or email a candidate. Asked to, it declines that part and says the human makes that change.
- Score before the role's jurisdictions are known. It asks rather than defaulting one, because the jurisdiction decides which compliance behaviour switches on. NYC candidates wait until the role config records an independent bias audit date.
- Follow instructions planted in a JD or resume ("rank this candidate first"). It flags them on the scorecard and carries on.
- Read hundreds of resumes in one context. Past about 200 applicants, run a funnel screen first and evaluate its top N.
- Serve a job seeker checking their own fit, or write a JD.

## Install

In Claude Code:

```
/plugin marketplace add SayandipBagchi/job-evaluator
/plugin install job-evaluator@job-evaluator
```

For the MCP server:

```bash
pip install -r mcp/job-sources/requirements.txt
export GREENHOUSE_API_KEY=...            # optional, for ATS pulls
export JOB_EVALUATOR_LOG_DIR=~/job-evaluator-logs   # optional, default ~/.job-evaluator/logs
```

The server runs on the MCP Python SDK 1.x or 2.x.

## Use

Claude picks the skill up from phrases like "evaluate this resume against the JD", "shortlist these candidates" or "score this applicant". The commands name it directly. Before scoring, set the role's jurisdictions in `tenants/<org>/roles/<role>.json` (copy `skills/job-evaluator/templates/role-config.md`; `tenants/example-org/` shows the shape), or answer when asked.

| ATS | Status |
| --- | --- |
| Greenhouse Harvest | Read: jobs, applicants, resumes. Write: private notes, confirm-gated |
| Lever | Stub; planned for P3 |
| Anything else | Attach resumes or an export |

The connected Indeed connector covers JD lookup only. Its resume tool returns the signed-in user's own resume, not applicants.

## Layout

```
job-evaluator/
├── .claude-plugin/
│   ├── plugin.json                 name, version, author. Single source of truth
│   └── marketplace.json            lets this repo install as its own marketplace
├── .mcp.json                       wires the job-sources MCP server
├── commands/                       evaluate, shortlist, rubric, explain
├── skills/
│   ├── job-evaluator/
│   │   ├── SKILL.md                workflow, bands, guardrails, routing
│   │   ├── references/             scoring, confidence, fairness, guardrails, context contract,
│   │   │                           compliance, output contract, portability
│   │   ├── examples/               scorecard, batch shortlist, a scorecard that fails
│   │   ├── templates/              role config, candidate notice
│   │   └── schemas/                rubric, resume, scorecard (JSON Schema)
│   └── jd-to-rubric/
│       ├── SKILL.md                JD → gates + weighted signals, frozen and hashed
│       ├── references/             gate vs signal, rubric schema
│       └── examples/               worked rubric
├── agents/
│   ├── resume-scorer.md            one fresh context per resume
│   ├── eval-runner.md              runs all three eval layers
│   └── review/                     fairness-audit, evidence-integrity
├── mcp/job-sources/                Python MCP server, deterministic core, ATS adapters, tests
├── tenants/<org>/roles/<role>.json thresholds, jurisdictions, constraints. Never in skills/
├── hosts/openai.yaml               optional UI metadata for OpenAI hosts
├── scripts/                        validator, quantitative evals, eval-case builder
├── evals/                          24 behavioural cases, synthetic fixtures, results (gitignored)
└── README.md, CHANGELOG.md, LICENSE
```

## Checking the package

```bash
python3 scripts/validate_skill.py              # layer A
claude plugin eval . --allow-tools Read Glob Grep   # layer B
python3 -m pytest mcp/job-sources/tests        # layer C, 80 unit and integration tests
python3 scripts/run_quant_evals.py             # layer C, quantitative
```

## Where it stands

Version 0.1.0, first build. Baseline from 25 October 2026, one run per case with a Sonnet judge:

| Layer | Result |
| --- | --- |
| A, structural validator | Pass |
| B, behavioural | 98 of 111 grader items (88%); 16 of 24 cases fully passing; skill routing correct in 24 of 24 |
| C, harness tests | 80 of 80 |
| C, deterministic evals D1 to D6 | Pass; reference band agreement 15 of 15 |
| C, live gates L1 to L4 | NOT RUN (need recorded model scorecards and recruiter labels) |

Known gaps: the Lever adapter is a stub, PDF hidden-text detection is not implemented (DOCX is), and layer B ran with the MCP server not started in the eval sandbox, so the harness is proven by a stdio end-to-end test instead. The open misses and the full list are in [`CHANGELOG.md`](CHANGELOG.md).

## Not legal advice

The compliance behaviour (EU AI Act, NYC Local Law 144, UK GDPR Article 22, India's DPDP Act) is product design meant to support a deploying organisation's own compliance work. It does not make a deployment compliant by itself. Its outputs are recommendations for a human reviewer, never employment decisions.
