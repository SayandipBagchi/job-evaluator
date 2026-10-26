# Eval fixtures

Synthetic data only. No real person's resume is in this folder, and none may be added: real resumes are personal data.

| Folder | Holds |
| --- | --- |
| `jds/` | Three synthetic JDs: `pm-cards` (Senior PM, card issuing), `be-payments` (backend engineer, payments), `analyst-growth` (data analyst) |
| `rubrics/` | The frozen rubric for each JD, as `jd-to-rubric` should produce it, with its hash |
| `resumes/<jd>/` | Five resumes per JD, each written to land in a known band for a known reason |
| `labels.json` | The expected band for each resume and why. Author-labelled for this synthetic set; recruiter-labelled pairs replace these in the golden set (see the PRD's open questions) |
| `swaps/` | Generated at test time by `scripts/run_quant_evals.py`: each resume under a swapped name, pronouns and graduation year |

Designed band per resume slot:

| Slot | Designed to be | Tests |
| --- | --- | --- |
| `a-strong` | Shortlist | Core scoring, evidence quotes |
| `b-borderline` | Review (score 60 to 74) | Band boundary |
| `c-offdomain` | Not recommended (rule 6) | Low score with clear evidence, confidence not Low |
| `d-gate` | Not recommended (rule 1) | Verifiably failed gate despite strong evidence |
| `e-steer` | Review | Injection or poor parse must not raise the band |
