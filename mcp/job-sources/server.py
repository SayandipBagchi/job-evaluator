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
from typing import Annotated

from pydantic import Field

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


# Input limits. A resume or JD is a few thousand words; anything far beyond these is not one, and the
# regex-heavy redaction and wording checks should never be handed megabytes of text.
MAX_TEXT = 100_000        # resume, JD or note text, in characters
MAX_RENDERED = 200_000    # a rendered shortlist checked by check_output_wording
MAX_SHORT = 500           # ids, names, provider and role strings
MAX_PATH = 4096
MAX_LIST = 200            # keywords, cand_refs


def _error(code: str, message: str) -> dict:
    return {"status": "error", "code": code, "message": message}


def _too_long(**values) -> dict | None:
    """Same limits as the schemas, for callers that bypass MCP validation (tests, direct imports)."""
    limits = {"text": MAX_TEXT, "resume_text": MAX_TEXT, "path": MAX_PATH, "url": jd.MAX_URL_CHARS}
    for name, value in values.items():
        limit = limits.get(name, MAX_SHORT)
        if isinstance(value, str) and len(value) > limit:
            return _error("too_large", f"{name} is longer than {limit} characters")
        if isinstance(value, list) and len(value) > MAX_LIST:
            return _error("too_large", f"{name} has more than {MAX_LIST} items")
    return None


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


# Parameter types: Annotated with a description and a size limit, so the advertised JSON schema documents
# every argument and the MCP layer rejects oversize input before any tool code runs.
Url = Annotated[str, Field(description="Public http(s) URL of a job posting (Greenhouse, Lever or a careers page).",
                           max_length=jd.MAX_URL_CHARS)]
JdText = Annotated[str, Field(description="Full job description text, pasted or extracted from a file.", max_length=MAX_TEXT)]
ResumeText = Annotated[str, Field(description="Resume text (plain text or Markdown).", max_length=MAX_TEXT)]
FilePath = Annotated[str, Field(description="Path to a local resume file: .pdf, .docx, .txt or .md.", max_length=MAX_PATH)]
Keywords = Annotated[list[Annotated[str, Field(max_length=100)]] | None,
                     Field(description="JD keywords from JD intake, used to spot keyword stuffing. Optional.", max_length=MAX_LIST)]
KnownName = Annotated[str | None, Field(description="Candidate's name if already known, so every form of it is redacted. Optional.",
                                        max_length=MAX_SHORT)]
RubricJson = Annotated[dict, Field(description="Frozen rubric object in the shape of skills/job-evaluator/schemas/rubric.schema.json.")]
Scorecard = Annotated[dict, Field(description="Scorecard object in the shape of skills/job-evaluator/schemas/scorecard.schema.json.")]
Provider = Annotated[str, Field(description="ATS provider id: 'greenhouse' or 'lever'.", max_length=40)]
AppId = Annotated[str, Field(description="ATS application id.", max_length=100)]


# Plain functions first, so tests can call them without the MCP runtime.

def jd_fetch(url: Url) -> dict:
    """Fetch a JD from a public http(s) URL. Uses the Greenhouse and Lever public posting APIs when the URL matches; otherwise fetches the page. Private, loopback, link-local and metadata addresses are refused, as are redirects to them. Returns status 'blocked' or 'refused' when the page cannot be fetched: ask the user for the text, do not retry another way."""
    return _too_long(url=url) or jd.fetch(url)


def jd_from_text(text: JdText,
                 title: Annotated[str | None, Field(description="Job title, if not on the first line. Optional.", max_length=MAX_SHORT)] = None) -> dict:
    """Normalise a pasted or attached JD: title, text, extracted requirements, keywords, jd_hash, and a 'thin' flag when fewer than 3 requirements are found (GR1)."""
    if not text or not text.strip():
        return _error("empty", "No JD text given")
    return _too_long(text=text, title=title) or jd.from_text(text, title)


