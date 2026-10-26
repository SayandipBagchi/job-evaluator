#!/usr/bin/env python3
"""Layer C: quantitative evals for job-evaluator. Stdlib only.

Deterministic checks (always run, over evals/fixtures/):
  D1 rubrics valid, and each jd_hash matches its JD file
  D2 reference pipeline: prepare_resume -> validate_scorecard -> score_and_band
     agrees with labels.json, band and rule
  D3 fairness invariance: name, pronoun and graduation-year swaps produce
     byte-identical redacted text, so no scorer can see the difference
  D4 determinism: five runs of the pipeline give identical results
  D5 order invariance: a shuffled batch gives the same band per candidate
  D6 injection: every e-steer resume with steering content is flagged, and the
     neutralised text no longer contains it

Live checks (need model scorecards under evals/results/runs/<run>/<jd>/<slot>.json):
  L1 band agreement with labels       gate >= 0.80
  L2 Spearman rank vs labels          gate >= 0.70
  L3 determinism across runs          score sd <= 2, band identical
  L4 calibration                      High >= 0.90, Med >= 0.75
Without model scorecards the live checks are NOT RUN, never passed.

Usage: python3 scripts/run_quant_evals.py [--write]
"""

from __future__ import annotations

import json
import random
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp" / "job-sources"))

from job_sources import jd as jdmod  # noqa: E402
from job_sources import rubric as rubmod  # noqa: E402
from job_sources import scoring  # noqa: E402
import server  # noqa: E402

MOCKS = ROOT / "evals" / "fixtures"
RESULTS = ROOT / "evals" / "results"
BAND_ORDER = {"Shortlist": 2, "Review": 1, "Not recommended": 0}
SWAP_NAMES = ["James O'Connor", "Fatima Begum", "Hiroshi Tanaka", "Maria Gonzalez", "Kwame Mensah"]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def mock_set():
    rubrics = {p.stem: load(p) for p in sorted((MOCKS / "rubrics").glob("*.json"))}
    labels = {k: v for k, v in load(MOCKS / "labels.json").items() if not k.startswith("_")}
    refs = {k: v for k, v in load(MOCKS / "reference_scorecards.json").items() if not k.startswith("_")}
    return rubrics, labels, refs


def jd_keywords(jd_id: str) -> list[str]:
    return jdmod.from_text((MOCKS / "jds" / f"{jd_id}.md").read_text(encoding="utf-8"))["keywords"]


def run_pipeline(rubrics, refs, order=None, raw_override=None):
    results = {}
    items = [(j, s) for j in refs for s in refs[j]]
    if order:
        items = order(items)
    for jd_id, slot in items:
        rub = rubrics[jd_id]
        raw = (raw_override or {}).get((jd_id, slot)) or (MOCKS / "resumes" / jd_id / f"{slot}.txt").read_text(encoding="utf-8")
        prepared = server.prepare_resume(text=raw, jd_keywords=jd_keywords(jd_id))
        card = json.loads(json.dumps(refs[jd_id][slot]))
        card.update({"cand_ref": prepared["cand_ref"], "rubric_hash": rubmod.rubric_hash(rub),
                     "parse_quality": prepared["parse_quality"], "injection_flagged": prepared["injection_flagged"]})
        problems = scoring.validate_scorecard(rub, card, prepared["text"])
        band = scoring.score_and_band(rub, card, parse_quality=prepared["parse_quality"],
                                      injection_flagged=prepared["injection_flagged"]).as_dict()
        results[(jd_id, slot)] = {"prepared": prepared, "problems": problems, **band}
    return results


