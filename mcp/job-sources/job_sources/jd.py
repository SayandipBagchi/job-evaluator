"""JD intake: public job-board APIs first, then a plain page fetch, then a paste.

Greenhouse and Lever publish job postings through public JSON APIs, so those
URLs never need scraping. Anything that refuses a fetch is reported as blocked
and the skill asks the user for the text. There is no retry through another route.
"""

from __future__ import annotations

import html
import http.client
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from .rubric import text_hash

USER_AGENT = "job-evaluator/0.1 (+recruiter JD intake)"
TIMEOUT = 15  # seconds, per connect and per read
MAX_URL_CHARS = 2048
MAX_RESPONSE_BYTES = 2_000_000  # a JD page or posting API response is far smaller than this
MAX_REDIRECTS = 5
MAX_JD_CHARS = 100_000
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443}

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


class UnsafeURL(ValueError):
    """The URL points somewhere a JD fetch must never go (SSRF guard)."""


def _ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%", 1)[0])
    if isinstance(addr, ipaddress.IPv6Address):
        mapped = addr.ipv4_mapped or addr.sixtofour
        if mapped is not None:
            addr = mapped
        elif addr.teredo is not None:
            addr = addr.teredo[1]
    # is_global excludes loopback, RFC 1918, link-local (169.254.0.0/16 incl. cloud metadata, fe80::/10),
    # unique-local (fc00::/7), CGNAT (100.64.0.0/10), unspecified, reserved and documentation ranges.
    return addr.is_global and not addr.is_multicast


def check_url(url: str) -> str:
    """Validate a user-supplied URL before any network access. Returns the URL or raises UnsafeURL.

    Only http(s) on the default ports, a real hostname, no credentials in the URL, and every address the
    hostname resolves to must be public. The connection itself re-checks the peer address (DNS rebinding).
    """
    if not isinstance(url, str) or not url.strip():
        raise UnsafeURL("No URL given")
    url = url.strip()
    if len(url) > MAX_URL_CHARS:
        raise UnsafeURL(f"URL longer than {MAX_URL_CHARS} characters")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURL("Only http and https URLs can be fetched")
    if parts.username or parts.password:
        raise UnsafeURL("URLs with embedded credentials are not fetched")
    host = parts.hostname
    if not host:
        raise UnsafeURL("URL has no host")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeURL("URL has an invalid port") from exc
    if port not in ALLOWED_PORTS:
        raise UnsafeURL("Only the default http/https ports are allowed")
    try:
        infos = socket.getaddrinfo(host, port or (443 if parts.scheme.lower() == "https" else 80), proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise UnsafeURL(f"Host could not be resolved: {host}") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses or not all(_ip_is_public(a) for a in addresses):
        raise UnsafeURL("Host resolves to a private, loopback, link-local or metadata address")
    return url


def _check_peer(sock) -> None:
    peer = sock.getpeername()[0]
    if not _ip_is_public(peer):
        sock.close()
        raise UnsafeURL("Connection reached a non-public address")


class _GuardedHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        super().connect()
        _check_peer(self.sock)


class _GuardedHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        super().connect()  # TLS handshake runs on the already-connected socket
        _check_peer(self.sock)


class _GuardedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_GuardedHTTPConnection, req)


class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_GuardedHTTPSConnection, req, context=self._context)


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)  # every hop is validated, so a public URL cannot bounce to an internal one
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(
    _GuardedHTTPHandler, _GuardedHTTPSHandler, _GuardedRedirectHandler,
    urllib.request.ProxyHandler({}),  # never route through an environment proxy
)


def _get(url: str) -> tuple[int, str]:
    """GET a URL through the SSRF guard. Returns (status, body); status 0 with a message on network errors.

    Raises UnsafeURL when the URL, a redirect target or the connected peer is not a public address.
    """
    check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json"})
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as resp:
            body = resp.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                return 413, ""
            return resp.status, body.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, UnsafeURL):
            raise exc.reason
        return 0, str(exc.reason)
    except (TimeoutError, socket.timeout, OSError, http.client.HTTPException) as exc:
        if isinstance(exc, UnsafeURL):
            raise
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
    if len(text) > MAX_JD_CHARS:
        return {"status": "error", "code": "too_large", "source": source,
                "message": f"JD text is longer than {MAX_JD_CHARS} characters. Ask for the job description itself, not a whole site."}
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
    try:
        return _fetch(url)
    except UnsafeURL as exc:
        return {"status": "refused", "source": str(url)[:200], "code": "unsafe_url", "message":
                f"{exc}. Only public http(s) job pages are fetched. Ask the user to paste the JD or attach it."}
    except (json.JSONDecodeError, AttributeError, TypeError) as exc:
        return {"status": "error", "source": str(url)[:200], "code": "bad_response",
                "message": f"The job board returned an unexpected response ({type(exc).__name__}). Ask the user to paste the JD."}


def _fetch(url: str) -> dict:
    # Every network call goes through _get, which runs check_url first; nothing here opens a socket itself.
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
    if status == 413:
        return {"status": "error", "source": url, "http_status": status, "code": "too_large",
                "message": f"The page is larger than {MAX_RESPONSE_BYTES // 1_000_000} MB. Ask the user to paste the JD."}
    if status in (401, 403, 429, 451) or (status == 0 and body):
        return {"status": "blocked", "source": url, "http_status": status,
                "message": "This page could not be fetched. Ask the user to paste the JD or attach it."}
    if status != 200 or not body:
        return {"status": "error", "source": url, "http_status": status,
                "message": "Fetch failed. Ask the user to paste the JD or attach it."}
    text = html_to_text(body)
    result = from_text(text, source=url)
    if result.get("thin"):
        result["message"] = "Very few requirements found; the page may be rendered by script. Ask for the text."
    return result
