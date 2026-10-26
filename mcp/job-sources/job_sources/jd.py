"""JD intake: public job-board APIs first, then a plain page fetch, then a paste.

Greenhouse and Lever publish job postings through public JSON APIs, so those
URLs never need scraping. Anything that refuses a fetch is reported as blocked
and the skill asks the user for the text. There is no retry through another route.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser

from .rubric import text_hash

USER_AGENT = "job-evaluator/0.1 (+recruiter JD intake)"
TIMEOUT = 20

GREENHOUSE_BOARD = re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", re.I)
LEVER_POSTING = re.compile(r"jobs\.lever\.co/([\w-]+)/([0-9a-f-]{36})", re.I)

REQUIREMENT_HINT = re.compile(
    r"\b(?:experience|years?|required|must|should|ability|proficien|knowledge|familiar|degree|"
    r"skills?|track record|strong|own|lead|manage|deliver|build|partner|work with|understanding)\b",
    re.I,
)
BULLET = re.compile(r"^\s*(?:[-*•▪◦·]|\d+[.)])\s+(.+)$")


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "ul", "ol"}
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(html.unescape(markup))
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - URL comes from the user
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, TimeoutError) as exc:
        return 0, str(exc)


def extract_requirements(text: str) -> list[str]:
    reqs: list[str] = []
    for line in text.splitlines():
        m = BULLET.match(line)
        candidate = (m.group(1) if m else line).strip()
        if 12 <= len(candidate) <= 300 and REQUIREMENT_HINT.search(candidate):
            if m or re.search(r"\b(?:must|required|should|you have|you will)\b", candidate, re.I):
                reqs.append(candidate)
    seen, out = set(), []
    for r in reqs:
        key = r.lower()
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def keywords(text: str) -> list[str]:
    stop = set("the and for with you our are will that this have from your who can into about their they "
               "able work team role more than what also such well within across".split())
    words = re.findall(r"[a-z][a-z+#.]{2,}", text.lower())
    counts: dict[str, int] = {}
    for w in words:
        if w not in stop:
            counts[w] = counts.get(w, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:60]]


def from_text(text: str, title: str | None = None, source: str = "pasted") -> dict:
    text = text.strip()
    if not title:
        first = next((l.strip() for l in text.splitlines() if l.strip()), "")
        title = first[:120]
    reqs = extract_requirements(text)
    return {
        "status": "ok",
        "source": source,
        "title": title,
        "text": text,
        "jd_hash": text_hash(text),
        "requirements": reqs,
        "requirement_count": len(reqs),
        "thin": len(reqs) < 3,
        "keywords": keywords(text),
    }


def fetch(url: str) -> dict:
    gh = GREENHOUSE_BOARD.search(url)
    if gh:
        status, body = _get(f"https://boards-api.greenhouse.io/v1/boards/{gh.group(1)}/jobs/{gh.group(2)}")
        if status == 200:
            data = json.loads(body)
            return from_text(html_to_text(data.get("content", "")), data.get("title"), source=url)
    lv = LEVER_POSTING.search(url)
    if lv:
        status, body = _get(f"https://api.lever.co/v0/postings/{lv.group(1)}/{lv.group(2)}")
        if status == 200:
            data = json.loads(body)
            parts = [data.get("descriptionPlain", "")]
            for block in data.get("lists", []):
                parts.append(block.get("text", ""))
                parts.append(html_to_text(block.get("content", "")))
            parts.append(data.get("additionalPlain", ""))
            return from_text("\n".join(p for p in parts if p), data.get("text"), source=url)

    status, body = _get(url)
    if status in (401, 403, 429, 451) or (status == 0 and body):
        return {"status": "blocked", "source": url, "http_status": status,
                "message": "This page could not be fetched. Ask the user to paste the JD or attach it."}
    if status != 200 or not body:
        return {"status": "error", "source": url, "http_status": status,
                "message": "Fetch failed. Ask the user to paste the JD or attach it."}
    text = html_to_text(body)
    result = from_text(text, source=url)
    if result["thin"]:
        result["message"] = "Very few requirements found; the page may be rendered by script. Ask for the text."
    return result