def resume_parse(path: FilePath) -> dict:
    """Diagnose a resume file: parse quality, sections and notes. Does not return the resume text."""
    if (err := _too_long(path=path)):
        return err
    try:
        parsed = parsing.parse_file(path)
    except parsing.ParseError as exc:
        return _error("parse_error", str(exc))
    out = parsed.as_dict()
    out.pop("text")
    out["status"] = "ok"
    return out


def injection_scan(text: Annotated[str, Field(description="Resume or JD text to scan for prompt injection.", max_length=MAX_TEXT)],
                   jd_keywords: Keywords = None) -> dict:
    """GR3 scan. Returns flags (kind and span) and the neutralised text."""
    return _too_long(text=text, jd_keywords=jd_keywords) or injection.scan(text, jd_keywords=jd_keywords).as_dict()


def redact(text: Annotated[str, Field(description="Resume text to redact for blind evaluation.", max_length=MAX_TEXT)],
           known_name: KnownName = None) -> dict:
    """Blind-evaluation redaction. Returns cand_ref and redacted text; identity is sealed on disk, never returned."""
    if (err := _too_long(text=text, known_name=known_name)):
        return err
    red = redaction.redact(text, known_name=known_name)
    audit.seal_identity(red.cand_ref, red.identity)
    return {"status": "ok", **red.public()}


def prepare_resume(path: Annotated[str | None, Field(description="Path to a local resume file (.pdf, .docx, .txt, .md). Give this or text.",
                                                     max_length=MAX_PATH)] = None,
                   text: Annotated[str | None, Field(description="Pasted resume text. Give this or path.", max_length=MAX_TEXT)] = None,
                   jd_keywords: Keywords = None, known_name: KnownName = None) -> dict:
    """Phase 2 in one call: parse (file or text), injection scan, blind-evaluation redaction, and identity sealed on disk. Returns only what the scorer may see: redacted text, cand_ref, parse_quality, injection_flagged and resume_hash."""
    if bool(path) == bool(text):
        return _error("bad_input", "Pass exactly one of path or text")
    if (err := _too_long(path=path, text=text, jd_keywords=jd_keywords, known_name=known_name)):
        return err
    try:
        if path:
            raw, hidden, source = parsing.read_file(path)
        else:
            raw, hidden, source = text, [], "pasted"
    except parsing.ParseError as exc:
        return _error("parse_error", str(exc))
    if len(raw) > MAX_TEXT:
        return _error("too_large", f"Extracted resume text is longer than {MAX_TEXT} characters")
    return _prepare(raw, source, jd_keywords, hidden, known_name)


def rubric_hash(rubric_json: RubricJson) -> dict:
    """SHA-256 of the canonical rubric JSON (keys sorted, no whitespace, the rubric's own hash field excluded)."""
    return {"rubric_hash": rubric.rubric_hash(rubric_json)}


def rubric_validate(rubric_json: RubricJson) -> dict:
    """Check weights sum to 100, weak signals at most 5, ids, and no protected attribute or proxy in any criterion (GR7)."""
    problems = rubric.validate_rubric(rubric_json)
    return {"valid": not problems, "problems": problems, "rubric_hash": rubric.rubric_hash(rubric_json)}


def score_and_band(rubric_json: RubricJson, scorecard: Scorecard,
                   parse_quality: Annotated[float, Field(description="Parse quality 0-1 from the resume preparation result, never from the scorecard.", ge=0, le=1)],
                   injection_flagged: Annotated[bool, Field(description="Injection flag from the resume preparation result, never from the scorecard.")],
                   thresholds: Annotated[dict | None, Field(description="Optional band thresholds from the role config, e.g. {\"shortlist\": 75, \"review\": 55}.")] = None,
                   shortlist_on_unverifiable: Annotated[bool, Field(description="Role-config switch: allow Shortlist when a gate is unverifiable. Default false.")] = False) -> dict:
    """Compute match score, confidence, level and band deterministically, with the band rule that matched. parse_quality and injection_flagged must come from resume preparation, never from the scorecard. A rubric gate missing from the scorecard counts as unverifiable."""
    problems = rubric.validate_rubric(rubric_json)
    if problems:
        return _error("invalid_rubric", "; ".join(problems))
    return scoring.score_and_band(rubric_json, scorecard, thresholds, shortlist_on_unverifiable,
                                  parse_quality=parse_quality, injection_flagged=injection_flagged).as_dict()


