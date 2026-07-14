import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from xueqiu_watchlist_sync import build_watchlist_manifest, mark_manifest_synced  # noqa: E402


def pool_markdown(codes):
    rows = ["# 明日研究股票池", "", "| 股票代码 | 股票名称 |", "| --- | --- |"]
    rows.extend(f"| {code} | 股票{index} |" for index, code in enumerate(codes, 1))
    return "\n".join(rows) + "\n"


class XueqiuWatchlistSyncTests(unittest.TestCase):
    def test_manifest_uses_exact_canonical_pool(self):
        codes = ["301396", "603259", "300347", "300760", "600276", "600036", "600919", "002409", "300236", "300346", "300655", "002156", "002185", "300394", "000977"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "research_pool.md"
            path.write_text(pool_markdown(codes), encoding="utf-8")
            manifest = build_watchlist_manifest(path, run_id="run-test", trade_date="2026-07-13")
        self.assertEqual(manifest["status"], "pending_chrome_sync")
        self.assertEqual(manifest["count"], 15)
        self.assertEqual([stock["stock_code"] for stock in manifest["stocks"]], codes)
        self.assertEqual(manifest["stocks"][0]["quote_url"], "https://xueqiu.com/S/SZ301396")

    def test_incomplete_or_688_pool_is_blocked(self):
        codes = ["301396", "688001"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "research_pool.md"
            path.write_text(pool_markdown(codes), encoding="utf-8")
            manifest = build_watchlist_manifest(path)
        self.assertEqual(manifest["status"], "blocked_incomplete_pool")
        self.assertIn("expected_15_stocks_got_2", manifest["errors"])
        self.assertIn("688_stock_not_tradable_for_account", manifest["errors"])

    def test_mark_synced_requires_exact_code_set(self):
        codes = ["301396", "603259", "300347", "300760", "600276", "600036", "600919", "002409", "300236", "300346", "300655", "002156", "002185", "300394", "000977"]
        with tempfile.TemporaryDirectory() as tmp:
            pool_path = Path(tmp) / "research_pool.md"
            manifest_path = Path(tmp) / "xueqiu_watchlist_sync.json"
            pool_path.write_text(pool_markdown(codes), encoding="utf-8")
            manifest_path.write_text(json.dumps(build_watchlist_manifest(pool_path), ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                mark_manifest_synced(manifest_path, codes[:-1])
            synced = mark_manifest_synced(manifest_path, reversed(codes))
        self.assertEqual(synced["status"], "synced")
        self.assertEqual(sorted(synced["verified_codes"]), sorted(codes))


if __name__ == "__main__":
    unittest.main()
