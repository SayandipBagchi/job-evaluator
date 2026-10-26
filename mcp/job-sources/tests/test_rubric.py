import copy

from job_sources import rubric as rub


def test_mock_rubric_is_valid(rubric):
    assert rub.validate_rubric(rubric) == []


def test_hash_is_stable_and_ignores_its_own_field(rubric):
    h = rub.rubric_hash(rubric)
    with_field = {**rubric, "rubric_hash": h}
    assert rub.rubric_hash(with_field) == h
    reordered = dict(reversed(list(rubric.items())))
    assert rub.rubric_hash(reordered) == h


def test_hash_changes_when_a_weight_changes(rubric):
    edited = copy.deepcopy(rubric)
    edited["signals"][0]["weight"] = 29
    edited["signals"][1]["weight"] = 26
    assert rub.rubric_hash(edited) != rub.rubric_hash(rubric)


def test_weights_must_sum_to_100(rubric):
    bad = copy.deepcopy(rubric)
    bad["signals"][0]["weight"] = 40
    assert any("sum to" in p for p in rub.validate_rubric(bad))


def test_weak_signals_capped_at_5(rubric):
    bad = copy.deepcopy(rubric)
    bad["signals"][4]["weak_signal"] = True  # s5 weight 10, plus s6 weight 3
    assert any("cap" in p for p in rub.validate_rubric(bad))


def test_protected_attributes_rejected(rubric):
    for phrase in ("Young and energetic", "Native speaker of English", "Graduation year after 2015", "Gender balance"):
        bad = copy.deepcopy(rubric)
        bad["signals"][3]["criterion"] = phrase
        assert any("protected attribute" in p for p in rub.validate_rubric(bad)), phrase


def test_ordinary_words_are_not_false_positives(rubric):
    ok = copy.deepcopy(rubric)
    ok["signals"][3]["criterion"] = "Managed a health-tech roadmap and stakeholder agenda"
    assert rub.validate_rubric(ok) == []


def test_institution_never_a_gate(rubric):
    bad = copy.deepcopy(rubric)
    bad["gates"].append({"id": "g2", "requirement": "Degree from a top university", "jd_phrase": "x",
                         "verifiable_from_resume": True})
    assert any("never be a gate" in p for p in rub.validate_rubric(bad))


def test_thin_jd_rejected(rubric):
    thin = copy.deepcopy(rubric)
    thin["signals"] = thin["signals"][:2]
    thin["signals"][0]["weight"], thin["signals"][1]["weight"] = 50, 50
    assert any("GR1" in p for p in rub.validate_rubric(thin))
