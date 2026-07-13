from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import daily_session  # noqa: E402
import finalize_session  # noqa: E402


class OutputRoutingTests(unittest.TestCase):
    def test_daily_session_keeps_markdown_only_until_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "reports" / "run_20260713_test"
            args = SimpleNamespace(
                trade_date="2026-07-13",
                run_id="run_20260713_test",
                run_dir=run_dir,
                state_dir=root / "state",
                pasted_trades=None,
                trades_csv=None,
                journal=None,
                market_view=None,
                article_urls=None,
                article_excerpt=None,
                article_digest=None,
                positions=None,
                market_snapshot=None,
                research_pool=None,
                strict_balance=False,
            )

            result = daily_session.prepare_session(args)

            self.assertEqual(result, run_dir)
            self.assertTrue((run_dir / "index.md").exists())
            self.assertTrue((run_dir / "coach_note.md").exists())
            self.assertFalse((run_dir / "index.html").exists())
            self.assertFalse((run_dir / "coach_note.html").exists())
            manifest = (run_dir / "session_manifest.json").read_text(encoding="utf-8")
            self.assertIn("index_markdown", manifest)
            self.assertNotIn("index_html", manifest)

    def test_failed_finalize_does_not_publish_to_personal_site(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run_20260713_test"
            run_dir.mkdir()
            args = SimpleNamespace(
                run_dir=run_dir,
                trade_date="2026-07-13",
                overwrite_checklist=False,
                skip_personal_site=False,
            )
            with patch.object(finalize_session, "write_personal_site") as refresh:
                report = finalize_session.finalize(args)

            refresh.assert_not_called()
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["personal_site_skipped"], "session validation failed")

    def test_finalize_refreshes_personal_site_without_session_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run_20260713_test"
            run_dir.mkdir()
            (run_dir / "evidence_packet.md").write_text("# 证据\n", encoding="utf-8")
            (run_dir / "research_pool.md").write_text("# 内容\n\n研究池不是买入名单。\n", encoding="utf-8")
            (run_dir / "xueqiu_post.md").write_text("# 内容\n\n不构成投资建议。\n", encoding="utf-8")
            coach = "\n".join(f"## {heading}\n\n已记录。" for heading in finalize_session.REQUIRED_COACH_NOTE_HEADINGS)
            (run_dir / "coach_note.md").write_text(coach, encoding="utf-8")
            args = SimpleNamespace(
                run_dir=run_dir,
                trade_date="2026-07-13",
                overwrite_checklist=False,
                skip_personal_site=False,
            )
            site_paths = {"site": Path(tmp) / "personal_site" / "index.html"}

            with patch.object(finalize_session, "write_personal_site", return_value=site_paths):
                report = finalize_session.finalize(args)

            self.assertEqual(report["status"], "ok")
            self.assertIn("markdown_outputs", report)
            self.assertNotIn("rendered_html", report)
            self.assertEqual(report["personal_site"]["site"], str(site_paths["site"]))
            self.assertFalse((run_dir / "coach_note.html").exists())


if __name__ == "__main__":
    unittest.main()
