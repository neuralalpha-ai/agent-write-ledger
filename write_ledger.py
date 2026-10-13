"""Write ledger: record every outbound write so it can never silently happen twice.

States (one JSON line per event, append-only):
  attempt  - written BEFORE the network call
  sent     - the call succeeded
  failed   - the call returned a clear error (safe to fix and try again)
  unknown  - anything else (timeout, dropped connection, crash)

The last row for an item id is its final state. A final state of "attempt" or
"unknown" blocks every further write until a human resolves it, because the
first try may have gone through.

Standard library only. Python 3.9+.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class LedgerBlocked(RuntimeError):
    """Raised when an earlier write is in an unresolved state."""


class AlreadySent(RuntimeError):
    """Raised when the item id was already sent successfully."""


class WriteLedger:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ---------- reading ----------
    def rows(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def final_states(self) -> Dict[str, Dict[str, Any]]:
        final: Dict[str, Dict[str, Any]] = {}
        for r in self.rows():
            final[r["id"]] = r
        return final

    def unresolved(self) -> List[Dict[str, Any]]:
        return [r for r in self.final_states().values() if r["state"] in ("attempt", "unknown")]

    def was_sent(self, item_id: str) -> bool:
        r = self.final_states().get(item_id)
        return bool(r and r["state"] == "sent")

    def count_today(self, tz: Optional[_dt.tzinfo] = None) -> int:
        """Number of write attempts started today (in tz, default local time)."""
        today = _dt.datetime.now(tz).date().isoformat()
        return sum(1 for r in self.rows() if r["state"] == "attempt" and r["at"][:10] == today)

    def last_attempt_at(self) -> Optional[_dt.datetime]:
        ts = [r["at"] for r in self.rows() if r["state"] == "attempt"]
        return _dt.datetime.fromisoformat(max(ts)) if ts else None

    # ---------- writing ----------
    def _append(self, row: Dict[str, Any]) -> None:
        row.setdefault("at", _dt.datetime.now().astimezone().isoformat())
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def resolve(self, item_id: str, state: str, note: str) -> None:
        """Human-only: after checking the real system, mark an unresolved item sent or failed."""
        if state not in ("sent", "failed"):
            raise ValueError("state must be 'sent' or 'failed'")
        self._append({"id": item_id, "state": state, "resolved_by_human": True, "note": note})

    def guarded_write(self, item_id: str, payload: Any, send: Callable[[Any], Any],
                      is_clear_error: Callable[[BaseException], bool] = lambda e: False) -> Any:
        """Run send(payload) at most once per item id.

        is_clear_error(e) should return True only for errors where the server
        clearly refused the request (for example HTTP 400/401/403/422).
        Everything else is recorded as "unknown" and blocks the queue.
        """
        blocked = self.unresolved()
        if blocked:
            ids = ", ".join(r["id"] for r in blocked)
            raise LedgerBlocked(f"Unresolved earlier write(s): {ids}. Check them, then call resolve().")
        if self.was_sent(item_id):
            raise AlreadySent(item_id)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        self._append({"id": item_id, "state": "attempt", "payload_sha256": digest})
        try:
            result = send(payload)
        except BaseException as e:  # noqa: BLE001 - we must record every outcome
            state = "failed" if is_clear_error(e) else "unknown"
            self._append({"id": item_id, "state": state, "error": f"{type(e).__name__}: {e}"[:300]})
            raise
        self._append({"id": item_id, "state": "sent", "result": str(result)[:300]})
        return result
