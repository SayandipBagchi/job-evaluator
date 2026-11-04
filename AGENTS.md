# job-evaluator: agent instructions

Recruiter-side resume evaluation. Two skills, loaded from `skills/`:

- `skills/jd-to-rubric/SKILL.md`: turn a job description into a frozen, hashed screening rubric. Always runs first.
- `skills/job-evaluator/SKILL.md`: score resumes against that rubric and recommend Shortlist, Review or Not recommended, with quoted evidence and a confidence level. A human makes every decision.

Optional MCP server (stdio): `python3 mcp/job-sources/server.py`, after `pip install -r mcp/job-sources/requirements.txt`. Without it, both skills work on pasted or attached text in the degraded mode their SKILL.md files describe.

Subagent prompts in `agents/` and slash commands in `commands/` are Claude Code plugin pieces; other hosts can read them as plain instructions. Host notes are in `skills/job-evaluator/references/portability.md`.

Tests: `pip install -r mcp/job-sources/requirements-dev.txt && python3 -m pytest mcp/job-sources/tests`.
