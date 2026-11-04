"""End-to-end: start server.py over stdio with the real MCP SDK, list tools, call the core pipeline.

Skipped when the MCP SDK is not installed. This is the harness proof that does not depend on
any host's eval sandbox starting plugin servers.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

import server  # noqa: E402

PKG = Path(__file__).resolve().parents[1]
FIXTURES = PKG.parents[1] / "evals" / "fixtures"


def _text(result) -> dict:
    return json.loads(result.content[0].text)


async def _run(log_dir: str) -> None:
    params = StdioServerParameters(command=sys.executable, args=[str(PKG / "server.py")],
                                   env={"JOB_EVALUATOR_LOG_DIR": log_dir, "PATH": "/usr/bin:/usr/local/bin"})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            names = {t.name for t in tools}
            assert names == set(server.READ_TOOLS + server.WRITE_TOOLS)
            for t in tools:  # strict, documented schemas and honest annotations
                assert t.input_schema.get("additionalProperties") is False, t.name
                assert all(p.get("description") for p in t.input_schema.get("properties", {}).values()), t.name
                assert t.annotations is not None, t.name
            extra = await session.call_tool("jd_from_text", {"text": "x", "unexpected": 1})
            assert extra.is_error
            ssrf = _text(await session.call_tool("jd_fetch", {"url": "http://169.254.169.254/latest/meta-data/"}))
            assert ssrf["status"] == "refused"

            rubric = json.loads((FIXTURES / "rubrics" / "pm-cards.json").read_text())
            resume = (FIXTURES / "resumes" / "pm-cards" / "a-strong.txt").read_text()
            prepared = _text(await session.call_tool("prepare_resume", {"text": resume}))
            assert prepared["redacted"] and "Priya" not in prepared["text"]

            reference = json.loads((FIXTURES / "reference_scorecards.json").read_text())["pm-cards"]["a-strong"]
            card = {**reference, "cand_ref": prepared["cand_ref"],
                    "rubric_hash": _text(await session.call_tool("rubric_hash", {"rubric_json": rubric}))["rubric_hash"]}
            valid = _text(await session.call_tool("validate_scorecard",
                                                  {"rubric_json": rubric, "scorecard": card, "resume_text": prepared["text"]}))
            assert valid["valid"], valid
            band = _text(await session.call_tool("score_and_band", {
                "rubric_json": rubric, "scorecard": card,
                "parse_quality": prepared["parse_quality"], "injection_flagged": prepared["injection_flagged"]}))
            assert band["band"] == "Shortlist" and band["score"] == 100.0

            note = _text(await session.call_tool("ats_add_note", {"application_id": "77", "text": "x"}))
            assert note["status"] == "confirmation_required"


def test_stdio_end_to_end(tmp_path):
    asyncio.run(_run(str(tmp_path / "logs")))
