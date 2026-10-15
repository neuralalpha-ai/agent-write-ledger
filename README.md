# agent-write-ledger

**Stop AI agents and scheduled jobs from doing the same write twice.**

One file, standard library only (Python 3.9+). Wrap every outbound write (post, email, order, payment, deploy) and the ledger guarantees:

- each item is sent **at most once**
- an `attempt` row is written **before** the network call, so a crash mid-send leaves a trace
- a timeout or dropped connection becomes **`unknown`**, and `unknown` **blocks the queue** until a human checks the real system
- no automatic retries on writes, because a retried write is how duplicates happen

```python
from write_ledger import WriteLedger, LedgerBlocked, AlreadySent

ledger = WriteLedger("write_ledger.jsonl")

def send(payload):
    return my_api.create_post(payload["text"])   # your real write

try:
    ledger.guarded_write("post-2026-10-13-1", {"text": "hello"}, send,
                         is_clear_error=lambda e: getattr(e, "status", 0) in (400, 401, 403, 422))
except LedgerBlocked as e:
    print("Stopped:", e)      # an earlier write is unresolved; check it first
except AlreadySent:
    print("Already sent, skipping")
```

After checking the real system, resolve a stuck item by hand:

```python
ledger.resolve("post-2026-10-13-1", "sent", "found it on the account at 03:12")
```

## Why

A timeout on a write does not mean it failed. It means you don't know. Most code treats "don't know" as "failed" and retries, which is exactly how you get a second email, a second order, or a second post at 3 a.m.

The ledger is a plain JSONL file you can read with `cat`:

```
{"id": "post-1", "state": "attempt", "payload_sha256": "9f2c...", "at": "..."}
{"id": "post-1", "state": "sent", "result": "...", "at": "..."}
{"id": "post-2", "state": "attempt", "payload_sha256": "41ab...", "at": "..."}
{"id": "post-2", "state": "unknown", "error": "TimeoutError: read timed out", "at": "..."}
```

The last row per id is its state. `post-2` blocks everything until you resolve it.

## Run the tests

```bash
python -m unittest discover -s tests -v
```

## The full kit

This is one piece of the **Agent Ops Guardrails Kit**, which adds a kill switch, daily caps and cool-downs, an identity check, a heartbeat for jobs that stop quietly, a spend meter, a reproducible release builder, templates and a verified checklist:
https://neuralalpha.gumroad.com/l/agent-ops-guardrails-kit?utm_source=github&utm_medium=readme

Free one-page checklist: https://neuralalpha.gumroad.com/l/agent-ops-preflight?utm_source=github&utm_medium=readme
日本語版チェックリスト（無料）: https://neuralalpha.gumroad.com/l/agent-ops-preflight-ja?utm_source=github&utm_medium=readme
Weekly notes on running agents in production: https://neuralalphaai.substack.com/?utm_source=github&utm_medium=readme

## License

MIT
