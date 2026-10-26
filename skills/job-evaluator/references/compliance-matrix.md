# Compliance matrix

What the plugin does differently by where candidates live. This is product behaviour designed to support compliance. It is not legal advice and it does not make a deployment compliant on its own; the deploying organisation's legal team decides that.

As of 25 October 2026.

| Code | Regime | Applies when | Plugin behaviour |
| --- | --- | --- | --- |
| EU | EU AI Act, Annex III (employment is high-risk). Standalone high-risk obligations apply from 2 December 2027 after the Digital Omnibus delay. | Candidates in the EU | Audit record per evaluation; visible rubric; human decision field; recommendation wording |
| US-NYC | New York City Local Law 144 (automated employment decision tools): independent bias audit before use, published summary, notice to candidates | NYC-resident candidates or NYC-located roles | Stop before scoring unless `nyc_bias_audit_date` is set in the role config; candidate-notice template |
| UK | UK GDPR Article 22 (solely automated decisions with significant effect) | UK candidates | No automated rejection; human decision field required; recommendation wording |
| IN | Digital Personal Data Protection Act 2023 | Candidates in India | Purpose and retention line in the notice; audit log stores hashes, not resume text; retention from role config |
| US | Other US states with AI-in-hiring rules (Illinois, Colorado, California and others) | US candidates outside NYC | Same safeguards as UK; flag that state rules vary and legal should confirm |

## What every record holds

The audit log (`eval_log`) writes one JSON line per candidate evaluation:

Required: `role_id`, `rubric_hash`, `cand_ref`, `resume_hash` (of the redacted text), `score`, `confidence`, `band`, `jurisdictions` (non-empty), `guardrails_not_run` (a list, empty if none). Added by the tool: `timestamp`, `plugin_version`, `human_decision` (null until `record_human_decision` writes one).

The log uses an allowlist of fields and refuses any email address or phone number, so it never holds resume text, names or contact details. `eval_log_prune` deletes records and sealed identities older than the role's `retention_days`.

## Wording that must appear

- On every scorecard: "This is a recommendation to support a human reviewer. It is not a hiring decision."
- On every Not recommended line: "recommendation; a human confirms".
- In the candidate notice, when the role config says notices are required: see `templates/candidate-notice.md`.
