"""Greenhouse Harvest API adapter (https://developers.greenhouse.io/harvest.html).

Auth is HTTP Basic with the API key as the username and an empty password. The
key needs read access to Jobs, Applications and Candidates, and write access to
Candidates only if notes are wanted. Writes also need an On-Behalf-Of user id.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .base import AtsAdapter, AtsError, ConfirmationRequired

BASE = "https://harvest.greenhouse.io/v1"
TIMEOUT = 30


class GreenhouseAdapter(AtsAdapter):
    name = "greenhouse"

    def __init__(self, api_key: str | None = None, opener=None):
        self.api_key = api_key or os.environ.get("GREENHOUSE_API_KEY", "")
        if not self.api_key:
            raise AtsError("not_configured", "Set GREENHOUSE_API_KEY to use the Greenhouse adapter.")
        self._open = opener or urllib.request.urlopen

    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None,
                 headers: dict | None = None, raw: bool = False):
        url = path if path.startswith("http") else f"{BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        token = base64.b64encode(f"{self.api_key}:".encode()).decode()
        hdrs = {"Authorization": f"Basic {token}", "Accept": "application/json", **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        if not url.startswith(BASE):
            hdrs.pop("Authorization")  # attachment URLs are pre-signed; never send the key elsewhere
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with self._open(req, timeout=TIMEOUT) as resp:
                payload = resp.read()
                link = resp.headers.get("Link", "") if hasattr(resp, "headers") else ""
        except urllib.error.HTTPError as exc:
            code = {401: "unauthorised", 403: "forbidden", 404: "not_found", 429: "rate_limited"}.get(exc.code, "http_error")
            raise AtsError(code, f"Greenhouse returned HTTP {exc.code} for {path}") from exc
        except urllib.error.URLError as exc:
            raise AtsError("unreachable", f"Greenhouse could not be reached: {exc.reason}") from exc
        if raw:
            return payload
        return json.loads(payload or b"null"), link

    def list_jobs(self, status: str = "open") -> list[dict]:
        data, _ = self._request("GET", "/jobs", {"status": status, "per_page": 100})
        return [{"job_id": str(j["id"]), "name": j.get("name"), "status": j.get("status")} for j in data or []]

    def list_applicants(self, job_id: str, page: int = 1, per_page: int = 100) -> dict:
        data, link = self._request("GET", "/applications",
                                   {"job_id": job_id, "status": "active", "per_page": per_page, "page": page})
        rows = []
        for app in data or []:
            resumes = [a for a in app.get("attachments", []) if a.get("type") == "resume"]
            rows.append({
                "application_id": str(app["id"]),
                "candidate_id": str(app.get("candidate_id")),
                "stage": (app.get("current_stage") or {}).get("name"),
                "has_resume": bool(resumes),
                "profile_url": f"https://app.greenhouse.io/people/{app.get('candidate_id')}?application_id={app['id']}",
            })
        return {"page": page, "applications": rows, "has_more": 'rel="next"' in (link or "")}

    def get_resume(self, application_id: str, dest_dir: str) -> str:
        if not re.fullmatch(r"\d+", str(application_id)):
            raise AtsError("bad_id", "application_id must be numeric")
        app, _ = self._request("GET", f"/applications/{application_id}")
        resumes = [a for a in app.get("attachments", []) if a.get("type") == "resume"]
        if not resumes:
            raise AtsError("no_resume", f"Application {application_id} has no resume attachment")
        latest = sorted(resumes, key=lambda a: a.get("created_at", ""))[-1]
        suffix = Path(latest.get("filename", "resume.pdf")).suffix.lower() or ".pdf"
        if suffix not in {".pdf", ".docx", ".txt"}:
            raise AtsError("unsupported_type", f"Resume attachment type {suffix} is not supported")
        blob = self._request("GET", latest["url"], raw=True)
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"gh_{application_id}{suffix}"
        path.write_bytes(blob)
        return str(path)

    def add_note(self, application_id: str, text: str, confirm: bool, on_behalf_of: str | None = None) -> dict:
        if not confirm:
            raise ConfirmationRequired({"application_id": application_id, "note": text})
        if not on_behalf_of:
            raise AtsError("missing_user", "Greenhouse notes need the On-Behalf-Of user id of the recruiter")
        app, _ = self._request("GET", f"/applications/{application_id}")
        candidate_id = app.get("candidate_id")
        body = {"user_id": int(on_behalf_of), "body": text, "visibility": "private"}
        data, _ = self._request("POST", f"/candidates/{candidate_id}/activity_feed/notes", body=body,
                                headers={"On-Behalf-Of": str(on_behalf_of)})
        return {"status": "written", "note_id": (data or {}).get("id"), "candidate_id": str(candidate_id)}
