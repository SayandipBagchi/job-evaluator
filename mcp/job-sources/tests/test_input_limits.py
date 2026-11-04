"""Oversize input: structured errors, and no quadratic regex on long text (formerly hung >10 s on 200k chars)."""

import time

import server
from job_sources import audit, redaction, scoring


def test_server_tools_reject_oversize_text():
    big = "A" * (server.MAX_TEXT + 1)
    for out in (server.redact(big), server.prepare_resume(text=big), server.injection_scan(big),
                server.jd_from_text(big), server.validate_scorecard({}, {}, big)):
        assert out["status"] == "error" and out["code"] == "too_large", out
    assert server.check_output_wording("A" * (server.MAX_RENDERED + 1))["code"] == "too_large"


def test_long_inputs_stay_fast():
    for text in ("A" * 200_000, "a.b+c" * 40_000, ("word " * 40_000)):
        start = time.monotonic()
        redaction.redact(text)
        scoring.output_wording_problems(text)
        audit._personal_content(text)
        assert time.monotonic() - start < 3, "regex blow-up on long input"


def test_email_detection_still_works():
    red = redaction.redact("Jane Doe\njane.doe+cv@example.co.uk | (a@b.com)\nExperience\nPM at Acme")
    assert "example.co.uk" not in red.text and "a@b.com" not in red.text
    assert scoring.output_wording_problems("contact a@b.com")
