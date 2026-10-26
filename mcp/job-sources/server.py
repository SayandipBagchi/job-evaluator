#!/usr/bin/env python3
"""job-sources MCP server for the job-evaluator plugin.

Thin wrappers over job_sources/. Raw resume text never comes back to the model
from a file or the ATS: `prepare_resume` and `ats_get_resume` return only the
injection-neutralised, redacted text and a cand_ref. Identity is sealed on disk
and returned only by `identity_rejoin`, for rendering.

Write tools: ats_add_note (needs confirm=true), eval_log and
record_human_decision (local, append-only).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from job_sources import audit, injection, jd, parsing, redaction, rubric, scoring  # noqa: E402
from job_sources.adapters import ADAPTERS, AtsError, ConfirmationRequired  # noqa: E402

PLUGIN_ROOT = HERE.parents[1]
try:
    PLUGIN_VERSION = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
except (OSError, KeyError, json.JSONDecodeError):
    PLUGIN_VERSION = "unknown"

READ_TOOLS = (
    "jd_fetch", "jd_from_text", "resume_parse", "injection_scan", "redact", "prepare_resume",
    "rubric_hash", "rubric_validate", "score_and_band", "validate_scorecard", "check_output_wording",
    "identity_rejoin", "ats_list_jobs", "ats_list_applicants", "ats_get_resume",
)
WRITE_TOOLS = ("ats_add_note", "eval_log", "record_human_decision", "eval_log_prune")


def _error(code: str, message: str) -> dict:
    return {"status": "error", "code": code, "message": message}


def _adapter(provider: str):
    cls = ADAPTERS.get(provider)
    if cls is None:
        raise AtsError("unknown_provider", f"Unknown ATS provider '{provider}'. Known: {', '.join(ADAPTERS)}")
    return cls()


def _prepare(text: str, source: str, jd_keywords: list[str] | None, hidden_spans: list | None,
             known_name: str | None) -> dict:
    parsed = parsing.parse_text(text, source=source, hidden_spans=hidden_spans)
    guardrails_not_run = []
    try:
        scan = injection.scan(parsed.text, jd_keywords=jd_keywords, hidden_spans=parsed.hidden_spans)
    except Exception:  # fail closed: an unscanned resume goes to Review (GR3)
        scan = injection.ScanResult(flags=[{"kind": "scan_failed", "start": 0, "end": 0}], text=parsed.text)
        guardrails_not_run.append("GR3")
    red = redaction.redact(scan.text, known_name=known_name)
    # cand_ref comes from the original text so the same resume always maps to the same ref.
    red.cand_ref = redaction.cand_ref_for(text)
    audit.seal_identity(red.cand_ref, red.identity)
    return {
        "status": "ok",
        "cand_ref": red.cand_ref,
        "source": source,
        "text": red.text,
        "redacted": True,
        "removed_counts": red.removed,
        "parse_quality": parsed.parse_quality,
        "parse_notes": parsed.notes,
        "injection_flagged": scan.flagged,
        "injection_flags": [{"kind": f["kind"]} for f in scan.flags],
        "resume_hash": rubric.text_hash(red.text),
        "guardrails_not_run": guardrails_not_run,
    }


# Plain functions first, so tests can call them without the MCP runtime.

def jd_fetch(url: str) -> dict:
    """Fetch a JD from a URL. Uses Greenhouse and Lever public posting APIs when the URL matches; otherwise fetches the page. Returns status 'blocked' when the site refuses: ask the user for the text, do not retry another way."""
    return jd.fetch(url)


def jd_from_text(text: str, title: str | None = None) -> dict:
    """Normalise a pasted or attached JD: title, text, extracted requirements, keywords, jd_hash, and a 'thin' flag when fewer than 3 requirements are found (GR1)."""
    if not text or not text.strip():
        return _error("empty", "No JD text given")
    return jd.from_text(text, title)


def resume_parse(path: str) -> dict:
    """Diagnose a resume file: parse quality, sections and notes. Does not return the text; use prepare_resume for scoring input."""
    try:
        parsed = parsing.parse_file(path)
    except parsing.ParseError as exc:
        return _error("parse_error", str(exc))
    out = parsed.as_dict()
    out.pop("text")
    out["status"] = "ok"
    return out


def injection_scan(text: str, jd_keywords: list[str] | None = None) -> dict:
    """GR3 scan. Returns flags (kind and span) and the neutralised text."""
    return injection.scan(text, jd_keywords=jd_keywords).as_dict()


def redact(text: str, known_name: str | None = None) -> dict:
    """Blind-evaluation redaction. Returns cand_ref and redacted text; identity is sealed on disk, never returned."""
    red = redaction.redact(text, known_name=known_name)
    audit.seal_identity(red.cand_ref, red.identity)
    return {"status": "ok", **red.public()}


def prepare_resume(path: str | None = None, text: str | None = None, jd_keywords: list[str] | None = None,
                   known_name: str | None = None) -> dict:
    """Phase 2 in one call: parse (file or text), injection scan, redact, seal identity. Returns only what the scorer may see."""
    if bool(path) == bool(text):
        return _error("bad_input", "Pass exactly one of path or text")
    try:
        if path:
            raw, hidden, source = parsing.read_file(path)
        else:
            raw, hidden, source = text, [], "pasted"
    except parsing.ParseError as exc:
        return _error("parse_error", str(exc))
    return _prepare(raw, source, jd_keywords, hidden, known_name)


def rubric_hash(rubric_json: dict) -> dict:
    """SHA-256 of the canonical rubric JSON (keys sorted, no whitespace, rubric_hash field excluded)."""
    return {"rubric_hash": rubric.rubric_hash(rubric_json)}


def rubric_validate(rubric_json: dict) -> dict:
    """Check weights sum to 100, weak signals at most 5, ids, and no protected attribute or proxy in any criterion (GR7)."""
    problems = rubric.validate_rubric(rubric_json)
    return {"valid": not problems, "problems": problems, "rubric_hash": rubric.rubric_hash(rubric_json)}


def score_and_band(rubric_json: dict, scorecard: dict, parse_quality: float, injection_flagged: bool,
                   thresholds: dict | None = None, shortlist_on_unverifiable: bool = False) -> dict:
    """Compute match score, confidence, level and band deterministically, with the band rule that matched. Pass parse_quality and injection_flagged from the prepare_resume result, never from the scorecard. A rubric gate missing from the scorecard counts as unverifiable."""
    problems = rubric.validate_rubric(rubric_json)
    if problems:
        return _error("invalid_rubric", "; ".join(problems))
    return scoring.score_and_band(rubric_json, scorecard, thresholds, shortlist_on_unverifiable,
                                  parse_quality=parse_quality, injection_flagged=injection_flagged).as_dict()


def validate_scorecard(rubric_json: dict, scorecard: dict, resume_text: str) -> dict:
    """GR4 and GR5: rubric hash matches, every criterion present, statuses agree with scores, every quote appears verbatim in the redacted resume."""
    problems = scoring.validate_scorecard(rubric_json, scorecard, resume_text)
    return {"valid": not problems, "problems": problems}


def check_output_wording(text: str) -> dict:
    """GR8, GR10, GR11 on rendered output: no decision words, Not recommended lines carry the human-confirms wording, no email or phone."""
    problems = scoring.output_wording_problems(text)
    return {"valid": not problems, "problems": problems}


def identity_rejoin(cand_refs: list[str]) -> dict:
    """Render step only: display name and profile links for each cand_ref. Never contact details."""
    return audit.rejoin(cand_refs)


def ats_list_jobs(provider: str = "greenhouse", status: str = "open") -> dict:
    """List jobs in the ATS. Read-only."""
    try:
        return {"status": "ok", "jobs": _adapter(provider).list_jobs(status)}
    except AtsError as exc:
        return _error(exc.code, exc.message)


def ats_list_applicants(job_id: str, provider: str = "greenhouse", page: int = 1) -> dict:
    """One page (100) of active applications for a job: ids, stage, has_resume, profile link. No contact details. Read-only."""
    try:
        return {"status": "ok", **_adapter(provider).list_applicants(job_id, page)}
    except AtsError as exc:
        return _error(exc.code, exc.message)


def ats_get_resume(application_id: str, provider: str = "greenhouse", jd_keywords: list[str] | None = None) -> dict:
    """Download an application's resume and return it prepared for scoring (parsed, scanned, redacted). The raw file stays on disk. Read-only."""
    try:
        with tempfile.TemporaryDirectory(prefix="job-evaluator-") as tmp:
            path = _adapter(provider).get_resume(application_id, tmp)
            raw, hidden, _ = parsing.read_file(path)
            result = _prepare(raw, f"{provider}:{application_id}", jd_keywords, hidden, None)
        return result
    except AtsError as exc:
        return _error(exc.code, exc.message)
    except parsing.ParseError as exc:
        return _error("parse_error", str(exc))


