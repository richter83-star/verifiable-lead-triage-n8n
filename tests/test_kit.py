"""Kit checks: the JS sealer and the Python verifier must agree, and tampering must be caught."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1] / "kit"
sys.path.insert(0, str(KIT / "verifier"))
from verify_audit import main as verify_main, verify_lines  # noqa: E402

NODE = shutil.which("node")
SEAL = KIT / "src" / "seal.js"

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required")


def seal(events_per_run: list[list[dict]], start_text: str = "") -> str:
    script = (
        "const s=require(process.argv[1]); const runs=JSON.parse(process.argv[2]); let text=process.argv[3]||'';"
        "runs.forEach((ev,i)=>{ const e=s.sealEvents(ev, s.chainHead(text), 'run'+i, '2026-11-07T00:00:0'+i+'.000Z');"
        " text += e.map(x=>JSON.stringify(x)).join('\\n') + '\\n'; }); process.stdout.write(text);"
    )
    return subprocess.run([NODE, "-e", script, str(SEAL), json.dumps(events_per_run), start_text],
                          capture_output=True, text=True, check=True, encoding="utf-8").stdout


RUN = [
    {"step": "lead_received", "actor": "manual", "data": {"lead_id": "L-1", "company": "Café Ünïcode — 日本", "x": None}},
    {"step": "model_decision", "actor": "m", "data": {"label": "hot", "score": 85, "confidence": 0.75, "ok": True}},
    {"step": "route", "actor": "rules", "data": {"queue": "sales_now"}},
]


def lines(text: str) -> list[str]:
    return text.splitlines()


def test_js_sha256_matches_python():
    import hashlib

    for s in ["", "abc", "a" * 55, "a" * 56, "a" * 119, "x" * 5000, "héllo — 日本 😀"]:
        out = subprocess.run([NODE, "-e", "process.stdout.write(require(process.argv[1]).sha256Hex(process.argv[2]))", str(SEAL), s],
                             capture_output=True, text=True, check=True, encoding="utf-8").stdout
        assert out == hashlib.sha256(s.encode("utf-8")).hexdigest()


def test_chain_across_runs_is_intact():
    text = seal([RUN, RUN])
    r = verify_lines(lines(text))
    assert r["intact"] and r["entries"] == 6


def test_appending_to_existing_log_continues_chain():
    first = seal([RUN])
    both = seal([RUN], start_text=first)
    r = verify_lines(lines(both))
    assert r["intact"] and r["entries"] == 6


def test_floats_are_stored_as_strings():
    e = json.loads(lines(seal([RUN]))[1])
    assert e["data"]["confidence"] == "0.75" and e["data"]["score"] == 85


@pytest.mark.parametrize("mutate,expect", [
    (lambda ls: [ls[0], ls[1].replace('"hot"', '"cold"'), *ls[2:]], "edited"),
    (lambda ls: [ls[0], *ls[2:]], "seq"),
    (lambda ls: [ls[0], ls[2], ls[1], *ls[3:]], "seq"),
    (lambda ls: [*ls[:3], "{not json", *ls[3:]], "not valid JSON"),
])
def test_tampering_is_detected(mutate, expect):
    ls = lines(seal([RUN, RUN]))
    r = verify_lines(mutate(ls))
    assert not r["intact"]
    assert any(expect in p["problem"] for p in r["problems"])


def test_expect_head_catches_rewrite(tmp_path: Path):
    original = seal([RUN, RUN])
    head = json.loads(lines(original)[-1])["hash"]
    rewritten = seal([[{"step": "lead_received", "actor": "forger", "data": {"lead_id": "L-9"}}]])
    p = tmp_path / "log.jsonl"
    p.write_text(rewritten, encoding="utf-8")
    assert verify_main([str(p)]) == 0  # a full rewrite is internally consistent...
    assert verify_main([str(p), "--expect-head", head]) == 1  # ...but the recorded head is gone


def test_demo_samples():
    assert verify_lines((KIT / "samples" / "demo-audit.jsonl").read_text(encoding="utf-8").splitlines())["intact"]
    bad = verify_lines((KIT / "samples" / "demo-audit-tampered.jsonl").read_text(encoding="utf-8").splitlines())
    assert not bad["intact"] and bad["problems"][0]["line"] == 5


def test_workflow_embeds_current_seal_code():
    wf = json.loads((KIT / "workflow" / "verifiable-lead-triage.json").read_text(encoding="utf-8"))
    code = next(n for n in wf["nodes"] if n["name"] == "Seal audit entries")["parameters"]["jsCode"]
    assert "function sha256Hex" in code and "sealEvents" in code
    assert "0x428a2f98" in code
    names = {n["name"] for n in wf["nodes"]}
    for a, conn in wf["connections"].items():
        assert a in names
        for out in conn["main"]:
            for c in out:
                assert c["node"] in names


# ---------- n8n template gallery version ----------
GALLERY = KIT / "gallery" / "verifiable-lead-triage.gallery.json"


def test_gallery_matches_a_fresh_build():
    sys.path.insert(0, str(KIT.parent))
    import build_workflow

    assert json.loads(GALLERY.read_text(encoding="utf-8")) == build_workflow.build_gallery()


def test_gallery_follows_n8n_submission_rules():
    wf = json.loads(GALLERY.read_text(encoding="utf-8"))
    nodes = {n["name"]: n for n in wf["nodes"]}
    # user-editable values live in an Edit Fields (Set) node that every trigger passes through
    assert nodes["Settings"]["type"] == "n8n-nodes-base.set"
    fields = {a["name"]: a["value"] for a in nodes["Settings"]["parameters"]["assignments"]["assignments"]}
    assert set(fields) == {"audit_log_path", "llm_base_url", "llm_model", "mock_llm"} and fields["mock_llm"] is True
    for trig in ("Run with sample lead", "Lead webhook"):
        assert wf["connections"][trig]["main"][0][0]["node"] == "Settings"
    assert wf["connections"]["Settings"]["main"][0][0]["node"] == "Prepare"
    # an overview sticky note plus section notes
    stickies = [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.stickyNote"]
    overview = nodes["Overview"]["parameters"]["content"]
    assert len(stickies) >= 4
    for must in ("Setup", "Self-hosted n8n", "does not prevent", "AI assistance", "github.com/richter83-star"):
        assert must in overview
    # no secrets or personal data anywhere in the template
    text = json.dumps(wf)
    assert "llm_api_key: ''" in nodes["Prepare"]["parameters"]["jsCode"]  # the key stays empty; it comes from the environment
    for pattern in (r"sk-[A-Za-z0-9]{10,}", r"Bearer [A-Za-z0-9]{10,}", r"[\w.+-]+@[\w-]+\.[\w.]+", r"https?://[^\s\"]*webhook[^\s\"]*"):
        assert not re.search(pattern, text), pattern
    # Settings values are read, and environment variables still win
    prep = nodes["Prepare"]["parameters"]["jsCode"]
    assert prep.index("const st = ") < prep.index("$env.AUDIT_LLM_API_KEY") < prep.index("// n8n reads files with glob")
    assert all(n["type"].startswith("n8n-nodes-base.") for n in wf["nodes"])
