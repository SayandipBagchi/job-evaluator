import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
ROOT = PKG.parents[1]
sys.path.insert(0, str(PKG))

MOCKS = ROOT / "evals" / "fixtures"


@pytest.fixture(autouse=True)
def isolated_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_EVALUATOR_LOG_DIR", str(tmp_path / "logs"))
    return tmp_path / "logs"


@pytest.fixture
def rubric():
    return json.loads((MOCKS / "rubrics" / "pm-cards.json").read_text(encoding="utf-8"))


@pytest.fixture
def resume_text():
    return (MOCKS / "resumes" / "pm-cards" / "a-strong.txt").read_text(encoding="utf-8")


@pytest.fixture
def reference():
    return json.loads((MOCKS / "reference_scorecards.json").read_text(encoding="utf-8"))
