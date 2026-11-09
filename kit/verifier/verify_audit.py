#!/usr/bin/env python3
"""Verify a hash-chained audit log (JSONL) written by the Verifiable Lead Triage workflow.

Checks every line:
  - the line is valid JSON with the expected fields
  - seq counts up by one from 1
  - prev_hash equals the previous entry's hash (the first entry's is 64 zeros)
  - hash equals SHA-256 of the entry's canonical JSON (keys sorted, no spaces, UTF-8, "hash" left out)

Tamper-evident, not tamper-proof: someone who rewrites the WHOLE file can rebuild a valid
chain. Record the head hash somewhere else (an email to yourself, a git commit, a ticket)
and check it later with --expect-head.

Usage:
  python verify_audit.py audit.jsonl
  python verify_audit.py audit.jsonl --expect-head <hash>
  python verify_audit.py audit.jsonl --json
Exit code 0 = intact, 1 = problems found, 2 = file could not be read.
Standard library only (Python 3.8+).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

GENESIS = "0" * 64
FIELDS = {"seq", "ts", "run_id", "step", "actor", "data", "prev_hash", "hash"}


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(canon(body).encode("utf-8")).hexdigest()


def verify_lines(lines):
    problems = []
    prev_hash, prev_seq, count, head = GENESIS, 0, 0, GENESIS
    for n, raw in enumerate(lines, start=1):
        raw = raw.strip()
        if not raw:
            continue
        count += 1
        try:
            e = json.loads(raw)
        except json.JSONDecodeError as err:
            problems.append({"line": n, "problem": f"not valid JSON ({err.msg})"})
            prev_hash, prev_seq = None, prev_seq + 1
            continue
        missing = FIELDS - set(e)
        if missing:
            problems.append({"line": n, "problem": f"missing fields: {sorted(missing)}"})
        if e.get("seq") != prev_seq + 1:
            problems.append({"line": n, "problem": f"seq is {e.get('seq')}, expected {prev_seq + 1} (entry missing, added or reordered)"})
        if prev_hash is not None and e.get("prev_hash") != prev_hash:
            problems.append({"line": n, "problem": "prev_hash does not match the previous entry (chain broken here)"})
        if e.get("hash") != entry_hash(e):
            problems.append({"line": n, "problem": "hash does not match the entry's contents (entry was edited)"})
        prev_hash = e.get("hash")
        prev_seq = e.get("seq") if isinstance(e.get("seq"), int) else prev_seq + 1
        head = e.get("hash", head)
    return {"entries": count, "head": head, "intact": not problems, "problems": problems}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Verify a hash-chained audit log.")
    ap.add_argument("path")
    ap.add_argument("--expect-head", help="a head hash you recorded earlier; fails if the log no longer ends there or past it")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args(argv)
    try:
        with open(args.path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as err:
        print(f"cannot read {args.path}: {err}", file=sys.stderr)
        return 2
    result = verify_lines(lines)
    if args.expect_head:
        hashes = []
        for raw in lines:
            try:
                hashes.append(json.loads(raw).get("hash"))
            except json.JSONDecodeError:
                pass
        if args.expect_head not in hashes:
            result["intact"] = False
            result["problems"].append({"line": None, "problem": "the recorded head hash is not in this log (history was rewritten or truncated)"})
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{args.path}: {result['entries']} entries, head {result['head']}")
        if result["intact"]:
            print("INTACT: every entry matches its hash and links to the one before it.")
        else:
            print(f"PROBLEMS FOUND ({len(result['problems'])}):")
            for p in result["problems"]:
                where = f"line {p['line']}" if p["line"] else "log"
                print(f"  {where}: {p['problem']}")
    return 0 if result["intact"] else 1


if __name__ == "__main__":
    sys.exit(main())
