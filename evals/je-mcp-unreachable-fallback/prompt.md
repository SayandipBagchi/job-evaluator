---
name: je-mcp-unreachable-fallback
tags: [harness, should-fire, job-evaluator]
runs: 3
max_turns: 20
timeout_seconds: 480
---
Pull the applicants for Greenhouse job 4012345 and shortlist them. Candidates are in the UK. (If the Greenhouse connector is unavailable or not configured, handle that.)
