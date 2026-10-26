"""Deterministic core for the job-evaluator plugin.

Everything here is pure Python and testable without the MCP runtime. The MCP
server in ../server.py is a thin wrapper that exposes these functions as tools.
"""

__all__ = [
    "audit",
    "injection",
    "jd",
    "parsing",
    "redaction",
    "rubric",
    "scoring",
]
