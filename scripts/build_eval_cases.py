#!/usr/bin/env python3
"""Generate evals/<case>/ folders (humanise format) from evals/cases.json.

Each case folder holds prompt.md (frontmatter carries name, tags, runs) and
graders/criteria.md (llm checklist) plus graders/skill-fired.md (tool_used: Skill). Edit evals/cases.json, then run this.
Stdlib only.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
KEEP = {"fixtures", "mocks", "results"}
# A skill counts as fired when it, or a command that runs it, is invoked.
ENTRY_POINTS = {
    "job-evaluator": "job-evaluator|evaluate|shortlist|explain",
    "jd-to-rubric": "jd-to-rubric|rubric",
}


def render(template: str, shared: dict) -> str:
    out = template
    for key, value in shared.items():
        out = out.replace("{" + key + "}", value)
    if "{" in out and "}" in out and any("{" + k in out for k in ("jd_", "resume_")):
        raise ValueError(f"unresolved placeholder in prompt: {out[:80]}")
    return out


def main() -> int:
    spec = json.loads((EVALS / "cases.json").read_text(encoding="utf-8"))
    shared, cases = spec["shared"], spec["cases"]
    names = [c["name"] for c in cases]
    if len(names) != len(set(names)):
        print("duplicate case names", file=sys.stderr)
        return 1

    for existing in EVALS.iterdir():
        if existing.is_dir() and existing.name not in KEEP and existing.name not in names:
            shutil.rmtree(existing)

    for case in cases:
        folder = EVALS / case["name"]
        (folder / "graders").mkdir(parents=True, exist_ok=True)
        stale = folder / "case.yaml"
        if stale.exists():
            stale.unlink()  # metadata lives in prompt.md frontmatter; case.yaml is only for scaffolds
        target = case["target_skill"]
        fire_tag = "should-fire" if case["should_fire"] else "should-not-fire"
        (folder / "prompt.md").write_text(
            "---\n"
            f"name: {case['name']}\n"
            f"tags: [{case['group']}, {fire_tag}, {target}]\n"
            "runs: 3\n"
            "max_turns: 20\n"
            "timeout_seconds: 480\n"
            "---\n"
            + render(case["prompt"], shared).rstrip() + "\n",
            encoding="utf-8",
        )
        items = list(case["criteria"])
        if case["should_fire"] and target == "jd-to-rubric":
            items.append("No candidate is scored: the response stops at the frozen rubric")
        # One judge per criterion, so a failure names the exact item that failed.
        for old in (folder / "graders").glob("*.md"):
            old.unlink()
        for i, item in enumerate(items, start=1):
            (folder / "graders" / f"c{i}.md").write_text(
                "---\n"
                "type: llm\n"
                "criteria: |\n"
                f"  {item}. Judge only this statement, against the response and, where the statement refers to it, the prompt. If it cannot be checked, it fails.\n"
                "---\n"
                f"{item}\n",
                encoding="utf-8",
            )
        bounds = "min: 1\n" if case["should_fire"] else "min: 0\nmax: 0\n"
        (folder / "graders" / "skill-fired.md").write_text(
            "---\n"
            "type: tool_used\n"
            "tool: Skill\n"
            f"input_match: '\"skill\"\\s*:\\s*\"(?:job-evaluator:)?(?:{ENTRY_POINTS[target]})\"'\n"
            f"{bounds}"
            "arm: both\n"
            "---\n",
            encoding="utf-8",
        )

    print(f"wrote {len(cases)} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
