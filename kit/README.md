# Verifiable Lead Triage Kit for n8n (v0.1.1)

An n8n workflow that sorts incoming B2B leads with an AI model (or simple rules) and writes every step to a **tamper-evident audit log**. If anyone edits, deletes or reorders a past entry, the included verifier shows exactly where.

Built with AI assistance. Tested on self-hosted n8n 1.122.4 (Windows) with automated checks before release.
Source, issues and updates: https://github.com/richter83-star/verifiable-lead-triage-n8n

## What's inside

| File | What it is |
| --- | --- |
| `workflow/verifiable-lead-triage.json` | The n8n workflow to import |
| `verifier/verify_audit.py` | Command-line verifier (Python 3.8+, no installs) |
| `verifier/viewer.html` | Offline verifier for your browser, with demo logs |
| `samples/demo-audit.jsonl`, `samples/demo-audit-tampered.jsonl` | Example logs: one intact, one with an edited entry |
| `src/seal.js` | The hashing code used inside the workflow, for review |

## What it does

1. A lead arrives (webhook) or you run it with the built-in sample lead.
2. **Classify lead** labels it `hot`, `warm` or `cold` with a score and a one-sentence reason, using any OpenAI-compatible model (Ollama, LM Studio, OpenAI) or deterministic rules.
3. The lead is routed to a queue: `sales_now`, `nurture`, `archive`, or `human_review` if the model reply is unusable.
4. Three entries are appended to the audit log: lead received, model decision, route. Each entry includes the SHA-256 hash of the previous one, so the log forms a chain.

## Requirements

- **Self-hosted n8n 1.x.** The workflow reads and writes a file on disk, which n8n Cloud does not allow.
- Python 3.8+ for the command-line verifier, or any modern browser for `viewer.html`.
- For model-based triage: an OpenAI-compatible endpoint. Local models work.

## Setup (about 10 minutes)

1. **Import:** in n8n, open *Workflows → Import from File* and choose `workflow/verifiable-lead-triage.json`.
2. **Choose where the log lives:** open the **Prepare** node and set `audit_log_path`. Use an absolute path in a folder that exists, for example `C:/n8n-audit/lead-triage.jsonl` or `/home/node/audit/lead-triage.jsonl`. If your n8n sets `N8N_RESTRICT_FILE_ACCESS_TO`, the folder must be inside the allowed path. Avoid the characters `* ? [ ] { }` in the path: n8n reads files with glob patterns.
3. **First run (no model needed):** leave `mock_llm: true` and click **Test workflow**. The **Result** node shows the label, queue and the new head hash. Run it a second time to extend the chain.
4. **Verify:** `python verifier/verify_audit.py C:/n8n-audit/lead-triage.jsonl` should print `INTACT`. Or open `verifier/viewer.html` and choose the file.
5. **Switch to a model:** in **Prepare**, set `mock_llm: false`, `llm_base_url` (for example `http://127.0.0.1:11434/v1` for Ollama) and `llm_model`. Add `llm_api_key` only if your provider needs one.
6. **Go live:** activate the workflow and send leads to the webhook:

```
curl -X POST http://localhost:5678/webhook/lead-triage -H "Content-Type: application/json" -d "{\"lead_id\":\"L-2001\",\"company\":\"Acme\",\"employees\":120,\"budget_usd\":15000,\"message\":\"Need help automating support triage\"}"
```

Every setting in **Prepare** can also come from environment variables: `AUDIT_LOG_PATH`, `AUDIT_MOCK_LLM`, `AUDIT_LLM_BASE_URL`, `AUDIT_LLM_MODEL`.

## What "tamper-evident" means here, and its limits

- **Detected:** editing any field of a past entry, deleting or inserting an entry, reordering entries, corrupting a line.
- **Not prevented:** someone with write access can still change or delete the file. The log makes changes *visible*; it does not *block* them.
- **Full rewrite:** someone who rewrites the whole file can recompute a valid chain. To catch that, copy the head hash somewhere outside the server (an email to yourself, a ticket, a git commit) and check later with `python verifier/verify_audit.py <log> --expect-head <hash>`.
- **Not a correctness check:** the log proves what the model decided and when, not that the decision was right.
- **Not a compliance certification:** the kit can support your own audit process but does not make you compliant with any standard.
- **Concurrency:** two runs finishing at the same moment can both read the same last entry; the verifier will then flag a sequence problem. For high lead volume, run the workflow with one worker or queue leads.

## Privacy

The log stores the lead ID, company, source and a SHA-256 fingerprint of the full lead, but not the lead's message or contact details. Edit the **Seal audit entries** node if you need more or less.

## License

Apache License 2.0 (see `LICENSE` and `NOTICE`). You may use, modify and redistribute the kit, including commercially, under the terms of that license. It is provided as is, without warranty of any kind.
