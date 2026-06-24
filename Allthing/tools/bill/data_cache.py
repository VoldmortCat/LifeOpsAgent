"""全局账单数据缓存模块。

设计意图：
  - 每次 get_monthly_bill_data 或 get_date_range_bill_data 查询后，
    自动将结果缓存到此模块的全局 dict 中
  - 缓存自带标签（如 "202604" / "2026-04-12~2026-06-01"），
    方便 agent 判断当前缓存是否匹配后续需求
  - generate_bill_charts 可直接通过 cache_key 读取缓存数据，
    无需重新传 JSON
  - 缓存是覆盖式的：同一标签的后续查询会覆盖旧数据
  - get_cache_info 工具供 agent 查询当前缓存状态
"""

import time
from typing import Optional, List


# 全局缓存：{ "cache_key": { "label", "data", "record_count", "cached_at" } }
_cache = {}


def set_cache(key: str, label: str, data: list, record_count: int) -> str:
    """存入缓存，覆盖同 key 的旧数据。"""
    _cache[key] = {
        "label": label,
        "data": data,
        "record_count": record_count,
        "cached_at": time.time(),
    }
    return f"✅ 已缓存数据集 [{key}]：{label}，{record_count}条记录"


def get_cache(key: str) -> Optional[list]:
    """从缓存中读取数据集。未命中返回 None。"""
    entry = _cache.get(key)
    return entry["data"] if entry else None


def get_cache_info(key: str = "") -> str:
    """查询缓存信息。key 为空时返回全部缓存概览。"""
    import json
    if key and key in _cache:
        entry = _cache[key]
        return json.dumps({
            "key": key,
            "label": entry["label"],
            "record_count": entry["record_count"],
            "cached_seconds_ago": round(time.time() - entry["cached_at"], 1),
        }, ensure_ascii=False)
    elif key:
        return json.dumps({
            "error": f"缓存中无键 [{key}]",
            "available_keys": list(_cache.keys()),
        }, ensure_ascii=False)
    else:
        entries = [
            {"key": k, "label": v["label"], "record_count": v["record_count"],
             "cached_seconds_ago": round(time.time() - v["cached_at"], 1)}
            for k, v in _cache.items()
        ]
        return json.dumps({"total_cached": len(entries), "entries": entries}, ensure_ascii=False)


def clear_cache() -> None:
    """清空全部缓存。"""
    _cache.clear()


def get_cache_keys() -> List[str]:
    """返回当前所有缓存键。"""
    return list(_cache.keys())
