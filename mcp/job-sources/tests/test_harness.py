import inspect
import io
import json
import urllib.request

import pytest

import server
from job_sources import audit
from job_sources.adapters import ConfirmationRequired, GreenhouseAdapter


class FakeResponse(io.BytesIO):
    def __init__(self, payload, headers=None):
        super().__init__(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, routes):
        self.routes = routes
        self.requests: list[urllib.request.Request] = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        for prefix, payload in self.routes.items():
            if req.full_url.startswith(prefix):
                return FakeResponse(payload)
        raise AssertionError(f"unexpected request {req.full_url}")


APP = {"id": 77, "candidate_id": 501, "current_stage": {"name": "Application Review"},
       "attachments": [{"type": "resume", "filename": "cv.txt", "url": "https://s3.example.com/cv.txt?sig=abc",
                        "created_at": "2026-10-01"}]}


def test_write_tools_require_confirm():
    for name in server.WRITE_TOOLS:
        if name.startswith("ats_"):
            params = inspect.signature(getattr(server, name)).parameters
            assert "confirm" in params and params["confirm"].default is False, name


def test_every_declared_tool_exists():
    for name in server.READ_TOOLS + server.WRITE_TOOLS:
        assert callable(getattr(server, name))


@pytest.mark.parametrize("key", ["k", None])
def test_add_note_without_confirm_returns_preview(monkeypatch, key):
    if key:
        monkeypatch.setenv("GREENHOUSE_API_KEY", key)
    else:
        monkeypatch.delenv("GREENHOUSE_API_KEY", raising=False)
    for confirm in (False, "true", 1):
        out = server.ats_add_note("77", "Shortlisted: card launch evidence", confirm=confirm)
        assert out["status"] == "confirmation_required", confirm
        assert out["preview"]["note"] == "Shortlisted: card launch evidence"


def test_greenhouse_note_refuses_without_confirm():
    gh = GreenhouseAdapter(api_key="k", opener=FakeOpener({}))
    with pytest.raises(ConfirmationRequired):
        gh.add_note("77", "x", confirm=False)


def test_greenhouse_lists_applicants_without_contact_details():
    opener = FakeOpener({"https://harvest.greenhouse.io/v1/applications?": [APP]})
    gh = GreenhouseAdapter(api_key="k", opener=opener)
    out = gh.list_applicants("123")
    row = out["applications"][0]
    assert row == {"application_id": "77", "candidate_id": "501", "stage": "Application Review", "has_resume": True,
                   "profile_url": "https://app.greenhouse.io/people/501?application_id=77"}
    assert opener.requests[0].get_header("Authorization").startswith("Basic ")


def test_greenhouse_never_sends_key_to_attachment_host(tmp_path):
    opener = FakeOpener({
        "https://harvest.greenhouse.io/v1/applications/77": APP,
        "https://s3.example.com/": b"Experience\nPM at Acme (2020 - 2024)",
    })
    gh = GreenhouseAdapter(api_key="secret", opener=opener)
    path = gh.get_resume("77", str(tmp_path))
    attachment_req = opener.requests[-1]
    assert attachment_req.full_url.startswith("https://s3.example.com/")
    assert attachment_req.get_header("Authorization") is None
    assert open(path).read().startswith("Experience")


def test_missing_key_is_reported(monkeypatch):
    monkeypatch.delenv("GREENHOUSE_API_KEY", raising=False)
    out = server.ats_list_jobs()
    assert out["status"] == "error" and out["code"] == "not_configured"


def test_lever_stub_says_not_implemented():
    out = server.ats_list_jobs(provider="lever")
    assert out["code"] == "not_implemented"


def test_prepare_resume_returns_only_redacted_text(resume_text):
    out = server.prepare_resume(text=resume_text)
    assert out["redacted"] and "Priya" not in out["text"] and "@" not in out["text"]
    assert out["cand_ref"] == server.prepare_resume(text=resume_text)["cand_ref"]
    rejoined = server.identity_rejoin([out["cand_ref"]])[out["cand_ref"]]
    assert rejoined["name"] == "Priya Raman"
    assert "emails" not in rejoined and "phones" not in rejoined


def test_resume_parse_does_not_return_text(tmp_path, resume_text):
    f = tmp_path / "cv.txt"
    f.write_text(resume_text)
    out = server.resume_parse(str(f))
    assert "text" not in out and out["parse_quality"] >= 0.9


def test_audit_log_rejects_personal_content(isolated_logs):
    base = {"role_id": "senior-pm", "rubric_hash": "a" * 64, "cand_ref": "cand_0000abcd", "resume_hash": "b" * 64,
            "score": 80.0, "confidence": 0.8, "band": "Shortlist", "jurisdictions": ["IN"], "guardrails_not_run": []}
    assert server.eval_log(base)["status"] == "logged"
    for bad in ({**base, "resume_text": "..."}, {**base, "candidate_name": "Priya"}, {**base, "Name": "Priya"},
                {**base, "source": "mail me at a@b.com"}, {**base, "source": "call +91 98450 12345"},
                {**base, "band": "Reject"}, {**base, "jurisdictions": []},
                {k: v for k, v in base.items() if k != "jurisdictions"}):
        assert server.eval_log(bad)["status"] == "rejected", bad
    lines = (isolated_logs / "evaluations.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["human_decision"] is None


def test_human_decision_recorded(isolated_logs):
    out = server.record_human_decision("senior-pm", "cand_0000abcd", "a" * 64, "override_up", "recruiter-1", "strong portfolio")
    assert out["status"] == "logged"
    assert server.record_human_decision("senior-pm", "cand_0000abcd", "a" * 64, "auto-reject", "x")["status"] == "rejected"
    assert server.record_human_decision("senior-pm", "cand_0000abcd", "a" * 64, "advance", "r1",
                                        "call her on +91 98450 12345")["status"] == "rejected"


def test_prune_removes_old_records(isolated_logs):
    import json as _json
    isolated_logs.mkdir(parents=True, exist_ok=True)
    old = {"event": "evaluation", "timestamp": "2020-01-01T00:00:00+00:00"}
    new = {"event": "evaluation", "timestamp": "2999-01-01T00:00:00+00:00"}
    (isolated_logs / "evaluations.jsonl").write_text(_json.dumps(old) + "\n" + _json.dumps(new) + "\n")
    out = server.eval_log_prune(180)
    assert out["records_removed"] == 1
    assert len((isolated_logs / "evaluations.jsonl").read_text().splitlines()) == 1


def test_score_and_band_tool_rejects_invalid_rubric(rubric):
    bad = {**rubric, "signals": rubric["signals"][:2]}
    assert server.score_and_band(bad, {}, 0.9, False)["code"] == "invalid_rubric"


def test_scorer_cannot_set_its_own_parse_quality(rubric):
    card = {"criteria": [{"id": s["id"], "score": 4, "status": "met", "evidence": "x"} for s in rubric["signals"]],
            "gates": [{"id": "g1", "status": "passed", "evidence": "x"}], "parse_quality": 1.0, "injection_flagged": False}
    # The prepared values win: an unreadable resume is Review whatever the scorer claims.
    assert server.score_and_band(rubric, card, 0.2, False)["band"] == "Review"
    assert server.score_and_band(rubric, card, 0.95, True)["confidence"] < server.score_and_band(rubric, card, 0.95, False)["confidence"]
