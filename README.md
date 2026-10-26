# Job Evaluator

Author: Sayandip Bagchi. Version lives in `.claude-plugin/plugin.json`.

A recruiter-side plugin that reads a job description and each resume in full and recommends **Shortlist**, **Review** or **Not recommended**. Each recommendation comes with a 0 to 100 match score, a confidence level, and a quoted resume line behind every point. A human confirms every recommendation. Nothing is auto-rejected.

Two skills, four commands, four subagents and one MCP server:

**`jd-to-rubric`** turns a JD into a frozen rubric before any resume is opened. Hard gates are kept apart from weighted signals totalling 100, weak signals such as institution are capped at 5, and the result is hashed so every candidate is scored against the same criteria.

**`job-evaluator`** parses, scans and redacts each resume, then scores it against the frozen rubric blind to identity. It computes score, confidence and band deterministically and runs two independent reviewers before returning.

## Layout

```
job-evaluator/
├── .claude-plugin/plugin.json      name, version, author. Single source of truth
├── .mcp.json                       wires the job-sources MCP server
├── commands/
│   ├── evaluate.md                 /job-evaluator:evaluate    one JD × one resume → scorecard
│   ├── shortlist.md                /job-evaluator:shortlist   one JD × N resumes → bands + sheet
│   ├── rubric.md                   /job-evaluator:rubric      JD → frozen rubric, no scoring
│   └── explain.md                  /job-evaluator:explain     audit one score, no re-score
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

Unlike humanise, this package ships a `.mcp.json` and real subagents in `agents/`: the ATS harness and the per-candidate context isolation need them.

## Design, in three layers

**Context engineering.** The step that scores a person sees the least: the frozen rubric and one redacted resume. It never sees the raw JD, identity, or other candidates. Each resume in a batch gets a fresh subagent context. See `skills/job-evaluator/references/context-contract.md`.

**Guardrails.** Thirteen guardrails (GR1 to GR13) span input, process, output, action and compliance, and they fail closed: a guardrail that could not run sends the candidate to Review and is reported as NOT RUN. See `references/guardrails.md`.

**Evals.** Three layers: a structural validator, 24 behavioural cases across five groups, and a quantitative suite. The quantitative suite covers fairness invariance, determinism, order invariance and injection handling, plus live band-agreement and calibration gates. See `evals/README.md`.

## Install

Drop the `.plugin` file into Claude and accept it, or add the containing folder as a plugin marketplace and install `job-evaluator` from it. Once the repo is pushed:

```
/plugin install job-evaluator --marketplace SayandipBagchi/<repo>
```

For the MCP server:

```bash
pip install -r mcp/job-sources/requirements.txt
export GREENHOUSE_API_KEY=...            # optional, for ATS pulls
export JOB_EVALUATOR_LOG_DIR=~/job-evaluator-logs   # optional, default ~/.job-evaluator/logs
```

The server runs on the MCP Python SDK 1.x or 2.x.

## Use

Claude picks the skill up from phrases like "evaluate this resume against the JD", "shortlist these candidates" or "score this applicant". Commands name it directly. Before scoring, set the role's jurisdictions in `tenants/<org>/roles/<role>.json` (copy `templates/role-config.md`), or answer when asked.

| ATS | Status |
| --- | --- |
| Greenhouse Harvest | Read: jobs, applicants, resumes. Write: private notes, confirm-gated |
| Lever | Stub; planned for P3 |
| Anything else | Attach resumes or an export |

The connected Indeed connector covers JD lookup only. Its resume tool returns the signed-in user's own resume, not applicants.

## Checking the package

```bash
python3 scripts/validate_skill.py              # layer A
claude plugin eval . --allow-tools Read Glob Grep   # layer B
python3 -m pytest mcp/job-sources/tests        # layer C, 80 unit and integration tests
python3 scripts/run_quant_evals.py             # layer C, quantitative
```

## Not legal advice

The compliance behaviour (EU AI Act, NYC Local Law 144, UK GDPR Article 22, India's DPDP Act) is product design meant to support a deploying organisation's own compliance work. It does not make a deployment compliant by itself.
