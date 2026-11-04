"""SSRF guard and size limits for JD intake (jd_fetch).

No test here reaches the internet. Local HTTP servers bind to 127.0.0.1; where a test needs the fetcher to talk
to them, it allows exactly that loopback address and nothing else.
"""

import http.server
import ipaddress
import socket
import threading

import pytest

from job_sources import jd


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",      # cloud metadata
    "http://[fd00:ec2::254]/latest/meta-data/",      # AWS IPv6 metadata
    "http://127.0.0.1/",
    "http://localhost/",
    "http://2130706433/",                             # 127.0.0.1 as a decimal integer
    "http://0.0.0.0/",
    "http://10.0.0.5/jobs/1",
    "http://192.168.1.10/",
    "http://172.16.0.1/",
    "http://100.64.0.1/",                             # carrier-grade NAT
    "http://[::1]/",
    "http://[fe80::1]/",
    "http://[::ffff:169.254.169.254]/",               # IPv4-mapped IPv6
])
def test_internal_addresses_are_refused(url):
    out = jd.fetch(url)
    assert out["status"] == "refused" and out["code"] == "unsafe_url"
    assert "paste" in out["message"]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/jd", "gopher://x/", "javascript:alert(1)", "", "test",
                                 "https://user:pw@example.com/jd", "https://example.com:8443/jd", "https://" + "a" * 3000])
def test_bad_schemes_credentials_ports_and_length_are_refused(url):
    assert jd.fetch(url)["status"] == "refused"


def test_hostname_resolving_to_private_address_is_refused(monkeypatch):
    def fake_getaddrinfo(host, port, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))]
    monkeypatch.setattr(jd.socket, "getaddrinfo", fake_getaddrinfo)
    assert jd.fetch("https://careers.example.com/jobs/1")["status"] == "refused"


def test_public_addresses_pass_the_ip_check():
    assert jd._ip_is_public("8.8.8.8")
    assert jd._ip_is_public("2606:4700:4700::1111")
    assert not jd._ip_is_public("::ffff:10.0.0.1")


class _Handler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self):  # noqa: N802
        status, headers, body = self.routes.get(self.path, (404, {}, b""))
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    port = srv.server_address[1]
    real = jd._ip_is_public
    # Treat only this loopback test server as "public"; every other internal address stays blocked.
    monkeypatch.setattr(jd, "_ip_is_public", lambda ip: ip == "127.0.0.1" or real(ip))
    monkeypatch.setattr(jd, "ALLOWED_PORTS", {None, 80, 443, port})
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


def test_redirect_to_metadata_is_refused(local_server):
    _Handler.routes = {"/jd": (302, {"Location": "http://169.254.169.254/latest/meta-data/"}, b"")}
    out = jd.fetch(local_server + "/jd")
    assert out["status"] == "refused"


def test_oversized_response_is_capped(local_server, monkeypatch):
    monkeypatch.setattr(jd, "MAX_RESPONSE_BYTES", 1000)
    _Handler.routes = {"/big": (200, {"Content-Type": "text/html"}, b"<p>x</p>" * 1000)}
    out = jd.fetch(local_server + "/big")
    assert out["status"] == "error" and out["code"] == "too_large"


def test_allowed_page_is_fetched(local_server):
    page = b"<h1>Senior PM</h1><ul><li>You must own the roadmap</li><li>Experience leading launches is required</li></ul>"
    _Handler.routes = {"/ok": (200, {"Content-Type": "text/html"}, page)}
    out = jd.fetch(local_server + "/ok")
    assert out["status"] == "ok" and out["requirement_count"] >= 2


def test_malformed_board_api_response_is_an_error(monkeypatch):
    monkeypatch.setattr(jd, "_get", lambda url: (200, "not json"))
    out = jd.fetch("https://boards.greenhouse.io/acme/jobs/4012345")
    assert out["status"] == "error" and out["code"] == "bad_response"


def test_oversized_jd_text_is_rejected():
    out = jd.from_text("must have experience\n" * 10_000)
    assert out["status"] == "error" and out["code"] == "too_large"
