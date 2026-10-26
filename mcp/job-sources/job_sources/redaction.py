"""Blind-evaluation redaction (fairness-rules.md, context-contract.md).

`redact` returns the redacted text and a stable cand_ref. The identity it strips
is returned separately so the server can seal it on disk; it never goes back to
the scoring context.

Two kinds of error matter here and pull in opposite directions: leaving identity
in (a fairness failure) and removing evidence (an accuracy failure). Patterns are
anchored to labels and positions wherever possible so they do neither.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .scoring import find_phone_numbers

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL = re.compile(r"(?:https?://|www\.)\S+|\b(?:linkedin\.com|github\.com|twitter\.com|x\.com|instagram\.com)/\S+", re.I)
HANDLE_LABEL = re.compile(r"\b(?:linkedin|github|twitter|instagram)\s*[:\-]\s*@?/?[\w./-]+", re.I)
AT_HANDLE = re.compile(r"(?<![\w.])@[A-Za-z_][\w.]{2,30}\b")
LABEL_WORDS = (r"date\s+of\s+birth|d\.?o\.?b\.?|(?<!average\s)(?<!mean\s)(?<!median\s)age|gender|sex|marital\s+status|nationality|religion|caste|community|"
               r"father'?s\s+name|mother'?s\s+name|husband'?s\s+name|spouse|passport(?:\s+no\.?)?|blood\s+group|"
               r"address|permanent\s+address|current\s+address|residence|pin\s*code|pincode|postcode|zip(?:\s+code)?|"
               r"visa\s+status|personal\s+statement|personal\s+details")
# A labelled personal field anywhere in a line, up to the next separator.
LABELLED = re.compile(rf"\b(?:{LABEL_WORDS})[ \t]*(?::|\s-\s)[^\n.;|•]*", re.I)
DATE = r"\d{1,2}[/.\- ](?:\d{1,2}|[A-Za-z]{3,9})[/.\- ]\d{2,4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}"
DOB = re.compile(rf"\b(?:born(?:\s+on)?|b\.)\s*[:\-]?\s*(?:{DATE})", re.I)
RELATION_LINE = re.compile(r"\b[SDW]\s*/\s*O\b\.?\s*[:\-]?\s*[A-Z][\w.' ]{1,40}")
AGE_PHRASE = re.compile(r"\b(?:aged?\s+\d{2}|\d{2}\s*(?:years?|yrs?)\s+old)\b", re.I)
FAMILY_PHRASE = re.compile(r"(?:\bhappily\s+married|married\s+(?:with|to)\s+\w+|(?:father|mother|parent)\s+of\s+(?:one|two|three|four|\d+)\b[^.;\n]*|"
                           r"\(?\s*\bmother\s+tongue\s*\)?|\bnative\s+of\s+[A-Z]\w+)", re.I)
PRONOUN_TAG = re.compile(r"\(\s*(?:he|she|they)\s*/\s*(?:him|her|them)(?:\s*/\s*\w+)?\s*\)", re.I)
# Lowercase pronouns anywhere, or capitalised at a sentence start. Not all-caps: HER and SHE are often acronyms.
PRONOUNS = re.compile(r"\b(?:he|she|him|her|his|hers|himself|herself)\b|(?:^|(?<=[.!?:]\s)|(?<=\n))(?:He|She|His|Her)\b", re.M)
HONORIFIC = re.compile(r"\b(?:Mr|Mrs|Ms|Mx|Miss|Shri|Smt|Kumari|Sri)\.?\s+(?=[A-Z][a-z]|\[)")
PHOTO_TOKEN = re.compile(r"\[\s*(?:photo|photograph|picture|headshot|image)\s*\]|^\s*(?:photo|photograph|headshot)\s*$", re.I | re.M)
UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b")
YEAR = re.compile(r"\b(?:19[4-9]\d|20[0-4]\d)\b")

HEADINGS = (r"education|academic(?:s| qualifications| background)?|qualifications|experience|work experience|"
            r"professional experience|employment(?: history)?|work history|career history|internships?|"
            r"volunteering|volunteer experience|skills|technical skills|projects|certifications?|summary|profile|"
            r"professional summary|objective|achievements|awards|publications|interests|languages(?: known)?|"
            r"leadership|activities|extracurriculars?|references|personal details|contact")
SECTION_HEAD = re.compile(rf"^\s*(?:{HEADINGS})\s*:?\s*$", re.I)
EDUCATION_HEAD = re.compile(r"^\s*(?:education|academic(?:s| qualifications| background)?|qualifications)\s*:?\s*$", re.I)
INLINE_EDUCATION = re.compile(r"\b(?:education|qualifications?)\s*:[^\n]*?(?=\b(?:experience|skills|projects|summary)\s*:|\n|$)", re.I)
TITLE_WORDS = {"resume", "résumé", "curriculum vitae", "cv", "profile", "bio-data", "biodata", "personal profile"}
CREDENTIALS = r"(?:MBA|PhD|Ph\.D\.?|CFA|CPA|CA|PMP|MSc|BSc|BA|MA|MD|PE|CISSP|ACCA|FRM|B\.Tech|M\.Tech)"
NAME_TOKEN = r"[A-Z][a-zA-Z'\-]+|[A-Z]\.?"
NAME_RE = re.compile(rf"^\s*((?:{NAME_TOKEN})(?:\s+(?:{NAME_TOKEN})){{1,3}})(?=\s*(?:$|[,(|.]|\s-\s|\s{{2,}}|{CREDENTIALS}\b))")
# Words after a name part that mean it is an organisation or an award, not the person.
ORG_FOLLOWERS = (r"(?:\s*&|\s+(?:and\s+Co|Industries|Group|Ltd|Limited|Inc|LLP|LLC|Corp|Corporation|Fellowship|"
                 r"Foundation|Scholarship|Award|Prize|University|College|Institute|Bank|Capital|Partners|Labs?|"
                 r"Technologies|Systems|Holdings|Motors|Steel|Consultancy))")

PLACEHOLDER = {
    "name": "[CANDIDATE]", "email": "[EMAIL]", "phone": "[PHONE]", "url": "[LINK]", "dob": "[DOB]",
    "personal": "[PERSONAL DETAIL]", "age": "[AGE]", "pronoun": "[they]", "photo": "[PHOTO REMOVED]",
    "address": "[ADDRESS]", "grad_year": "[YEAR]",
}


@dataclass
class Redaction:
    cand_ref: str
    text: str
    identity: dict = field(default_factory=dict)
    removed: dict = field(default_factory=dict)

    def public(self) -> dict:
        """What may go back to the model: no identity values, only counts."""
        return {"cand_ref": self.cand_ref, "text": self.text, "redacted": True, "removed_counts": self.removed}


def cand_ref_for(raw_text: str) -> str:
    normalised = re.sub(r"\s+", " ", raw_text).strip()
    return "cand_" + hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:8]


def _title_case(s: str) -> str:
    return " ".join(w.capitalize() if w.isupper() and len(w) > 1 else w for w in s.split())


def _guess_name(text: str) -> str | None:
    """The name is usually the first non-title line, or the leading tokens of a one-line resume."""
    for line in text.splitlines()[:6]:
        stripped = line.strip().strip("#*").strip()
        if not stripped:
            continue
        if stripped.lower().rstrip(":") in TITLE_WORDS:
            continue
        if SECTION_HEAD.match(stripped):
            return None
        head = stripped[:60]
        candidate = _title_case(head) if head.split(",")[0].split("(")[0].isupper() else head
        m = NAME_RE.match(candidate)
        if m:
            name = m.group(1).strip().rstrip(".")
            if name.lower() in TITLE_WORDS or any(ch.isdigit() for ch in name):
                return None
            return name
        return None
    return None


def _redact_name(text: str, name: str, counts: dict) -> str:
    n = 0
    full = re.compile(r"\s+".join(re.escape(p) for p in name.split()), re.I)
    text, k = full.subn(PLACEHOLDER["name"], text)
    n += k
    for part in (p for p in name.split() if len(p.rstrip(".")) > 1):
        rx = re.compile(rf"\b{re.escape(part)}\b(?!{ORG_FOLLOWERS})", re.I)
        text, k = rx.subn(PLACEHOLDER["name"], text)
        n += k
    if n:
        counts["name"] = counts.get("name", 0) + n
    return text


def _redact_education_years(text: str, counts: dict) -> str:
    lines = text.split("\n")
    in_edu = False
    for i, line in enumerate(lines):
        if EDUCATION_HEAD.match(line):
            in_edu = True
            continue
        if SECTION_HEAD.match(line):
            in_edu = False
            continue
        if in_edu:
            new, k = YEAR.subn(PLACEHOLDER["grad_year"], line)
            if k:
                counts["grad_year"] = counts.get("grad_year", 0) + k
                lines[i] = new
    text = "\n".join(lines)

    def inline(m: re.Match) -> str:
        new, k = YEAR.subn(PLACEHOLDER["grad_year"], m.group())
        if k:
            counts["grad_year"] = counts.get("grad_year", 0) + k
        return new

    text = INLINE_EDUCATION.sub(inline, text)
    text, k = re.subn(r"\b(class of|graduated(?: in)?|batch of|passed out(?: in)?|graduating)\s+(?:19|20)\d{2}\b",
                      lambda m: f"{m.group(1)} {PLACEHOLDER['grad_year']}", text, flags=re.I)
    if k:
        counts["grad_year"] = counts.get("grad_year", 0) + k
    return text


def redact(raw_text: str, known_name: str | None = None) -> Redaction:
    counts: dict = {}
    identity: dict = {}
    text = raw_text

    def sub(pattern: re.Pattern, kind: str, value_key: str | None = None) -> None:
        nonlocal text
        found = [m.group() for m in pattern.finditer(text) if m.group().strip()]
        if not found:
            return
        if value_key:
            identity.setdefault(value_key, []).extend(found)
        text = pattern.sub(lambda m: PLACEHOLDER[kind] if m.group().strip() else m.group(), text)
        counts[kind] = counts.get(kind, 0) + len(found)

    # Contact details first: the name pass must not rewrite the inside of an email or a handle.
    sub(EMAIL, "email", "emails")
    links = [m.group() for m in URL.finditer(text)] + [m.group() for m in HANDLE_LABEL.finditer(text)]
    if links:
        identity["profile_links"] = [l for l in links if re.search(r"linkedin|github", l, re.I)]
    sub(URL, "url")
    sub(HANDLE_LABEL, "url")
    sub(AT_HANDLE, "url")

    name = known_name or _guess_name(raw_text)
    if name:
        identity["name"] = name
        text = _redact_name(text, name, counts)

    phone_spans = find_phone_numbers(text)
    if phone_spans:
        identity["phones"] = [text[a:b] for a, b in phone_spans]
        for a, b in reversed(phone_spans):
            text = text[:a] + PLACEHOLDER["phone"] + text[b:]
        counts["phone"] = len(phone_spans)

    sub(PHOTO_TOKEN, "photo")
    sub(DOB, "dob")
    sub(LABELLED, "personal")
    sub(RELATION_LINE, "personal")
    sub(UK_POSTCODE, "address")
    sub(AGE_PHRASE, "age")
    sub(FAMILY_PHRASE, "personal")
    sub(PRONOUN_TAG, "pronoun")
    sub(HONORIFIC, "personal")
    sub(PRONOUNS, "pronoun")
    text = _redact_education_years(text, counts)

    return Redaction(cand_ref=cand_ref_for(raw_text), text=text, identity=identity, removed=counts)
