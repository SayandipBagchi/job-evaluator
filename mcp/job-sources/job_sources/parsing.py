"""Resume parsing with a parse-quality score (GR2).

TXT and MD need nothing. PDF needs `pypdf`; DOCX needs `python-docx`. A missing
library is reported, never guessed around.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SECTION_KINDS = {
    "summary": r"summary|profile|about",
    "experience": r"experience|employment|work history|professional experience",
    "education": r"education|academic|qualifications",
    "skills": r"skills|technical skills|core competencies",
    "projects": r"projects",
    "certifications": r"certifications?|licen[cs]es",
}
HEAD_RE = {k: re.compile(rf"^\s*(?:{v})\s*:?\s*$", re.I | re.M) for k, v in SECTION_KINDS.items()}
DATE_RANGE = re.compile(
    r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+)?((?:19|20)\d{2})\s*(?:-|–|—|to|until)\s*"
    r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+)?((?:19|20)\d{2}|present|current|now)",
    re.I,
)


@dataclass
class Parsed:
    text: str
    parse_quality: float
    sections: list = field(default_factory=list)
    roles: list = field(default_factory=list)
    hidden_spans: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    source: str = "pasted"

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "text": self.text,
            "parse_quality": self.parse_quality,
            "sections": self.sections,
            "roles": self.roles,
            "hidden_spans": self.hidden_spans,
            "parse_notes": self.notes,
        }


class ParseError(Exception):
    pass


def _read_pdf(path: Path) -> tuple[str, list]:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise ParseError("PDF parsing needs pypdf: pip install pypdf") from exc
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages), []


def _read_docx(path: Path) -> tuple[str, list]:
    try:
        import docx  # type: ignore
        from docx.shared import Pt  # type: ignore
    except ImportError as exc:
        raise ParseError("DOCX parsing needs python-docx: pip install python-docx") from exc
    document = docx.Document(str(path))
    parts: list[str] = []
    hidden: list[tuple[int, int]] = []
    offset = 0
    for para in document.paragraphs:
        line = ""
        for run in para.runs:
            start = offset + len(line)
            line += run.text
            colour = run.font.color.rgb if run.font.color is not None and run.font.color.type is not None else None
            tiny = run.font.size is not None and run.font.size < Pt(4)
            white = colour is not None and str(colour).upper() in {"FFFFFF", "FEFEFE"}
            if (tiny or white or run.font.hidden) and run.text.strip():
                hidden.append((start, start + len(run.text)))
        parts.append(line)
        offset += len(line) + 1
    return "\n".join(parts), hidden


def read_file(path: str) -> tuple[str, list, str]:
    p = Path(path)
    if not p.is_file():
        raise ParseError(f"file not found: {path}")
    suffix = p.suffix.lower()
    if suffix in {".txt", ".md", ".text"}:
        return p.read_text(encoding="utf-8", errors="replace"), [], p.name
    if suffix == ".pdf":
        text, hidden = _read_pdf(p)
        return text, hidden, p.name
    if suffix == ".docx":
        text, hidden = _read_docx(p)
        return text, hidden, p.name
    raise ParseError(f"unsupported file type: {suffix}. Use PDF, DOCX or TXT")


def _sections(text: str) -> list[dict]:
    found = []
    for kind, rx in HEAD_RE.items():
        for m in rx.finditer(text):
            found.append((m.start(), kind))
    found.sort()
    out = []
    for i, (start, kind) in enumerate(found):
        end = found[i + 1][0] if i + 1 < len(found) else len(text)
        out.append({"kind": kind, "start": start, "end": end})
    return out


def _roles(text: str) -> list[dict]:
    roles = []
    for m in DATE_RANGE.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line = text[line_start: len(text) if line_end == -1 else line_end].strip()
        end = m.group(4)
        roles.append({
            "line": line[:160],
            "start": m.group(2),
            "end": None if end.lower() in {"present", "current", "now"} else end,
            "span": [line_start, len(text) if line_end == -1 else line_end],
        })
    return roles


def quality(text: str, sections: list, roles: list) -> tuple[float, list]:
    notes = []
    stripped = text.strip()
    if len(stripped) < 80:
        return 0.0, ["almost no text extracted: likely an image-only resume"]
    printable = sum(1 for ch in stripped if ch.isprintable() or ch in "\n\t") / len(stripped)
    words = re.findall(r"[A-Za-z]{2,}", stripped)
    real_word_ratio = len(words) / max(1, len(stripped.split()))
    score = 0.0
    score += 0.25 if len(stripped) >= 600 else 0.25 * len(stripped) / 600
    score += 0.2 * min(1.0, printable)
    score += 0.15 * min(1.0, real_word_ratio / 0.8)
    kinds = {s["kind"] for s in sections}
    # Pasted text often has no headings; a recovered role history counts as an experience section.
    score += 0.2 if ("experience" in kinds or len(roles) >= 1) else 0.0
    score += 0.05 if "education" in kinds else 0.0
    score += 0.05 if "skills" in kinds else 0.0
    score += 0.1 if roles else 0.0
    if "experience" not in kinds and not roles:
        notes.append("no experience section or role history found")
    if not roles:
        notes.append("no employment date ranges recovered")
    if printable < 0.95:
        notes.append("unusual characters in extracted text")
    return round(min(1.0, score), 3), notes


def parse_text(text: str, source: str = "pasted", hidden_spans: list | None = None) -> Parsed:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    sections = _sections(text)
    roles = _roles(text)
    q, notes = quality(text, sections, roles)
    return Parsed(text=text, parse_quality=q, sections=sections, roles=roles,
                  hidden_spans=[list(s) for s in hidden_spans or []], notes=notes, source=source)


def parse_file(path: str) -> Parsed:
    text, hidden, name = read_file(path)
    return parse_text(text, source=name, hidden_spans=hidden)
