#!/usr/bin/env python3
"""Initialize ignored private state files from public templates."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_DIR = ROOT / "templates" / "state"
DEFAULT_STATE_DIR = ROOT / "state"


STATE_FILES = [
    "coach_memory.md",
    "coach_lenses.md",
    "position_storylines.md",
    "personal_trading_modes.md",
    "research_pool_protocol.md",
    "decision_events.md",
    "trading_modes.json",
    "discipline_feed.json",
]


def init_state(template_dir: Path, state_dir: Path, force: bool = False) -> list[tuple[str, str]]:
    state_dir.mkdir(parents=True, exist_ok=True)
    results: list[tuple[str, str]] = []
    for filename in STATE_FILES:
        source = template_dir / filename
        target = state_dir / filename
        if not source.exists():
            raise FileNotFoundError(f"missing template: {source}")
        if target.exists() and not force:
            results.append((filename, "kept"))
            continue
        existed = target.exists()
        shutil.copyfile(source, target)
        results.append((filename, "overwritten" if existed else "created"))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化本地私有教练状态文件。")
    parser.add_argument("--template-dir", type=Path, default=DEFAULT_TEMPLATE_DIR)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--force", action="store_true", help="覆盖已有状态文件。谨慎使用。")
    args = parser.parse_args()

    results = init_state(args.template_dir, args.state_dir, force=args.force)
    for filename, status in results:
        print(f"{status}: {args.state_dir / filename}")
    print("state/ 默认被 Git 忽略；不要提交真实教练记忆或交易状态。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
