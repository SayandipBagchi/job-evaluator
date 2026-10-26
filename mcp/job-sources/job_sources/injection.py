"""GR3 injection scan. Flags content that tries to steer the evaluation and
returns a neutralised copy of the text.

Two rules learned the hard way:
- Scan normalised text. Zero-width and soft-hyphen characters split a phrase so
  a regex misses it, and stripping them later reassembles the phrase for the
  scorer. So invisible characters are removed first, the instruction scan runs on
  the cleaned text, and spans refer to the cleaned text.
- Neutralise the offending sentence or segment, never the whole line. Pasted
  resumes are often one line, and removing a line removes the evidence.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

NEUTRALISED = "[content that tried to steer the evaluation was removed]"

INVISIBLE = re.compile(r"[​‌‍⁠﻿­͏᠎⁡-⁤]")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)

_TARGET = r"(?:this|the|my|me)\s+(?:candidate|applicant|resume|cv|profile|application)"
INSTRUCTION_PATTERNS = [
    r"\b(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+)?(?:of\s+)?(?:the\s+|your\s+)?(?:previous|prior|above|earlier|system)?\s*(?:instructions|prompts?|rules|guidelines|directions)\b",
    r"\byou\s+are\s+now\s+(?:a|an|the|my)?\s*(?:ai|assistant|model|bot|recruiter|screener|evaluator)\b",
    r"(?:^|\n)\s*(?:system|assistant)\s*:",
    r"\[/?INST\]|<\s*/?\s*(?:system|instructions?|prompt)\s*>",
    rf"\b(?:rate|score|rank|grade|mark|place|put)\s+{_TARGET}\b[^.\n]{{0,40}}?(?:100|10\s*/\s*10|perfect|top|highest|first|number\s+one|maximum|full\s+marks)",
    rf"\b(?:give|assign|award)\s+{_TARGET}\s+(?:a\s+)?(?:score\s+of\s+)?(?:100|full\s+marks|the\s+maximum|top\s+marks)",
    rf"\b{_TARGET}\s+is\s+(?:the\s+)?(?:perfect|ideal|best|top)\s+(?:fit|match|candidate|choice)\b",
    rf"\b(?:shortlist|hire|select|advance)\s+{_TARGET}\s+(?:immediately|now|first)\b",
    r"\b(?:note|message|instruction)s?\s+(?:to|for)\s+(?:the\s+)?(?:ai|llm|model|bot|recruiter\s+bot|screening\s+(?:tool|ai|system)|automated\s+(?:screener|system))\b",
    r"\bif\s+you\s+are\s+(?:an?\s+)?(?:ai|llm|language\s+model|bot|automated\s+(?:screener|system))\b",
    r"\b(?:ai|automated)\s+(?:reviewers?|screeners?|systems?)\s*[:,]\s*(?:score|rate|rank|shortlist|select)\b",
]
INSTRUCTION_RE = [re.compile(p, re.I) for p in INSTRUCTION_PATTERNS]
# Base64 has upper and lower case and digits; a hex hash or an id does not trip this.
BASE64_RUN = re.compile(r"\b(?=[A-Za-z0-9+/]*[A-Z])(?=[A-Za-z0-9+/]*[a-z])(?=[A-Za-z0-9+/]*\d)[A-Za-z0-9+/]{120,}={0,2}")
TOKEN = re.compile(r"[a-z][a-z0-9+#./-]*", re.I)
SEGMENT_END = re.compile(r"(?<=[.!?])\s+|\n")


@dataclass
class ScanResult:
    flags: list = field(default_factory=list)
    text: str = ""
    invisible_removed: int = 0

    @property
    def flagged(self) -> bool:
        return bool(self.flags) or self.invisible_removed > 0

    def as_dict(self) -> dict:
        return {"flagged": self.flagged, "flags": self.flags, "text": self.text,
                "invisible_removed": self.invisible_removed}


def normalise(text: str) -> tuple[str, int]:
    count = len(INVISIBLE.findall(text))
    text = INVISIBLE.sub("", text)
    return unicodedata.normalize("NFKC", text), count


def _segment_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen a match to the sentence or line segment that holds it."""
    left = 0
    for m in SEGMENT_END.finditer(text, 0, start):
        left = m.end()
    m = SEGMENT_END.search(text, end)
    right = m.start() if m else len(text)
    return left, right


def _stuffing_spans(text: str, jd_keywords: set[str]) -> list[tuple[int, int]]:
    """Segments that read as a keyword dump: repeated n-grams, or (outside a
    skills list) mostly JD keywords with no sentence structure."""
    spans = []
    pos = 0
    for m in list(SEGMENT_END.finditer(text)) + [None]:
        end = m.start() if m else len(text)
        segment = text[pos:end]
        seg_start = pos
        pos = m.end() if m else len(text)
        tokens = [t.lower() for t in TOKEN.findall(segment)]
        if len(tokens) < 20:
            continue
        bigrams: dict = {}
        for a, b in zip(tokens, tokens[1:]):
            bigrams[(a, b)] = bigrams.get((a, b), 0) + 1
        repeated = max(bigrams.values()) >= 3
        low_variety = len(set(tokens)) / len(tokens) < 0.5
        commas = segment.count(",")
        is_list = commas >= len(tokens) / 4  # a genuine comma-separated skills list
        keyword_heavy = bool(jd_keywords) and not is_list and \
            sum(1 for t in tokens if t in jd_keywords) / len(tokens) > 0.6 and segment.count(".") == 0
        if repeated or low_variety or keyword_heavy:
            spans.append((seg_start, end))
    return spans


def scan(text: str, jd_keywords: list[str] | None = None, hidden_spans: list | None = None) -> ScanResult:
    """Return flags with spans into the normalised text, and the neutralised text.

    `hidden_spans` come from the parser (white or tiny text in a DOCX) and refer to
    the original text; they are removed before normalisation."""
    for a, b in sorted((tuple(map(int, s)) for s in hidden_spans or []), reverse=True):
        text = text[:a] + "\u0000HIDDEN\u0000" + text[b:]
    text, invisible = normalise(text)
    flags: list[dict] = []

    def add(kind: str, span: tuple[int, int], widen: bool = True) -> None:
        a, b = _segment_bounds(text, *span) if widen else span
        flags.append({"kind": kind, "start": a, "end": b})

    for m in re.finditer("\u0000HIDDEN\u0000", text):
        add("hidden_text", m.span(), widen=False)
    for m in HTML_COMMENT.finditer(text):
        add("hidden_text", m.span(), widen=False)
    for rx in INSTRUCTION_RE:
        for m in rx.finditer(text):
            add("instruction", m.span())
    for m in BASE64_RUN.finditer(text):
        add("encoded_payload", m.span(), widen=False)
    keywords = {k.lower() for k in (jd_keywords or []) if len(k) > 2}
    for span in _stuffing_spans(text, keywords):
        add("keyword_stuffing", span, widen=False)

    merged: list[dict] = []
    for f in sorted(flags, key=lambda f: (f["start"], f["end"])):
        if merged and f["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], f["end"])
            if f["kind"] not in merged[-1]["kind"].split("+"):
                merged[-1]["kind"] += "+" + f["kind"]
        else:
            merged.append(dict(f))
    cleaned = text
    for f in reversed(merged):
        cleaned = cleaned[: f["start"]] + NEUTRALISED + cleaned[f["end"]:]
    if invisible and not merged:
        merged.append({"kind": "hidden_text", "start": 0, "end": 0})
    return ScanResult(flags=merged, text=cleaned, invisible_removed=invisible)
