"""Match score, confidence and band (scoring-model.md, confidence-model.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .rubric import rubric_hash

DEFAULT_THRESHOLDS = {
    "shortlist_min_score": 75.0,
    "review_min_score": 60.0,
    "shortlist_min_confidence": 0.5,
    "low_confidence_below": 0.5,
    "parse_quality_min": 0.6,
}

CONFIDENCE_WEIGHTS = {
    "coverage": 0.40,
    "parse_quality": 0.25,
    "jd_specificity": 0.20,
    "gate_verifiability": 0.15,
}
INJECTION_PENALTY = 0.15

STATUS_FOR_SCORE = {4: "met", 3: "met", 2: "partial", 1: "partial", 0: ("absent", "unverifiable")}
NO_EVIDENCE = "no evidence"

BANNED_OUTPUT_WORDS = ("reject", "rejected", "do not hire", "hire", "unqualified")


@dataclass
class BandResult:
    score: float
    confidence: float
    confidence_level: str
    band: str
    band_rule: int
    components: dict = field(default_factory=dict)
    screening_items: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "confidence": self.confidence,
            "confidence_level": self.confidence_level,
            "band": self.band,
            "band_rule": self.band_rule,
            "components": self.components,
            "screening_items": self.screening_items,
        }


def confidence_level(value: float) -> str:
    if value >= 0.75:
        return "High"
    if value >= 0.5:
        return "Med"
    return "Low"


def jd_specificity(rubric: dict) -> float:
    """Share of signals whose full-evidence description is concrete (four or more words)."""
    signals = rubric.get("signals", [])
    if not signals:
        return 0.0
    concrete = sum(1 for s in signals if len(str(s.get("evidence_full", "")).split()) >= 4)
    return concrete / len(signals)


def _points(c: dict | None) -> int:
    try:
        value = int(float(c["score"])) if c else 0
    except (TypeError, ValueError, KeyError):
        return 0
    return value if 0 <= value <= 4 else 0


def match_score(rubric: dict, scorecard: dict) -> float:
    by_id = {c["id"]: c for c in scorecard.get("criteria", [])}
    total = 0.0
    for s in rubric["signals"]:
        points = _points(by_id.get(s["id"]))
        total += float(s["weight"]) * points / 4.0
    return round(total, 1)


def evidence_coverage(rubric: dict, scorecard: dict) -> float:
    by_id = {c["id"]: c for c in scorecard.get("criteria", [])}
    covered = 0.0
    for s in rubric["signals"]:
        c = by_id.get(s["id"])
        if c and c.get("status") in ("met", "partial", "absent"):
            covered += float(s["weight"])
    return covered / 100.0


def effective_gates(rubric: dict, scorecard: dict) -> list[dict]:
    """Every rubric gate, with the scorecard's status. A gate the scorecard leaves out is unverifiable."""
    given = {g.get("id"): g for g in scorecard.get("gates", [])}
    return [given.get(g["id"], {"id": g["id"], "status": "unverifiable"}) for g in rubric.get("gates", [])]


def gate_verifiability(rubric: dict, scorecard: dict) -> float:
    gates = effective_gates(rubric, scorecard)
    if not gates:
        return 1.0
    return sum(1 for g in gates if g.get("status") in ("passed", "failed")) / len(gates)


def score_and_band(
    rubric: dict,
    scorecard: dict,
    thresholds: dict | None = None,
    shortlist_on_unverifiable: bool = False,
    parse_quality: float | None = None,
    injection_flagged: bool | None = None,
) -> BandResult:
    """`parse_quality` and `injection_flagged` should come from prepare_resume, not from the
    scorer: the scorer must not report the values that decide its own band."""
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    score = match_score(rubric, scorecard)
    if parse_quality is None:
        parse_quality = float(scorecard.get("parse_quality", 0.0))
    if injection_flagged is None:
        injection_flagged = bool(scorecard.get("injection_flagged"))
    components = {
        "coverage": round(evidence_coverage(rubric, scorecard), 4),
        "parse_quality": round(parse_quality, 4),
        "jd_specificity": round(jd_specificity(rubric), 4),
        "gate_verifiability": round(gate_verifiability(rubric, scorecard), 4),
    }
    confidence = sum(CONFIDENCE_WEIGHTS[k] * v for k, v in components.items())
    if injection_flagged:
        confidence -= INJECTION_PENALTY
        components["injection_penalty"] = INJECTION_PENALTY
    confidence = round(max(0.0, min(1.0, confidence)), 4)
    level = confidence_level(confidence)

    gates = effective_gates(rubric, scorecard)
    failed = [g for g in gates if g.get("status") == "failed"]
    unverifiable = [g for g in gates if g.get("status") == "unverifiable"]
    screening = [f"{g['id']}: confirm on screening call" for g in unverifiable]

    if failed:
        band, rule = "Not recommended", 1
    elif confidence < t["low_confidence_below"] or parse_quality < t["parse_quality_min"]:
        band, rule = "Review", 2
    elif unverifiable and score >= t["shortlist_min_score"] and not shortlist_on_unverifiable:
        band, rule = "Review", 3
    elif score >= t["shortlist_min_score"] and confidence >= t["shortlist_min_confidence"]:
        band, rule = "Shortlist", 4
    elif score >= t["review_min_score"]:
        band, rule = "Review", 5
    else:
        band, rule = "Not recommended", 6

    return BandResult(score, confidence, level, band, rule, components, screening)


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def haystack_for_gates(resume_text: str) -> str:
    return _norm(resume_text)