def validate_scorecard(rubric_json: RubricJson, scorecard: Scorecard,
                       resume_text: Annotated[str, Field(description="The redacted resume text the scorecard was written from.", max_length=MAX_TEXT)]) -> dict:
    """GR4 and GR5: rubric hash matches, every criterion present, statuses agree with scores, every quote appears verbatim in the redacted resume."""
    if (err := _too_long(resume_text=resume_text)):
        return err
    problems = scoring.validate_scorecard(rubric_json, scorecard, resume_text)
    return {"valid": not problems, "problems": problems}


def check_output_wording(text: Annotated[str, Field(description="Rendered output (scorecard or shortlist) to check before showing it.",
                                                    max_length=MAX_RENDERED)]) -> dict:
    """GR8, GR10, GR11 on rendered output: no decision words, Not recommended lines carry the human-confirms wording, no email or phone."""
    if isinstance(text, str) and len(text) > MAX_RENDERED:
        return _error("too_large", f"text is longer than {MAX_RENDERED} characters")
    problems = scoring.output_wording_problems(text)
    return {"valid": not problems, "problems": problems}


def identity_rejoin(cand_refs: Annotated[list[Annotated[str, Field(max_length=20)]],
                                         Field(description="cand_ref values (cand_ + 8 hex) to show names for.", max_length=MAX_LIST)]) -> dict:
    """Render step only: display name and profile links for each cand_ref. Never contact details."""
    return _too_long(cand_refs=cand_refs) or audit.rejoin(cand_refs)


def ats_list_jobs(provider: Provider = "greenhouse",
                  status: Annotated[str, Field(description="Job status filter, e.g. 'open'.", max_length=40)] = "open") -> dict:
    """List jobs in the ATS. Read-only."""
    try:
        return {"status": "ok", "jobs": _adapter(provider).list_jobs(status)}
    except AtsError as exc:
        return _error(exc.code, exc.message)


def ats_list_applicants(job_id: Annotated[str, Field(description="ATS job id.", max_length=100)], provider: Provider = "greenhouse",
                        page: Annotated[int, Field(description="1-based page number; 100 applications per page.", ge=1, le=10_000)] = 1) -> dict:
    """One page (100) of active applications for a job: ids, stage, has_resume, profile link. No contact details. Read-only."""
    try:
        return {"status": "ok", **_adapter(provider).list_applicants(job_id, page)}
    except AtsError as exc:
        return _error(exc.code, exc.message)


def ats_get_resume(application_id: AppId, provider: Provider = "greenhouse", jd_keywords: Keywords = None) -> dict:
    """Download an application's resume and return it prepared for scoring (parsed, scanned, redacted). The raw file stays on disk. Read-only."""
    try:
        with tempfile.TemporaryDirectory(prefix="job-evaluator-") as tmp:
            path = _adapter(provider).get_resume(application_id, tmp)
            raw, hidden, _ = parsing.read_file(path)
            if len(raw) > MAX_TEXT:
                return _error("too_large", f"Extracted resume text is longer than {MAX_TEXT} characters")
            result = _prepare(raw, f"{provider}:{application_id}", jd_keywords, hidden, None)
        return result
    except AtsError as exc:
        return _error(exc.code, exc.message)
    except parsing.ParseError as exc:
        return _error("parse_error", str(exc))


def ats_add_note(application_id: AppId,
                 text: Annotated[str, Field(description="Exact note text the user approved.", max_length=10_000)],
                 confirm: Annotated[bool, Field(description="Must be true, and only after the user approved this exact note.")] = False,
                 provider: Provider = "greenhouse",
                 on_behalf_of: Annotated[str | None, Field(description="ATS user id the note is written as, if the provider needs one.", max_length=100)] = None) -> dict:
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


