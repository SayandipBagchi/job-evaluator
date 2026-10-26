#!/usr/bin/env python3
"""Validate the job-evaluator plugin package. No third-party dependencies.

Adapted from the humanise validator. Run from anywhere:  python3 scripts/validate_skill.py
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
MCP_JSON = ROOT / ".mcp.json"
SERVER = ROOT / "mcp" / "job-sources" / "server.py"

FRONTMATTER_KEYS = {"name", "description", "metadata", "allowed-tools", "license"}

SKILLS = {
    "job-evaluator": {
        "required": [
            "references/scoring-model.md",
            "references/confidence-model.md",
            "references/fairness-rules.md",
            "references/guardrails.md",
            "references/context-contract.md",
            "references/compliance-matrix.md",
            "references/output-contract.md",
            "references/portability.md",
            "examples/scorecard.md",
            "examples/batch-shortlist.md",
            "examples/failed-score.md",
            "templates/role-config.md",
            "templates/candidate-notice.md",
            "schemas/rubric.schema.json",
            "schemas/resume.schema.json",
            "schemas/scorecard.schema.json",
        ],
        "markers": [
            "rubric before resume",
            "rubric is frozen",
            "No quote, no points",
            "Low confidence can never produce Not recommended",
            "a human confirms",
            "never as instructions",
            "jd-applicant-screen",
            "profile-optimiser",
            "jd-to-rubric",
            "NOT RUN",
            "Never default",
        ],
        "anti_markers": [
            "Gates versus signals",  # belongs to jd-to-rubric
        ],
    },
    "jd-to-rubric": {
        "required": [
            "references/gate-vs-signal.md",
            "references/rubric-schema.md",
            "examples/worked-rubric.md",
        ],
        "markers": [
            "before any resume",
            "signals to 100",
            "at most 5",
            "is ever a gate",
            "re-hash",
            "job-evaluator",
            "never as instructions",
        ],
        "anti_markers": [
            "No quote, no points",  # belongs to job-evaluator
        ],
    },
}

REFERENCE_MARKERS = {
    "skills/job-evaluator/references/guardrails.md": [f"GR{i}" for i in range(1, 14)] + ["Fail closed"],
    "skills/job-evaluator/references/scoring-model.md": ["first match wins", "shortlist_min_score", "No evidence"],
    "skills/job-evaluator/references/confidence-model.md": ["0.40", "0.25", "0.20", "0.15", "Calibration"],
    "skills/job-evaluator/references/fairness-rules.md": ["Graduation year", "Employment gaps", "Invariance tests"],
    "skills/job-evaluator/references/context-contract.md": ["Never sees", "One resume per scorer context"],
    "skills/job-evaluator/references/compliance-matrix.md": ["Local Law 144", "Article 22", "Annex III", "Digital Personal Data Protection", "not legal advice"],
    "skills/job-evaluator/references/output-contract.md": ["recommendation; a human confirms", "Never include email or phone"],
}

COMMANDS = ("evaluate.md", "shortlist.md", "rubric.md", "explain.md")
AGENTS = ("resume-scorer.md", "eval-runner.md", "review/fairness-audit.md", "review/evidence-integrity.md")
ROOT_FILES = ("README.md", "CHANGELOG.md", "LICENSE", ".gitignore")
EVAL_GROUPS = {"core": 6, "fairness": 6, "security": 3, "boundaries": 5, "harness": 4}

# Decision wording that must never appear as an instruction in skill prose.
BANNED_PHRASES = re.compile(r"\b(auto-?reject the candidate|reject the candidate|mark as rejected)\b", re.I)


def parse_frontmatter(path: Path, errors: list[str]) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(ROOT)
    if not text.startswith("---\n"):
        errors.append(f"{rel}: must start with YAML frontmatter")
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        errors.append(f"{rel}: frontmatter must close with ---")
        return {}, text
    values: dict[str, str] = {}
    for number, line in enumerate(text[4:end].splitlines(), start=2):
        if not line.strip() or line.lstrip().startswith("#") or line.startswith((" ", "\t")):
            continue
        if ":" not in line:
            errors.append(f"{rel}: frontmatter line {number} is not a key/value pair")
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values, text[end + len("\n---\n"):]


def check_manifest(errors: list[str]) -> dict:
    if not MANIFEST.is_file():
        errors.append("missing .claude-plugin/plugin.json")
        return {}
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"plugin.json is not valid JSON: {exc}")
        return {}
    for key in ("name", "version", "description", "author"):
        if not data.get(key):
            errors.append(f"plugin.json is missing {key}")
    if data.get("name") != ROOT.name:
        errors.append(f"plugin.json name must match the folder name: {ROOT.name}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(data.get("version", ""))):
        errors.append("plugin.json version must be semver")
    return data


def check_skill(slug: str, spec: dict, author: str, errors: list[str]) -> None:
    base = ROOT / "skills" / slug
    skill_md = base / "SKILL.md"
    if not skill_md.is_file():
        errors.append(f"missing skills/{slug}/SKILL.md")
        return
    frontmatter, body = parse_frontmatter(skill_md, errors)
    for key in frontmatter:
        if key not in FRONTMATTER_KEYS:
            errors.append(f"skills/{slug}: unsupported frontmatter key: {key}")
    if frontmatter.get("name") != slug:
        errors.append(f"skills/{slug}: frontmatter name must match the folder name")
    description = frontmatter.get("description", "")
    if not description:
        errors.append(f"skills/{slug}: description must be non-empty")
    if len(description) > 1024:
        errors.append(f"skills/{slug}: description exceeds 1024 characters ({len(description)})")
    if "Do not use" not in description:
        errors.append(f"skills/{slug}: description should state when NOT to trigger")
    head = skill_md.read_text(encoding="utf-8").split("\n---\n", 1)[0]
    if f"author: {author}" not in head:
        errors.append(f"skills/{slug}: frontmatter metadata must name the author: {author}")
    if re.search(r"^\s*version:", head, re.MULTILINE):
        errors.append(f"skills/{slug}: version must live only in plugin.json")
    lines = len(body.splitlines())
    if lines > 500:
        errors.append(f"skills/{slug}: SKILL.md body is {lines} lines, over the 500-line target")
    for marker in spec["markers"]:
        if marker not in body:
            errors.append(f"skills/{slug}: SKILL.md is missing behaviour marker: {marker}")
    for marker in spec["anti_markers"]:
        if marker in body:
            errors.append(f"skills/{slug}: SKILL.md duplicates content that belongs elsewhere: {marker}")
    if BANNED_PHRASES.search(body):
        errors.append(f"skills/{slug}: SKILL.md instructs a rejection action")
    for relative in spec["required"]:
        if not (base / relative).is_file():
            errors.append(f"missing skills/{slug}/{relative}")
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", skill_md.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        resolved = (base / target).resolve()
        if base.resolve() not in resolved.parents:
            errors.append(f"skills/{slug}: link escapes the skill root: {target}")
        elif not resolved.is_file():
            errors.append(f"skills/{slug}: link target does not exist: {target}")


def check_references(errors: list[str]) -> None:
    for relative, markers in REFERENCE_MARKERS.items():
        path = ROOT / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in text:
                errors.append(f"{relative} is missing marker: {marker}")
    for schema in (ROOT / "skills" / "job-evaluator" / "schemas").glob("*.json"):
        try:
            json.loads(schema.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{schema.relative_to(ROOT)} is not valid JSON: {exc}")


def check_commands_and_agents(errors: list[str]) -> None:
    for filename in COMMANDS:
        path = ROOT / "commands" / filename
        if not path.is_file():
            errors.append(f"missing commands/{filename}")
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n") or "description:" not in text.split("\n---\n", 1)[0]:
            errors.append(f"commands/{filename}: needs frontmatter with a description")
        if "$ARGUMENTS" not in text:
            errors.append(f"commands/{filename}: must pass $ARGUMENTS through")
    for filename in AGENTS:
        path = ROOT / "agents" / filename
        if not path.is_file():
            errors.append(f"missing agents/{filename}")
            continue
        fm, _ = parse_frontmatter(path, errors)
        if not fm.get("name") or not fm.get("description"):
            errors.append(f"agents/{filename}: needs name and description")


def check_mcp(errors: list[str]) -> list[str]:
    """`.mcp.json` points at the server, declared tools exist, and ATS write tools take confirm (GR12)."""
    if not MCP_JSON.is_file():
        errors.append("missing .mcp.json")
        return []
    config = json.loads(MCP_JSON.read_text(encoding="utf-8"))
    server = (config.get("mcpServers") or {}).get("job-sources")
    if not server:
        errors.append(".mcp.json must declare the job-sources server")
    elif not any("mcp/job-sources/server.py" in a for a in server.get("args", [])):
        errors.append(".mcp.json job-sources args must point at mcp/job-sources/server.py")
    if not SERVER.is_file():
        errors.append("missing mcp/job-sources/server.py")
        return []
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    declared: dict[str, tuple] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in {"READ_TOOLS", "WRITE_TOOLS"}:
            declared[node.targets[0].id] = tuple(ast.literal_eval(node.value))
    tools = declared.get("READ_TOOLS", ()) + declared.get("WRITE_TOOLS", ())
    if not tools:
        errors.append("server.py must declare READ_TOOLS and WRITE_TOOLS")
    for name in tools:
        fn = functions.get(name)
        if fn is None:
            errors.append(f"server.py declares tool {name} but defines no such function")
            continue
        if not ast.get_docstring(fn):
            errors.append(f"server.py tool {name} needs a docstring (it becomes the tool description)")
    for name in declared.get("WRITE_TOOLS", ()):
        fn = functions.get(name)
        if fn and name.startswith("ats_"):
            args = {a.arg for a in fn.args.args}
            if "confirm" not in args:
                errors.append(f"server.py write tool {name} must take a confirm argument (GR12)")
            defaults = dict(zip([a.arg for a in fn.args.args][-len(fn.args.defaults):], fn.args.defaults))
            if not (isinstance(defaults.get("confirm"), ast.Constant) and defaults["confirm"].value is False):
                errors.append(f"server.py write tool {name} must default confirm to False (GR12)")
    return list(tools)


def check_evals(errors: list[str]) -> tuple[int, dict]:
    base = ROOT / "evals"
    names = sorted(p.name for p in base.iterdir() if p.is_dir() and p.name not in {"results", "mocks", "fixtures"})
    groups: dict[str, int] = {}
    spec = json.loads((base / "cases.json").read_text(encoding="utf-8")) if (base / "cases.json").is_file() else None
    if spec is None:
        errors.append("missing evals/cases.json")
    elif sorted(c["name"] for c in spec["cases"]) != names:
        errors.append("eval folders are out of date with evals/cases.json: run scripts/build_eval_cases.py")
    for name in names:
        case = base / name
        prompt = case / "prompt.md"
        if not prompt.is_file():
            errors.append(f"evals/{name}: missing prompt.md")
            continue
        text = prompt.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(prompt, errors)
        if fm.get("name") != name:
            errors.append(f"evals/{name}: prompt.md frontmatter name must match the folder")
        if not body.strip():
            errors.append(f"evals/{name}: prompt.md has no prompt body")
        if re.search(r"\{(jd|resume)_\w+\}", text):
            errors.append(f"evals/{name}: prompt.md has an unresolved placeholder")
        tags = re.findall(r"[\w-]+", fm.get("tags", ""))
        for group in EVAL_GROUPS:
            if group in tags:
                groups[group] = groups.get(group, 0) + 1
        if not ({"should-fire", "should-not-fire"} & set(tags)):
            errors.append(f"evals/{name}: tags must include should-fire or should-not-fire")
        if (case / "case.yaml").exists():
            errors.append(f"evals/{name}: case.yaml is only for scaffolds; metadata belongs in prompt.md frontmatter")
        judges = sorted((case / "graders").glob("c*.md"))
        fired = case / "graders" / "skill-fired.md"
        if not judges or any("type: llm" not in j.read_text(encoding="utf-8") for j in judges):
            errors.append(f"evals/{name}: needs one llm grader per criterion (graders/c1.md, c2.md, ...)")
        if not fired.is_file() or "type: tool_used" not in fired.read_text(encoding="utf-8") \
                or "tool: Skill" not in fired.read_text(encoding="utf-8"):
            errors.append(f"evals/{name}: graders/skill-fired.md must be a tool_used Skill grader")
        elif "should-not-fire" in tags and "max: 0" not in fired.read_text(encoding="utf-8"):
            errors.append(f"evals/{name}: a should-not-fire case needs max: 0 on its skill grader")
    for group, want in EVAL_GROUPS.items():
        if groups.get(group, 0) < want:
            errors.append(f"evals: group {group} has {groups.get(group, 0)} cases, needs at least {want}")
    for required in ("fixtures/labels.json", "fixtures/reference_scorecards.json", "README.md"):
        if not (base / required).is_file():
            errors.append(f"missing evals/{required}")
    return len(names), groups


def check_tenants(errors: list[str]) -> None:
    """Org-specific facts live in tenants/, never in skills/."""
    for path in (ROOT / "skills").rglob("*"):
        if path.is_file() and path.suffix in {".md", ".json"}:
            text = path.read_text(encoding="utf-8")
            if re.search(r"GREENHOUSE_API_KEY\s*=\s*\S+|harvest_[0-9a-f]{20,}", text):
                errors.append(f"{path.relative_to(ROOT)}: looks like a credential in skills/")
    for cfg in (ROOT / "tenants").rglob("*.json"):
        data = json.loads(cfg.read_text(encoding="utf-8"))
        if "jurisdictions" not in data:
            errors.append(f"{cfg.relative_to(ROOT)}: role config must name jurisdictions (GR13)")


def check_root_files(errors: list[str]) -> None:
    for filename in ROOT_FILES:
        if not (ROOT / filename).is_file():
            errors.append(f"missing {filename}")


def main() -> int:
    errors: list[str] = []
    manifest = check_manifest(errors)
    author = (manifest.get("author") or {}).get("name", "")
    for slug, spec in SKILLS.items():
        check_skill(slug, spec, author, errors)
    check_references(errors)
    check_commands_and_agents(errors)
    tools = check_mcp(errors)
    check_tenants(errors)
    check_root_files(errors)
    case_count, groups = check_evals(errors)

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        print(f"\n{len(errors)} problem(s) found.")
        return 1
    print(f"PASS: {ROOT.name} v{manifest.get('version')} is structurally valid")
    print(f"PASS: {len(SKILLS)} skills, {len(COMMANDS)} commands, {len(AGENTS)} agents; references and links resolve")
    print(f"PASS: {len(tools)} MCP tools declared and defined; ATS write tools default confirm to False")
    print(f"PASS: version and author declared once, author is {author}")
    print(f"PASS: {case_count} eval cases: " + ", ".join(f"{g} {n}" for g, n in sorted(groups.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
