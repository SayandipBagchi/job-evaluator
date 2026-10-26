import copy

import pytest

from job_sources import rubric as rub
from job_sources import scoring


def card(rubric, scores, gates=None, parse_quality=0.95, flagged=False, status=None):
    criteria = []
    for s, v in zip(rubric["signals"], scores):
        st = status or ("met" if v >= 3 else "partial" if v >= 1 else "absent")
        criteria.append({"id": s["id"], "score": v, "status": st, "evidence": "x" if v else "no evidence"})
    return {"cand_ref": "cand_0000abcd", "rubric_hash": rub.rubric_hash(rubric), "criteria": criteria,
            "gates": gates if gates is not None else [{"id": "g1", "status": "passed"}],
            "parse_quality": parse_quality, "injection_flagged": flagged}


def test_match_score_is_weighted_sum(rubric):
    assert scoring.match_score(rubric, card(rubric, [4, 4, 4, 4, 4, 4])) == 100.0
    assert scoring.match_score(rubric, card(rubric, [0] * 6)) == 0.0
    # 30*0.5 + 25 + 20*0.5 + 12*0.5 + 10 + 0 = 66
    assert scoring.match_score(rubric, card(rubric, [2, 4, 2, 2, 4, 0])) == 66.0


@pytest.mark.parametrize(
    "scores,gates,pq,flagged,band,rule",
    [
        ([4] * 6, [{"id": "g1", "status": "failed"}], 0.95, False, "Not recommended", 1),
        ([4] * 6, [{"id": "g1", "status": "passed"}], 0.3, False, "Review", 2),
        ([4] * 6, [{"id": "g1", "status": "unverifiable"}], 0.95, False, "Review", 3),
        ([4] * 6, [{"id": "g1", "status": "passed"}], 0.95, False, "Shortlist", 4),
        ([2, 4, 2, 2, 4, 0], [{"id": "g1", "status": "passed"}], 0.95, False, "Review", 5),
        ([0, 1, 0, 2, 2, 4], [{"id": "g1", "status": "passed"}], 0.95, False, "Not recommended", 6),
    ],
)
def test_band_rules_in_precedence_order(rubric, scores, gates, pq, flagged, band, rule):
    result = scoring.score_and_band(rubric, card(rubric, scores, gates, pq, flagged))
    assert (result.band, result.band_rule) == (band, rule)


def test_failed_gate_beats_everything(rubric):
    result = scoring.score_and_band(rubric, card(rubric, [4] * 6, [{"id": "g1", "status": "failed"}], 0.1))
    assert result.band_rule == 1


def test_low_confidence_never_yields_not_recommended_on_its_own(rubric):
    # Low score, but unreadable resume: must be Review, not Not recommended.
    result = scoring.score_and_band(rubric, card(rubric, [0] * 6, parse_quality=0.2))
    assert result.band == "Review" and result.band_rule == 2


def test_shortlist_on_unverifiable_setting(rubric):
    c = card(rubric, [4] * 6, [{"id": "g1", "status": "unverifiable"}])
    assert scoring.score_and_band(rubric, c).band == "Review"
    assert scoring.score_and_band(rubric, c, shortlist_on_unverifiable=True).band == "Shortlist"


def test_confidence_formula_and_injection_penalty(rubric):
    clean = scoring.score_and_band(rubric, card(rubric, [4] * 6))
    flagged = scoring.score_and_band(rubric, card(rubric, [4] * 6, flagged=True))
    assert clean.confidence == pytest.approx(0.40 + 0.25 * 0.95 + 0.20 * 1.0 + 0.15 * 1.0, abs=1e-4)
    assert flagged.confidence == pytest.approx(clean.confidence - 0.15, abs=1e-4)
    assert flagged.score == clean.score  # injection never moves the score


def test_unverifiable_signals_lower_coverage_not_score(rubric):
    c = card(rubric, [4, 4, 4, 4, 0, 0])
    c["criteria"][4]["status"] = "unverifiable"
    r = scoring.score_and_band(rubric, c)
    assert r.components["coverage"] == pytest.approx(0.90)


def test_thresholds_from_role_config(rubric):
    c = card(rubric, [2, 4, 2, 2, 4, 0])  # 66
    assert scoring.score_and_band(rubric, c, {"shortlist_min_score": 65}).band == "Shortlist"


def test_validate_scorecard_catches_missing_and_fake_quotes(rubric, resume_text, reference):
    good = copy.deepcopy(reference["pm-cards"]["a-strong"])
    good.update({"rubric_hash": rub.rubric_hash(rubric), "parse_quality": 1.0})
    assert scoring.validate_scorecard(rubric, good, resume_text) == []

    bad = copy.deepcopy(good)
    bad["criteria"][0]["evidence"] = "Led launch of a card to 5 million customers"
    bad["criteria"][1]["evidence"] = "no evidence"
    bad["criteria"][2]["status"] = "partial"
    problems = scoring.validate_scorecard(rubric, bad, resume_text)
    assert any("s1" in p and "verbatim" in p for p in problems)
    assert any("s2" in p and "no quoted evidence" in p for p in problems)
    assert any("s3" in p and "status" in p for p in problems)


def test_validate_scorecard_catches_hash_and_missing_criteria(rubric, resume_text, reference):
    c = copy.deepcopy(reference["pm-cards"]["a-strong"])
    c["rubric_hash"] = "0" * 64
    c["criteria"] = c["criteria"][:4]
    problems = scoring.validate_scorecard(rubric, c, resume_text)
    assert any("GR4" in p for p in problems)
    assert any("missing" in p for p in problems)


@pytest.mark.parametrize(
    "text,expect",
    [
        ("Priya · Shortlist · 82.5", []),
        ("We should reject this candidate", ["reject"]),
        ("Do not hire", ["hire"]),
        ("Not recommended · 40.0", ["human confirms"]),
        ("Not recommended · 40.0 · recommendation; a human confirms", []),
        ("contact priya@example.com", ["email"]),
        ("call +91 98450 12345", ["phone"]),
        ("Kestrel Finance (2019 - 2024)", []),
    ],
)
def test_output_wording(text, expect):
    problems = scoring.output_wording_problems(text)
    if not expect:
        assert problems == []
    for e in expect:
        assert any(e in p for p in problems), problems


def test_missing_gate_counts_as_unverifiable(rubric):
    c = card(rubric, [4] * 6, gates=[])
    result = scoring.score_and_band(rubric, c)
    assert result.band == "Review" and result.band_rule == 3
    assert any("gates missing" in p for p in scoring.validate_scorecard(rubric, c, "x"))


def test_bad_score_values_are_reported_not_raised(rubric):
    c = card(rubric, [4] * 6)
    c["criteria"][0]["score"] = "high"
    c["criteria"].append(dict(c["criteria"][1]))
    problems = scoring.validate_scorecard(rubric, c, "x")
    assert any("whole number" in p for p in problems)
    assert any("duplicate" in p for p in problems)
    assert scoring.match_score(rubric, c) >= 0


def test_batch_example_passes_wording_check():
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    text = (root / "skills/job-evaluator/examples/batch-shortlist.md").read_text()
    assert scoring.output_wording_problems(text) == []
