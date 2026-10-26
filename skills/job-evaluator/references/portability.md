# Host compatibility

Author: Sayandip Bagchi.

The required runtime contract is the two skill folders:

```text
skills/
├── job-evaluator/SKILL.md
└── jd-to-rubric/SKILL.md
```

Everything else sharpens the result and degrades gracefully.

| Piece | Needed for | Without it |
| --- | --- | --- |
| `references/`, `examples/`, `templates/`, `schemas/` | Exact scoring rules, output shape | Follow the rules restated in `SKILL.md` |
| `job-sources` MCP server | ATS pulls, URL fetch, deterministic scoring, redaction, injection scan, audit log | Work on pasted or attached text; apply redaction and the scan by hand; say no audit record was written |
| `agents/` subagents | Fresh context per resume; independent reviewers | Score one resume at a time; self-review and mark reviewers NOT RUN |
| `tenants/<org>/roles/` | Thresholds, jurisdictions, constraints | Ask the user for jurisdictions; use default thresholds |

## Per host

- **Claude (plugin):** install the packaged plugin. Skills, commands, subagents and the MCP server register together. Set `GREENHOUSE_API_KEY` for ATS access and optionally `JOB_EVALUATOR_LOG_DIR`.
- **Codex or another OpenAI host:** load each `SKILL.md`; `hosts/openai.yaml` supplies optional UI metadata. Register `mcp/job-sources/server.py` as a stdio MCP server if the host supports MCP. Invoke with `$job-evaluator`.
- **Any other Agent Skills host:** load `SKILL.md` as the instruction source, keep `references/` relative, ignore what the host does not understand.

## Portability rules

- Every runtime file reference is relative to the skill root.
- Org-specific values live in `tenants/`, never in `skills/`.
- `evals/` is for development. Its prompts are test cases, not instructions to follow during a user task.