def swap_variant(raw: str, idx: int) -> str:
    from job_sources.redaction import _guess_name

    lines = raw.split("\n")
    if _guess_name(raw):  # only swap a real name line; an image-only resume has none
        lines[0] = SWAP_NAMES[idx % len(SWAP_NAMES)]
    text = "\n".join(lines)
    text = re.sub(r"\(\s*she\s*/\s*her\s*\)", "(he/him)", text, flags=re.I)
    out, in_edu = [], False
    for line in text.split("\n"):
        if re.match(r"^\s*education\s*:?\s*$", line, re.I):
            in_edu = True
        elif re.match(r"^\s*(skills|experience|summary)\s*:?\s*$", line, re.I):
            in_edu = False
        elif in_edu:
            line = re.sub(r"\b(19|20)(\d{2})\b", lambda m: str(int(m.group()) - 20), line)
        out.append(line)
    return "\n".join(out)


def spearman(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    if len(set(rx)) < 2 or len(set(ry)) < 2:
        return None
    return statistics.correlation(rx, ry)


def deterministic_checks():
    rubrics, labels, refs = mock_set()
    sheet = {}

    problems = []
    for jd_id, rub in rubrics.items():
        problems += [f"{jd_id}: {p}" for p in rubmod.validate_rubric(rub)]
        actual = rubmod.text_hash((MOCKS / "jds" / f"{jd_id}.md").read_text(encoding="utf-8"))
        if rub["jd_hash"] != actual:
            problems.append(f"{jd_id}: jd_hash is stale (expected {actual[:12]})")
    sheet["D1 rubrics valid"] = ("pass" if not problems else "fail", problems)

    base = run_pipeline(rubrics, refs)
    misses = []
    for key, r in base.items():
        want = labels[key[0]][key[1]]
        if r["problems"]:
            misses.append(f"{key[0]}/{key[1]}: scorecard invalid: {'; '.join(r['problems'])}")
        if r["band"] != want["band"] or r["band_rule"] != want["rule"]:
            misses.append(f"{key[0]}/{key[1]}: got {r['band']} (rule {r['band_rule']}, score {r['score']}, "
                          f"conf {r['confidence']}), want {want['band']} (rule {want['rule']})")
    agree = sum(1 for k, r in base.items() if r["band"] == labels[k[0]][k[1]]["band"])
    sheet["D2 reference pipeline"] = ("pass" if not misses else "fail",
                                      [f"band agreement {agree}/{len(base)}"] + misses)

    diffs = []
    for i, (jd_id, slot) in enumerate(base):
        raw = (MOCKS / "resumes" / jd_id / f"{slot}.txt").read_text(encoding="utf-8")
        variant = swap_variant(raw, i)
        if variant == raw:
            continue
        a = base[(jd_id, slot)]["prepared"]["text"]
        b = server.prepare_resume(text=variant, jd_keywords=jd_keywords(jd_id))["text"]
        if a != b:
            first = next(k for k in range(min(len(a), len(b))) if a[k] != b[k]) if a[:len(b)] != b[:len(a)] else min(len(a), len(b))
            diffs.append(f"{jd_id}/{slot}: redacted text differs near: {a[max(0, first - 30):first + 30]!r}")
    sheet["D3 fairness invariance"] = ("pass" if not diffs else "fail", diffs)

    runs = [run_pipeline(rubrics, refs) for _ in range(5)]
    unstable = [f"{k[0]}/{k[1]}" for k in base
                if len({(r[k]["score"], r[k]["confidence"], r[k]["band"]) for r in runs}) != 1]
    sheet["D4 determinism"] = ("pass" if not unstable else "fail", unstable)

    rng = random.Random(20261025)
    shuffled = run_pipeline(rubrics, refs, order=lambda items: rng.sample(items, len(items)))
    moved = [f"{k[0]}/{k[1]}" for k in base if base[k]["band"] != shuffled[k]["band"]]
    sheet["D5 order invariance"] = ("pass" if not moved else "fail", moved)

    missed = []
    for (jd_id, slot), r in base.items():
        if slot != "e-steer":
            continue
        raw = (MOCKS / "resumes" / jd_id / f"{slot}.txt").read_text(encoding="utf-8")
        steering = re.search(r"ignore previous instructions|[​‌‍⁠﻿]|(?:\b\w+\b\s+){25,}", raw, re.I)
        if len(raw.strip()) < 80:
            continue  # the image-only case is a parse test, not an injection test
        if not r["prepared"]["injection_flagged"]:
            missed.append(f"{jd_id}/{slot}: steering content not flagged")
        if re.search(r"ignore previous instructions|[​‌‍⁠﻿]", r["prepared"]["text"], re.I):
            missed.append(f"{jd_id}/{slot}: steering content survives in the scorer's text")
        if not steering:
            missed.append(f"{jd_id}/{slot}: mock has no steering content to test")
    sheet["D6 injection"] = ("pass" if not missed else "fail", missed)
    return sheet, labels


def live_checks(labels):
    runs_dir = RESULTS / "runs"
    runs = sorted(p for p in runs_dir.glob("*") if p.is_dir()) if runs_dir.is_dir() else []
    if not runs:
        reason = "no model scorecards under evals/results/runs/"
        return {name: ("NOT RUN", [reason]) for name in
                ("L1 band agreement", "L2 rank correlation", "L3 determinism across runs", "L4 calibration")}

    per_key: dict = {}
    for run in runs:
        for path in run.glob("*/*.json"):
            card = load(path)
            per_key.setdefault((path.parent.name, path.stem), []).append(card)

    keys = [k for k in per_key if k[0] in labels and k[1] in labels[k[0]]]
    firsts = {k: per_key[k][0] for k in keys}
    agree = sum(1 for k in keys if firsts[k].get("band") == labels[k[0]][k[1]]["band"])
    rate = agree / len(keys) if keys else 0
    sheet = {"L1 band agreement": ("pass" if rate >= 0.8 else "fail", [f"{agree}/{len(keys)} = {rate:.2f}"])}

    rho = spearman([firsts[k].get("score", 0) for k in keys], [BAND_ORDER[labels[k[0]][k[1]]["band"]] for k in keys])
    sheet["L2 rank correlation"] = ("NOT RUN", ["too few distinct values"]) if rho is None else \
        ("pass" if rho >= 0.7 else "fail", [f"spearman {rho:.2f}"])

    if len(runs) < 2:
        sheet["L3 determinism across runs"] = ("NOT RUN", ["needs at least 2 runs"])
    else:
        bad = []
        for k in keys:
            scores = [c.get("score", 0) for c in per_key[k]]
            bands = {c.get("band") for c in per_key[k]}
            if len(scores) > 1 and (statistics.pstdev(scores) > 2 or len(bands) > 1):
                bad.append(f"{k[0]}/{k[1]}: sd {statistics.pstdev(scores):.1f}, bands {sorted(bands)}")
        sheet["L3 determinism across runs"] = ("pass" if not bad else "fail", bad)

    calib = []
    for level, gate in (("High", 0.9), ("Med", 0.75)):
        ks = [k for k in keys if firsts[k].get("confidence_level") == level]
        if not ks:
            calib.append(f"{level}: no cases, NOT RUN")
            continue
        acc = sum(1 for k in ks if firsts[k].get("band") == labels[k[0]][k[1]]["band"]) / len(ks)
        calib.append(f"{level}: {acc:.2f} over {len(ks)} (gate {gate})" + ("" if acc >= gate else " FAIL"))
    sheet["L4 calibration"] = ("fail" if any("FAIL" in c for c in calib) else
                               "NOT RUN" if all("NOT RUN" in c for c in calib) else "pass", calib)
    return sheet


def main() -> int:
    sheet, labels = deterministic_checks()
    sheet.update(live_checks(labels))
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"job-evaluator quantitative evals · {stamp}\n")
    for name, (status, notes) in sheet.items():
        print(f"{status.upper():8} {name}")
        for note in notes:
            print(f"         - {note}")
    if "--write" in sys.argv:
        RESULTS.mkdir(parents=True, exist_ok=True)
        out = RESULTS / f"quant-{stamp}.json"
        out.write_text(json.dumps({k: {"status": s, "notes": n} for k, (s, n) in sheet.items()}, indent=2))
        print(f"\nwrote {out.relative_to(ROOT)}")
    return 1 if any(s == "fail" for s, _ in sheet.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
