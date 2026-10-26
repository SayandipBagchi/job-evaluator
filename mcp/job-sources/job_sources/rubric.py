"""Rubric hashing and validation (GR4, GR7, fairness rules)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

WEAK_SIGNAL_CAP = 5.0
WEIGHT_TOLERANCE = 0.01

# Terms that must never become a criterion. Matched as whole words, case-insensitive.
FORBIDDEN_CRITERION_TERMS = (
    "age",
    "aged",
    "young",
    "youthful",
    "energetic",
    "digital native",
    "recent graduate",
    "graduation year",
    "gender",
    "male",
    "female",
    "man",
    "woman",
    "pronoun",
    "religion",
    "religious",
    "caste",
    "ethnicity",
    "race",
    "marital",
    "married",
    "has children",
    "pregnancy",
    "pregnant",
    "photo",
    "appearance",
    "native speaker",
    "mother tongue",
    "disability",
    "health condition",
    "employment gap",
)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def rubric_hash(rubric: dict) -> str:
    """SHA-256 over the canonical rubric JSON, with any rubric_hash field removed."""
    body = {k: v for k, v in rubric.items() if k != "rubric_hash"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def text_hash(text: str) -> str:
    normalised = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _has_forbidden(text: str) -> str | None:
    lowered = text.lower()
    for term in FORBIDDEN_CRITERION_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            return term
    return None


def validate_rubric(rubric: dict) -> list[str]:
    """Return a list of problems. Empty list means the rubric is usable."""
    problems: list[str] = []
    for key in ("role_title", "jd_hash", "weighting_note", "gates", "signals"):
        if key not in rubric:
            problems.append(f"missing field: {key}")
    if problems:
        return problems

    signals = rubric["signals"]
    gates = rubric["gates"]
    if len(signals) < 3:
        problems.append("fewer than 3 signals: the JD is too thin to screen against (GR1)")

    ids = [s.get("id") for s in signals] + [g.get("id") for g in gates]
    if len(ids) != len(set(ids)):
        problems.append("duplicate criterion ids")
    for s in signals:
        if not re.fullmatch(r"s\d+", str(s.get("id", ""))):
            problems.append(f"signal id must look like s1: {s.get('id')}")
    for g in gates:
        if not re.fullmatch(r"g\d+", str(g.get("id", ""))):
            problems.append(f"gate id must look like g1: {g.get('id')}")

    total = sum(float(s.get("weight", 0)) for s in signals)
    if abs(total - 100.0) > WEIGHT_TOLERANCE:
        problems.append(f"signal weights sum to {total:g}, not 100")

    weak = sum(float(s.get("weight", 0)) for s in signals if s.get("weak_signal"))
    if weak > WEAK_SIGNAL_CAP + WEIGHT_TOLERANCE:
        problems.append(f"weak signals carry {weak:g}, over the cap of {WEAK_SIGNAL_CAP:g} (GR7)")

    for item in list(signals) + list(gates):
        label = item.get("criterion") or item.get("requirement") or ""
        hit = _has_forbidden(label)
        if hit:
            problems.append(f"{item.get('id')}: criterion uses a protected attribute or proxy ('{hit}')")
        if "institution" in label.lower() or "university" in label.lower() or "college" in label.lower():
            if item.get("id", "").startswith("g"):
                problems.append(f"{item.get('id')}: institution can never be a gate (GR7)")
            elif not item.get("weak_signal"):
                problems.append(f"{item.get('id')}: institution must be marked weak_signal (GR7)")
    return problems
