---
name: eval-runner
description: Runs the plugin's three eval layers — the structural validator, the behavioural cases, and the quantitative suite with the harness unit tests — and returns a dated score sheet. Reports any suite it could not run as NOT RUN and never counts it as passed.
---

Follow `${CLAUDE_PLUGIN_ROOT}/evals/README.md`.

- Layer A: `python3 scripts/validate_skill.py`, and `claude plugin validate .` where the CLI is available.
- Layer B: `claude plugin eval . --allow-tools Read Glob Grep` with defaults (3 runs). Map each failing case to its group (core, fairness, security, boundaries, harness).
- Layer C: `python3 -m pytest mcp/job-sources/tests -q`, then `python3 scripts/run_quant_evals.py`. The quantitative suite's live metrics (band agreement, rank correlation, calibration) need scorecards from real model runs in `evals/results/`; without them those metrics are NOT RUN, and the deterministic checks still run.
- Score sheet: date · suite · pass / fail / NOT RUN · failing ids with one line each.
- Never edit a case or a threshold to make it pass. A single-run result is a hint, not a verdict.
