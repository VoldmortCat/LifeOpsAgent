#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
知识库文件导入脚本 — 支持增量导入 + SHA256 去重
用法: python scripts/import_knowledge.py [文件路径或目录]
"""
import sys
import os
import json
import hashlib
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.config_loader import config

TRACKER_FILE = Path(config.get("paths.knowledge_base_dir", "knowledge_base")) / ".import_tracker.json"


def load_tracker() -> dict:
    """加载已导入文件的追踪记录"""
    if TRACKER_FILE.exists():
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"imported": {}, "last_updated": None}


def save_tracker(tracker: dict):
    TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tracker["last_updated"] = datetime.now().isoformat()
    with open(TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(tracker, f, ensure_ascii=False, indent=2)


def file_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_md(filepath: str) -> tuple:
    """校验 .md 文件格式是否合法"""
    if not filepath.endswith(".md"):
        return False, "不是 .md 文件"
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        # 必须包含 ## 标题（作为段落分隔）
        if "## " not in content:
            return False, "缺少 ## 二级标题（段落分隔）"
        # 统计 ## 段落数作为数据量
        block_count = content.count("\n## ") + (1 if content.startswith("## ") else 0)
        if block_count < 2:
            return False, "至少需要2个 ## 段落块"
        return True, f"合法：{block_count} 个段落块"
    except Exception as e:
        return False, f"读取失败：{e}"


def import_file(filepath: str, tracker: dict, force: bool = False) -> tuple:
    """导入单个文件，返回（消息, 是否成功导入）"""
    abs_path = os.path.abspath(filepath)
    rel_path = os.path.relpath(abs_path, os.getcwd())

    # 1. 校验
    valid, msg = validate_md(abs_path)
    if not valid:
        return f"[ERROR] {rel_path}: {msg}", False

    # 2. 计算哈希
    sha = file_sha256(abs_path)

    # 3. 去重检查
    imported = tracker.get("imported", {})
    if sha in imported and not force:
        prev = imported[sha]
        return f"[SKIP] {rel_path}: 已导入过 (首次: {prev['first_imported']})", False

    # 4. 复制到 knowledge_base 对应子目录
    kb_dir = Path(config.get("paths.knowledge_base_dir", "knowledge_base"))
    # 按文件名推断分类（如 zhongshan_food → food）
    basename = os.path.basename(abs_path).lower()
    if "food" in basename or "restaurant" in basename:
        subdir = "food"
    elif "travel" in basename or "trip" in basename:
        subdir = "travel"
    else:
        subdir = "general"

    dest_dir = kb_dir / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / os.path.basename(abs_path)

    # 只在源文件不同时才复制
    if str(dest_path) != abs_path:
        with open(abs_path, "r", encoding="utf-8") as src:
            with open(dest_path, "w", encoding="utf-8") as dst:
                dst.write(src.read())

    # 5. 记录
    imported[sha] = {
        "file": os.path.basename(abs_path),
        "full_path": str(dest_path),
        "category": subdir,
        "sha256": sha,
        "first_imported": datetime.now().isoformat(),
        "size_bytes": os.path.getsize(abs_path),
    }
    tracker["imported"] = imported
    save_tracker(tracker)

    return f"[OK] {rel_path} -> knowledge_base/{subdir}/{os.path.basename(abs_path)}", True


def main():
    print("=" * 60)
    print("Knowledge Base Import Tool")
    print("=" * 60)

    tracker = load_tracker()
    imported = tracker.get("imported", {})
    print(f"已追踪文件: {len(imported)} 个")

    # 确定导入目标
    targets = sys.argv[1:] if len(sys.argv) > 1 else []

    if not targets:
        # 默认扫描 knowledge_base/ 下所有 .md
        kb_dir = Path(config.get("paths.knowledge_base_dir", "knowledge_base"))
        targets = list(kb_dir.rglob("*.md"))
        print(f"默认扫描 {kb_dir}/ 下 .md 文件...")
    else:
        # 展开目录
        expanded = []
        for t in targets:
            if os.path.isdir(t):
                expanded.extend(Path(t).rglob("*.md"))
            else:
                expanded.append(t)
        targets = expanded

    print(f"待处理: {len(targets)} 个文件\n")

    stats = {"new": 0, "skipped": 0, "error": 0}
    for t in targets:
        msg, ok = import_file(str(t), tracker)
        if ok:
            stats["new"] += 1
        elif "已导入过" in msg:
            stats["skipped"] += 1
        else:
            stats["error"] += 1
        print(f"  {msg}")

    print(f"\n{'=' * 60}")
    print(f"汇总: 新增 {stats['new']} | 跳过 {stats['skipped']} | 失败 {stats['error']}")
    print(f"追踪文件: {TRACKER_FILE}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()