def validate_scorecard(rubric: dict, scorecard: dict, resume_text: str, flag_spans: list | None = None) -> list[str]:
    """Mechanical GR4 and GR5 checks. Returns a list of problems."""
    problems: list[str] = []
    expected_hash = rubric.get("rubric_hash") or rubric_hash(rubric)
    if scorecard.get("rubric_hash") != expected_hash:
        problems.append("rubric_hash does not match the batch rubric (GR4)")

    signal_ids = [s["id"] for s in rubric["signals"]]
    got = [c.get("id") for c in scorecard.get("criteria", [])]
    missing = sorted(set(signal_ids) - set(got))
    extra = sorted(set(got) - set(signal_ids))
    dupes = sorted({x for x in got if got.count(x) > 1})
    if dupes:
        problems.append(f"duplicate criteria in scorecard: {', '.join(dupes)}")
    gate_ids = [g["id"] for g in rubric.get("gates", [])]
    got_gates = [g.get("id") for g in scorecard.get("gates", [])]
    missing_gates = sorted(set(gate_ids) - set(got_gates))
    if missing_gates:
        problems.append(f"gates missing from scorecard (treated as unverifiable): {', '.join(missing_gates)}")
    for g in scorecard.get("gates", []):
        if g.get("status") not in ("passed", "failed", "unverifiable"):
            problems.append(f"{g.get('id')}: gate status must be passed, failed or unverifiable")
        elif g.get("status") in ("passed", "failed") and _norm(str(g.get("evidence", ""))) not in haystack_for_gates(resume_text):
            problems.append(f"{g.get('id')}: a {g.get('status')} gate needs a quote that appears in the resume (GR5)")
    if missing:
        problems.append(f"criteria missing from scorecard: {', '.join(missing)}")
    if extra:
        problems.append(f"criteria not in the rubric: {', '.join(extra)}")

    haystack = _norm(resume_text)
    flagged_text = []
    for span in flag_spans or []:
        flagged_text.append(_norm(resume_text[span[0]:span[1]]))

    for c in scorecard.get("criteria", []):
        cid, status = c.get("id"), c.get("status")
        try:
            score = int(c.get("score", 0))
        except (TypeError, ValueError):
            problems.append(f"{cid}: score must be a whole number from 0 to 4")
            continue
        evidence = str(c.get("evidence", "")).strip()
        allowed = STATUS_FOR_SCORE.get(score)
        if allowed is None:
            problems.append(f"{cid}: score {score} outside 0 to 4")
            continue
        if isinstance(allowed, tuple):
            if status not in allowed:
                problems.append(f"{cid}: score 0 must have status absent or unverifiable, got {status}")
        elif status != allowed:
            problems.append(f"{cid}: score {score} must have status {allowed}, got {status}")
        if score > 0:
            if not evidence or _norm(evidence) == NO_EVIDENCE:
                problems.append(f"{cid}: score {score} with no quoted evidence (GR5)")
            elif _norm(evidence) not in haystack:
                problems.append(f"{cid}: quote does not appear verbatim in the resume (GR5)")
            elif any(_norm(evidence) in ft or ft in _norm(evidence) for ft in flagged_text if ft):
                problems.append(f"{cid}: quote comes from content flagged as injection (GR3)")
    return problems


PHONE_CANDIDATE = re.compile(r"(?<![\w])\+?\(?\d[\d ().-]{7,}\d(?![\w])")


def find_phone_numbers(text: str) -> list[tuple[int, int]]:
    """Spans that look like phone numbers: 10 to 15 digits, not a year range."""
    spans = []
    for m in PHONE_CANDIDATE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if not 10 <= len(digits) <= 15:
            continue
        if re.fullmatch(r"\s*(19|20)\d{2}\s*[-.]\s*(19|20)\d{2}\s*", m.group()):
            continue
        spans.append(m.span())
    return spans


def output_wording_problems(text: str) -> list[str]:
    """GR8 and GR10 checks on rendered text."""
    problems = []
    lowered = text.lower()
    for word in BANNED_OUTPUT_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            problems.append(f"decision wording in output: '{word}' (GR10)")
    for line in text.splitlines():
        low = line.lower()
        # A candidate line carries a score (82.5, or 40 / 100); a count line ("8 Not recommended") does not.
        per_candidate = re.search(r"\b\d{1,3}\.\d\b|\b\d{1,3}\s*/\s*100\b", line) and "not recommended" in low
        if per_candidate and "human confirms" not in low:
            problems.append("a Not recommended candidate line lacks 'recommendation; a human confirms' (GR8)")
            break
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
        problems.append("email address in output (GR11)")
    if find_phone_numbers(text):
        problems.append("phone number in output (GR11)")
    return problems