def ats_add_note(application_id: str, text: str, confirm: bool = False, provider: str = "greenhouse",
                 on_behalf_of: str | None = None) -> dict:
    """WRITE. Add a private note to the candidate's ATS record. Refuses with confirmation_required unless the user approved this exact note in this session and confirm=true. Never changes stage, never rejects."""
    try:
        if confirm is not True:  # GR12 fires before anything else, configured or not
            raise ConfirmationRequired({"application_id": application_id, "note": text})
        return _adapter(provider).add_note(application_id, text, confirm, on_behalf_of)
    except ConfirmationRequired as exc:
        return {"status": "confirmation_required", "preview": exc.preview,
                "message": "Show the user this exact note and ask for approval, then call again with confirm=true."}
    except AtsError as exc:
        return _error(exc.code, exc.message)


def eval_log(record: dict) -> dict:
    """WRITE (local, append-only). One audit record per evaluation. Required: role_id, rubric_hash, cand_ref, resume_hash, score, confidence, band, jurisdictions, guardrails_not_run (a list, empty if none). Optional: confidence_level, band_rule, parse_quality, injection_flagged, rubric_id, source, reviewers, retention_days. Any other field, and any email or phone number, is refused."""
    return audit.append(record, PLUGIN_VERSION)


def record_human_decision(role_id: str, cand_ref: str, rubric_hash_value: str, decision: str, reviewer: str,
                          reason: str = "") -> dict:
    """WRITE (local, append-only). Record the human's decision beside the recommendation: advance, hold, decline, override_up or override_down."""
    return audit.record_decision(role_id, cand_ref, rubric_hash_value, decision, reviewer, reason)


def eval_log_prune(retention_days: int) -> dict:
    """WRITE (local). Delete audit records and sealed identities older than the role's retention_days."""
    return audit.prune(retention_days)


TOOLS = [globals()[name] for name in READ_TOOLS + WRITE_TOOLS]


def main() -> None:
    try:  # MCP Python SDK 2.x
        from mcp.server.mcpserver import MCPServer as Server  # type: ignore
    except ImportError:
        try:  # MCP Python SDK 1.x
            from mcp.server.fastmcp import FastMCP as Server  # type: ignore
        except ImportError:
            sys.stderr.write("job-sources needs the MCP SDK: pip install -r requirements.txt\n")
            sys.exit(1)
    server = Server("job-sources")
    for fn in TOOLS:
        server.tool()(fn)
    server.run()


if __name__ == "__main__":
    main()