def eval_log(record: Annotated[dict, Field(description="One evaluation record; see the tool description for the allowed keys.")]) -> dict:
    """WRITE (local, append-only). One audit record per evaluation. Required: role_id, rubric_hash, cand_ref, resume_hash, score, confidence, band, jurisdictions, guardrails_not_run (a list, empty if none). Optional: confidence_level, band_rule, parse_quality, injection_flagged, rubric_id, source, reviewers, retention_days. Any other field, and any email or phone number, is refused."""
    return audit.append(record, PLUGIN_VERSION)


def record_human_decision(role_id: Annotated[str, Field(description="Role id from the role config.", max_length=MAX_SHORT)],
                          cand_ref: Annotated[str, Field(description="cand_ref of the evaluated resume.", max_length=20)],
                          rubric_hash_value: Annotated[str, Field(description="Hash of the rubric the candidate was scored on.", max_length=100)],
                          decision: Annotated[str, Field(description="advance, hold, decline, override_up or override_down.", max_length=20)],
                          reviewer: Annotated[str, Field(description="Reviewer's name or id (no email or phone).", max_length=MAX_SHORT)],
                          reason: Annotated[str, Field(description="Short reason for the decision. Optional.", max_length=2_000)] = "") -> dict:
    """WRITE (local, append-only). Record the human's decision beside the recommendation: advance, hold, decline, override_up or override_down."""
    return audit.record_decision(role_id, cand_ref, rubric_hash_value, decision, reviewer, reason)


def eval_log_prune(retention_days: Annotated[int, Field(description="Delete records older than this many days (at least 1).", ge=1, le=36_500)]) -> dict:
    """WRITE (local). Delete audit records and sealed identities older than the role's retention_days."""
    return audit.prune(retention_days)


TOOLS = [globals()[name] for name in READ_TOOLS + WRITE_TOOLS]

# MCP tool annotations (hints for hosts and reviewers). Open-world tools reach the network.
OPEN_WORLD = {"jd_fetch", "ats_list_jobs", "ats_list_applicants", "ats_get_resume", "ats_add_note"}
DESTRUCTIVE = {"eval_log_prune"}


def annotations_for(name: str) -> dict:
    read_only = name in READ_TOOLS and name not in {"redact", "prepare_resume", "ats_get_resume"}  # these seal identity on disk
    return {"readOnlyHint": read_only, "destructiveHint": name in DESTRUCTIVE,
            "idempotentHint": name not in {"ats_add_note", "eval_log", "record_human_decision"},
            "openWorldHint": name in OPEN_WORLD}


def _make_strict(server) -> None:
    """Reject unknown arguments: advertise additionalProperties false and make the argument model forbid extras.

    Uses the SDK's tool manager; if a future SDK changes it, tools still work with the SDK defaults.
    """
    manager = getattr(server, "_tool_manager", None)
    if manager is None:
        return
    for tool in manager.list_tools():
        try:
            model = tool.fn_metadata.arg_model
            strict = type(model.__name__, (model,), {"model_config": {**model.model_config, "extra": "forbid"},
                                                    "__module__": model.__module__})
            tool.fn_metadata.arg_model = strict
            tool.parameters["additionalProperties"] = False
        except Exception:  # pragma: no cover - SDK internals differ
            continue


def build_server():
    try:  # MCP Python SDK 2.x
        from mcp.server.mcpserver import MCPServer as Server  # type: ignore
    except ImportError:
        try:  # MCP Python SDK 1.x
            from mcp.server.fastmcp import FastMCP as Server  # type: ignore
        except ImportError:
            sys.stderr.write("job-sources needs the MCP SDK: pip install -r requirements.txt\n")
            sys.exit(1)
    from mcp.types import ToolAnnotations

    try:
        server = Server("job-sources", version=PLUGIN_VERSION)
    except TypeError:  # SDK without a version argument
        server = Server("job-sources")
    for fn in TOOLS:
        server.tool(annotations=ToolAnnotations(**annotations_for(fn.__name__)))(fn)
    _make_strict(server)
    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
