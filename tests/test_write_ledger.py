import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from write_ledger import WriteLedger, LedgerBlocked, AlreadySent  # noqa: E402


class TestWriteLedger(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "ledger.jsonl"

    def test_sends_once(self):
        lg, calls = WriteLedger(self.path), []
        lg.guarded_write("a", {"x": 1}, lambda p: calls.append(p) or "ok")
        with self.assertRaises(AlreadySent):
            lg.guarded_write("a", {"x": 1}, lambda p: calls.append(p))
        self.assertEqual(len(calls), 1)

    def test_unknown_blocks_until_resolved(self):
        lg = WriteLedger(self.path)

        def timeout(p):
            raise TimeoutError("read timed out")

        with self.assertRaises(TimeoutError):
            lg.guarded_write("a", {}, timeout)
        with self.assertRaises(LedgerBlocked):
            lg.guarded_write("b", {}, lambda p: "ok")
        lg.resolve("a", "failed", "checked: it never arrived")
        self.assertEqual(lg.guarded_write("b", {}, lambda p: "ok"), "ok")

    def test_clear_error_does_not_block(self):
        lg = WriteLedger(self.path)

        def refused(p):
            raise ValueError("HTTP 400")

        with self.assertRaises(ValueError):
            lg.guarded_write("a", {}, refused, is_clear_error=lambda e: isinstance(e, ValueError))
        self.assertEqual(lg.unresolved(), [])

    def test_crash_mid_send_leaves_attempt(self):
        lg = WriteLedger(self.path)
        lg._append({"id": "a", "state": "attempt"})  # simulate a process killed after writing the attempt row
        with self.assertRaises(LedgerBlocked):
            lg.guarded_write("b", {}, lambda p: "ok")


if __name__ == "__main__":
    unittest.main()
