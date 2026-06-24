"""
省钱计划持久化工具 — JSON 文件存储用户财务目标。

文件位置: data/savings/goals.json
格式:
{
  "monthly_budget": 3000,
  "current_spending": 2500,
  "days_remaining": 15,
  "month": "202605",
  "goals": [
    {"name": "买Switch", "target": 2000, "saved": 500, "created_at": "2026-05-26"}
  ],
  "updated_at": "2026-05-26T20:00:00"
}
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool

SAVINGS_DIR = Path("data/savings")
GOALS_FILE = SAVINGS_DIR / "goals.json"


def _load() -> dict:
    if GOALS_FILE.exists():
        try:
            with open(GOALS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"monthly_budget": 0, "current_spending": 0, "days_remaining": 0, "month": "", "goals": [], "updated_at": ""}


def _save(data: dict):
    SAVINGS_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    with open(GOALS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@tool
def set_savings_goal(goal_name: str = "日常消费预算", target_amount: float = 0, monthly_budget: float = 0, current_spending: float = 0, days_remaining: int = 0) -> str:
    """
    设置或更新省钱目标 / 预算约束。当用户提到预算金额时必须调用。

    Args:
        goal_name: 目标名称，如"买Switch"、"去日本旅行"、"日常消费预算"。默认"日常消费预算"
        target_amount: 目标金额（元），用户说了预算就填预算金额
        monthly_budget: 月预算（元），用户说了就填，没说不填
        current_spending: 本月已支出金额（元），用户说了就填，没说不填
        days_remaining: 距离下次发工资/收入的天数，用户说了就填，没说不填、默认用当月剩余天数

    Returns:
        JSON 格式的当前财务状况摘要
    """
    data = _load()

    if monthly_budget > 0:
        data["monthly_budget"] = monthly_budget
    if current_spending > 0:
        data["current_spending"] = current_spending
    if days_remaining > 0:
        data["days_remaining"] = days_remaining

    now_str = datetime.now().strftime("%Y-%m-%d")
    now_month = datetime.now().strftime("%Y%m")
    if not data.get("month"):
        data["month"] = now_month

    existing = next((g for g in data["goals"] if g["name"] == goal_name), None)
    if existing:
        existing["target"] = target_amount
    else:
        data["goals"].append({
            "name": goal_name,
            "target": target_amount,
            "saved": 0,
            "created_at": now_str,
        })

    _save(data)

    remaining = data["monthly_budget"] - data["current_spending"]
    # 日均计算：优先用用户指定的剩余天数，否则按当月剩余天数
    if data.get("days_remaining", 0) > 0:
        days = data["days_remaining"]
    else:
        days = max(30 - datetime.now().day, 1)
    goals_str = "\n".join(
        f"  - {g['name']}: 目标{g['target']}元, 已存{g['saved']}元, 进度{g['saved']/g['target']*100:.0f}%"
        for g in data["goals"]
    )

    return json.dumps({
        "status": "ok",
        "message": f"已记录省钱目标「{goal_name}」",
        "summary": {
            "月预算": f"{data['monthly_budget']}元",
            "本月已支出": f"{data['current_spending']}元",
            "剩余可支配": f"{remaining}元",
            "剩余天数": f"{days}天",
            "日均可用": f"{remaining / days:.0f}元" if remaining > 0 else "已超支",
            "省钱目标": goals_str if data["goals"] else "无",
        },
    }, ensure_ascii=False, indent=2)


@tool
def update_saved_amount(goal_name: str, amount: float) -> str:
    """
    更新省钱目标的已存金额（累计追加）。

    Args:
        goal_name: 省钱目标名称
        amount: 本次新增的存款金额（元）

    Returns:
        JSON 格式的更新结果
    """
    data = _load()
    existing = next((g for g in data["goals"] if g["name"] == goal_name), None)
    if not existing:
        return json.dumps({"error": f"未找到目标「{goal_name}」，请先使用 set_savings_goal 创建"}, ensure_ascii=False)

    existing["saved"] += amount
    _save(data)

    pct = existing["saved"] / existing["target"] * 100
    return json.dumps({
        "status": "ok",
        "goal": goal_name,
        "saved": existing["saved"],
        "target": existing["target"],
        "remaining": existing["target"] - existing["saved"],
        "progress": f"{pct:.0f}%",
    }, ensure_ascii=False, indent=2)


@tool
def get_financial_context() -> str:
    """
    读取当前用户的完整财务状况：月预算、已支出、剩余可支配、省钱目标及进度。
    在推荐餐厅/出行/消费前应调用此工具，确保推荐不超出用户预算。

    Returns:
        JSON 格式的财务状况全景
    """
    data = _load()

    if data["monthly_budget"] == 0 and not data["goals"]:
        return json.dumps({"has_data": False, "message": "暂无财务数据，用户尚未设置预算或省钱目标"}, ensure_ascii=False)

    remaining = data["monthly_budget"] - data["current_spending"]
    if data.get("days_remaining", 0) > 0:
        days_left = data["days_remaining"]
    else:
        days_left = max(30 - datetime.now().day, 1)

    goals_list = []
    for g in data["goals"]:
        goals_list.append({
            "name": g["name"],
            "target": g["target"],
            "saved": g["saved"],
            "remaining": g["target"] - g["saved"],
            "progress_pct": round(g["saved"] / g["target"] * 100, 1) if g["target"] > 0 else 0,
        })

    return json.dumps({
        "has_data": True,
        "month": data.get("month", ""),
        "monthly_budget": data["monthly_budget"],
        "current_spending": data["current_spending"],
        "remaining_budget": remaining,
        "daily_available": round(remaining / days_left, 1) if remaining > 0 else 0,
        "budget_status": "正常" if remaining > 0 else "已超支",
        "savings_goals": goals_list,
    }, ensure_ascii=False, indent=2)
