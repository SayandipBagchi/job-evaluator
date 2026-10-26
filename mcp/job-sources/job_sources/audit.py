"""Append-only audit log and the sealed identity store (compliance-matrix.md).

The log holds hashes and outcomes, never resume text or contact details. The
identity store maps cand_ref to a display name and profile links so the render
step can rejoin identity; it never holds email or phone, and the scoring context
never reads it.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

REQUIRED = ("role_id", "rubric_hash", "cand_ref", "resume_hash", "score", "confidence", "band", "jurisdictions",
            "guardrails_not_run")
# An allowlist, not a blocklist: a key that is not here is refused, so personal data cannot slip in under a new name.
ALLOWED_KEYS = set(REQUIRED) | {"confidence_level", "band_rule", "parse_quality", "injection_flagged", "rubric_id",
                                "source", "reviewers", "retention_days"}
ALLOWED_DECISIONS = {"advance", "hold", "decline", "override_up", "override_down"}


def log_dir() -> Path:
    base = os.environ.get("JOB_EVALUATOR_LOG_DIR") or str(Path.home() / ".job-evaluator" / "logs")
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _personal_content(value: str) -> list[str]:
    from .scoring import find_phone_numbers

    found = []
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", value):
        found.append("an email address")
    if find_phone_numbers(value):
        found.append("a phone number")
    return found


def _check(record: dict) -> list[str]:
    problems = [f"missing field: {k}" for k in REQUIRED if k not in record]
    extra = sorted(set(record) - ALLOWED_KEYS)
    if extra:
        problems.append(f"fields not allowed in the log (it never stores personal or resume content): {', '.join(extra)}")
    for what in _personal_content(json.dumps(record)):
        problems.append(f"record contains {what}")
    if "jurisdictions" in record and not record["jurisdictions"]:
        problems.append("jurisdictions must be named (GR13)")
    if record.get("band") not in {"Shortlist", "Review", "Not recommended"}:
        problems.append("band must be Shortlist, Review or Not recommended")
    return problems


def append(record: dict, plugin_version: str) -> dict:
    problems = _check(record)
    if problems:
        return {"status": "rejected", "problems": problems}
    row = {"event": "evaluation", "timestamp": _now(), "plugin_version": plugin_version,
           "human_decision": None, **record}
    with (log_dir() / "evaluations.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return {"status": "logged", "timestamp": row["timestamp"]}


def record_decision(role_id: str, cand_ref: str, rubric_hash: str, decision: str, reviewer: str, reason: str = "") -> dict:
    if decision not in ALLOWED_DECISIONS:
        return {"status": "rejected", "problems": [f"decision must be one of {sorted(ALLOWED_DECISIONS)}"]}
    personal = _personal_content(reason + " " + reviewer)
    if personal:
        return {"status": "rejected", "problems": [f"reason or reviewer contains {p}" for p in personal]}
    row = {"event": "human_decision", "timestamp": _now(), "role_id": role_id, "cand_ref": cand_ref,
           "rubric_hash": rubric_hash, "decision": decision, "reviewer": reviewer, "reason": reason[:500]}
    with (log_dir() / "evaluations.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return {"status": "logged", "timestamp": row["timestamp"]}


def seal_identity(cand_ref: str, identity: dict) -> None:
    store = log_dir() / "identity"
    store.mkdir(exist_ok=True)
    safe = {"name": identity.get("name"), "profile_links": identity.get("profile_links", [])}
    (store / f"{cand_ref}.json").write_text(json.dumps(safe), encoding="utf-8")


def rejoin(cand_refs: list[str]) -> dict:
    store = log_dir() / "identity"
    out = {}
    for ref in cand_refs:
        if not re.fullmatch(r"cand_[0-9a-f]{8}", ref):
            out[ref] = {"error": "not a cand_ref"}
            continue
        path = store / f"{ref}.json"
        out[ref] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"name": None, "profile_links": []}
    return out


def prune(retention_days: int) -> dict:
    """Delete evaluation records and sealed identities older than the retention period."""
    if retention_days < 1:
        return {"status": "rejected", "problems": ["retention_days must be at least 1"]}
    cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
    path = log_dir() / "evaluations.jsonl"
    kept, dropped = [], 0
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                ts = datetime.fromisoformat(json.loads(line)["timestamp"]).timestamp()
            except (ValueError, KeyError):
                kept.append(line)
                continue
            if ts < cutoff:
                dropped += 1
            else:
                kept.append(line)
        path.write_text("".join(l + "\n" for l in kept), encoding="utf-8")
    store = log_dir() / "identity"
    removed_ids = 0
    if store.is_dir():
        for f in store.glob("cand_*.json"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed_ids += 1
    return {"status": "pruned", "records_removed": dropped, "identities_removed": removed_ids}
