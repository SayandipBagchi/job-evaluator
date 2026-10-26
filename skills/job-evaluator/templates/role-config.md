# Role config template

Save as `tenants/<org>/roles/<role-id>.json`. Org-specific facts live here, never in `skills/`. The skill reads it before scoring; any field left out falls back to the default shown.

```json
{
  "role_id": "<kebab-case id>",
  "title": "<role title as advertised>",
  "jurisdictions": ["IN", "UK", "EU", "US", "US-NYC"],
  "candidate_locations_in_scope": ["IN"],
  "nyc_bias_audit_date": null,
  "thresholds": {
    "shortlist_min_score": 75,
    "review_min_score": 60,
    "shortlist_min_confidence": 0.5,
    "low_confidence_below": 0.5,
    "parse_quality_min": 0.6
  },
  "shortlist_on_unverifiable": false,
  "ats": { "provider": "greenhouse", "job_id": null },
  "retention_days": 180,
  "hard_constraints_not_in_jd": [],
  "notice_required": true
}
```

| Field | Meaning |
| --- | --- |
| `jurisdictions` | Where candidates live. Decides which compliance behaviour switches on. Required: the skill asks if it is missing |
| `nyc_bias_audit_date` | ISO date of the latest independent bias audit. Without it, NYC candidates are not scored |
| `shortlist_on_unverifiable` | If true, a candidate at or above the shortlist line with only unverifiable gates stays Shortlist and the gates go to screening-call items. Default false: they go to Review |
| `hard_constraints_not_in_jd` | Gates the hiring manager holds that the JD does not state. jd-to-rubric adds them as gates |
| `retention_days` | How long audit records are kept before deletion |
| `notice_required` | Whether candidates must be told an automated tool assists screening |
