#!/usr/bin/env python3
"""Append reviewed coach updates to private state files."""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
ALLOWED_STATE_FILES = {
    "coach_memory.md",
    "coach_lenses.md",
    "position_storylines.md",
    "personal_trading_modes.md",
    "research_pool_protocol.md",
    "decision_events.md",
}


def resolve_state_file(state_dir: Path, name: str) -> Path:
    if name not in ALLOWED_STATE_FILES:
        raise SystemExit(f"不允许写入该状态文件：{name}")
    target = (state_dir / name).resolve()
    state_root = state_dir.resolve()
    if state_root not in target.parents and target != state_root:
        raise SystemExit("状态文件路径越界。")
    return target


def read_update(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit("更新片段为空。")
    return text


def append_update(target: Path, update_text: str, trade_date: str, source: str, backup: bool = True) -> Path | None:
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if target.exists() and backup:
        backup_path = target.with_suffix(target.suffix + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.copyfile(target, backup_path)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    block = "\n".join(
        [
            "",
            f"## Update - {trade_date}",
            "",
            f"Source: `{source}`",
            "",
            update_text,
            "",
        ]
    )
    target.write_text(existing.rstrip() + "\n" + block, encoding="utf-8")
    return backup_path


def main() -> int:
    parser = argparse.ArgumentParser(description="把已审核的教练状态更新片段追加到私有 state 文件。")
    parser.add_argument("state_file", choices=sorted(ALLOWED_STATE_FILES))
    parser.add_argument("--update", type=Path, required=True, help="已审核的 Markdown 更新片段。")
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--source", default="", help="来源 run 或手记路径。")
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    target = resolve_state_file(args.state_dir, args.state_file)
    update_text = read_update(args.update)
    backup_path = append_update(target, update_text, args.trade_date, args.source or str(args.update), backup=not args.no_backup)
    print(f"updated: {target}")
    if backup_path:
        print(f"backup: {backup_path}")
    print("注意：state/ 默认被 Git 忽略；不要提交真实交易状态。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
