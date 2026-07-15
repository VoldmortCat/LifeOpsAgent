import sys
import os
import json
import asyncio
import glob
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from langgraph.checkpoint.sqlite import SqliteSaver
from graph.graph_builder import LifeOpsGraphRouter
from monitoring import get_logger, init_langsmith

logger = get_logger("lifeops.server")

langsmith_enabled = init_langsmith()
if langsmith_enabled:
    print("[LangSmith] 追踪已启用 → https://smith.langchain.com")
else:
    print("[LangSmith] 未启用（设置 LANGCHAIN_API_KEY 环境变量以启用）")

app = FastAPI(title="LifeOps Agent API", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
BILL_DIR = DATA_DIR / "bills"
CHART_DIR = DATA_DIR / "bills" / "charts"
KB_DIR = BASE_DIR / "knowledge_base"
os.makedirs(BILL_DIR, exist_ok=True)
os.makedirs(CHART_DIR, exist_ok=True)

checkpoint_db = str(DATA_DIR / "checkpoints" / "lifeops_checkpoints.db")
os.makedirs(os.path.dirname(checkpoint_db), exist_ok=True)


_checkpointer_ctx = SqliteSaver.from_conn_string(checkpoint_db)
_checkpointer = _checkpointer_ctx.__enter__()
_router = LifeOpsGraphRouter(checkpointer=_checkpointer)


def _get_router():
    return _router


# ====================== 系统配置 API ======================

BAIDU_MAPS_AK = os.environ.get("BAIDU_MAPS_BROWSER_AK", "")

@app.get("/api/config/map-ak")
def get_map_ak():
    ak = BAIDU_MAPS_AK or os.environ.get("BAIDU_MAPS_API_KEY", "")
    return {"ok": True, "ak": ak}


# ====================== 用户配置 API ======================

from pydantic import BaseModel
from typing import Dict

class UserConfigPayload(BaseModel):
    config: Dict[str, object]

@app.get("/api/user-config")
def get_user_config():
    """返回当前用户配置（密码脱敏）"""
    from config.config_loader import config as cfg_loader
    return {"ok": True, "config": cfg_loader.get_user_config()}

@app.post("/api/user-config")
def save_user_config(payload: UserConfigPayload):
    """保存用户配置到 user_config.yml"""
    from config.config_loader import config as cfg_loader
    try:
        cfg_loader.save_user_config(payload.config)
        return {"ok": True, "message": "配置已保存"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ====================== 账单 API ======================

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def _load_bill_df(period: str = "month"):
    now = datetime.now()
    if period == "week":
        start = now - timedelta(days=7)
        months = []
        cur = start
        while cur <= now:
            m = cur.strftime("%Y%m")
            if m not in months:
                months.append(m)
            cur = cur.replace(day=28) + timedelta(days=4)
            cur = cur.replace(day=1)
    elif period == "year":
        months = [f"{now.year}{m:02d}" for m in range(1, now.month + 1)]
    else:
        months = [now.strftime("%Y%m")]

    dfs = []
    for m in months:
        fp = BILL_DIR / f"{m}.csv"
        if fp.exists():
            df = pd.read_csv(fp, encoding="utf-8-sig", parse_dates=["交易时间", "交易日期"])
            if "金额(元)" in df.columns:
                df["金额(元)"] = pd.to_numeric(df["金额(元)"], errors="coerce")
            dfs.append(df)

    if not dfs:
        return pd.DataFrame()

    df = pd.concat(dfs, ignore_index=True)
    if period == "week":
        df = df[df["交易日期"] >= pd.Timestamp(start.date())]
    return df.sort_values(by="交易时间", ascending=False)


@app.get("/api/bills/summary")
def get_bill_summary(period: str = "month"):
    df = _load_bill_df(period)
    if df.empty:
        return {"period": period, "stats": {"expense": 0, "income": 0, "balance": 0, "dailyAvg": 0},
                "categories": [], "items": [], "charts": {}}

    exp_df = df[df["收/支"] == "支出"] if "收/支" in df.columns else df[df["金额(元)"] < 0]
    inc_df = df[df["收/支"] == "收入"] if "收/支" in df.columns else df[df["金额(元)"] > 0]

    total_exp = round(float(exp_df["金额(元)"].sum()), 2) if not exp_df.empty else 0
    total_inc = round(float(inc_df["金额(元)"].sum()), 2) if not inc_df.empty else 0
    days = max(1, (df["交易日期"].max() - df["交易日期"].min()).days + 1) if not df.empty else 1

    categories = []
    if not exp_df.empty and "交易类型" in exp_df.columns:
        cat_data = exp_df.groupby("交易类型")["金额(元)"].sum().sort_values(ascending=False)
        categories = [{"name": k, "amount": round(float(v), 2)} for k, v in cat_data.items()]

    items = []
    for _, row in df.head(30).iterrows():
        t = row.get("交易时间")
        ts = t.strftime("%m-%d") if pd.notna(t) else ""
        items.append({
            "category": str(row.get("交易类型", "")),
            "commodity": str(row.get("商品", "")),
            "amount": f'{float(row.get("金额(元)", 0)):.2f}',
            "type": "income" if str(row.get("收/支", "")) == "收入" else "expense",
            "date": ts,
        })

    return {
        "period": period,
        "stats": {
            "expense": f"{total_exp:.2f}",
            "income": f"{total_inc:.2f}",
            "balance": f"{total_inc - total_exp:.2f}",
            "dailyAvg": f"{total_exp / days:.2f}",
        },
        "categories": categories,
        "items": items,
        "charts": {
            "trend": f"/api/bills/chart-file?period={period}&type=trend",
            "category": f"/api/bills/chart-file?period={period}&type=category",
        },
    }


@app.get("/api/bills/chart-file")
def get_bill_chart_file(period: str = "month", type: str = "trend"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
    plt.rcParams["axes.unicode_minus"] = False

    df = _load_bill_df(period)
    if df.empty:
        return {"error": "no data"}

    chart_path = CHART_DIR / f"bill_{period}_{type}.png"

    if type == "category":
        exp_df = df[df["收/支"] == "支出"] if "收/支" in df.columns else pd.DataFrame()
        if exp_df.empty or "交易类型" not in exp_df.columns:
            return {"error": "no category data"}
        cat = exp_df.groupby("交易类型")["金额(元)"].sum().sort_values(ascending=True)
        plt.figure(figsize=(8, 5))
        plt.barh(cat.index, cat.values, color="#007aff")
        plt.title("支出分类分布", fontsize=14)
        plt.xlabel("金额（元）")
        plt.tight_layout()
    else:
        daily = df.groupby([df["交易日期"], "收/支"])["金额(元)"].sum().unstack(fill_value=0)
        plt.figure(figsize=(12, 4))
        colors = ["#4cd964", "#dd524d"]
        cols = [c for c in ["收入", "支出"] if c in daily.columns]
        for idx, col in enumerate(cols[:2]):
            plt.fill_between(daily.index, 0, daily[col], alpha=0.15, color=colors[idx])
            plt.plot(daily.index, daily[col], marker="o", markersize=4, linewidth=2, color=colors[idx], label=col)
        plt.title("每日收支趋势", fontsize=14)
        plt.legend(loc="upper right")
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()

    plt.savefig(chart_path, dpi=200, bbox_inches="tight")
    plt.close()
    return FileResponse(chart_path, media_type="image/png")


# ====================== 文档中心 API ======================

ALLOWED_EXTENSIONS = {".md", ".pdf", ".txt", ".csv", ".json", ".yml", ".yaml"}


@app.get("/api/docs/list")
def list_docs():
    docs = []
    for root, dirs, files in os.walk(KB_DIR):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                continue
            full = Path(root) / fname
            rel = full.relative_to(KB_DIR)
            docs.append({
                "name": fname,
                "path": str(rel).replace("\\", "/"),
                "category": str(rel.parent) if str(rel.parent) != "." else "未分类",
                "size": full.stat().st_size,
                "modified": datetime.fromtimestamp(full.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "ext": ext,
            })
    docs.sort(key=lambda d: d["modified"], reverse=True)
    categories = {}
    for d in docs:
        cat = d["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(d)
    return {"total": len(docs), "categories": categories, "list": docs}


@app.post("/api/docs/import")
async def import_doc(file: UploadFile = File(...), category: str = "other"):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return {"ok": False, "error": f"不支持的文件格式: {ext}"}

    cat_map = {
        "food": "food",
        "general": "general",
        "other": "other",
        "美食": "food",
        "通用": "general",
        "其他": "other",
    }
    cat = cat_map.get(category, "other")

    target_dir = KB_DIR / cat
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / file.filename

    content = await file.read()
    with open(target_path, "wb") as f:
        f.write(content)

    return {"ok": True, "filename": file.filename, "path": f"{cat}/{file.filename}",
            "size": len(content), "category": cat}


@app.get("/api/docs/file/{path:path}")
def get_doc_file(path: str):
    full_path = KB_DIR / path
    if not full_path.exists():
        return {"ok": False, "error": "文件不存在"}
    ext = full_path.suffix.lower()
    media_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".csv": "text/csv; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".yml": "text/yaml; charset=utf-8",
        ".yaml": "text/yaml; charset=utf-8",
    }
    media_type = media_map.get(ext, "application/octet-stream")
    return FileResponse(full_path, media_type=media_type, filename=full_path.name)


@app.get("/api/docs/preview/{path:path}")
def preview_doc(path: str):
    full_path = KB_DIR / path
    if not full_path.exists():
        return {"ok": False, "error": "文件不存在"}

    ext = full_path.suffix.lower()
    if ext in (".pdf", ".png", ".jpg", ".jpeg"):
        return {"ok": True, "filename": full_path.name, "ext": ext,
                "content": "", "is_binary": True, "file_url": f"/api/docs/file/{path}"}
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        if len(content) > 5000:
            content = content[:5000] + "\n\n... (内容已截断)"
        return {"ok": True, "filename": full_path.name, "ext": ext, "content": content}
    except UnicodeDecodeError:
        return {"ok": True, "filename": full_path.name, "ext": ext,
                "content": "[二进制文件]", "is_binary": True, "file_url": f"/api/docs/file/{path}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ====================== RAG 监控 API ======================

@app.get("/api/rag/status")
def get_rag_status():
    try:
        from monitoring.rag_logger import RAGMonitor
        from dataclasses import asdict
        monitor = RAGMonitor.get_instance()
        entries = monitor.get_recent_entries(20)
        logs = [asdict(e) for e in entries]
        return {"ok": True, "logs_count": len(logs), "logs": logs}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/rag/test")
def run_rag_test():
    yaml_path = BASE_DIR / "monitoring" / "test_cases.yml"
    if not yaml_path.exists():
        return {"ok": False, "error": f"测试用例文件不存在: {yaml_path}"}
    try:
        from monitoring.test_runner import load_test_cases, run_evaluation
        cases = load_test_cases(str(yaml_path))
        report = run_evaluation(cases)
        return {"ok": True, "report": report}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ====================== 对话管理 API ======================

@app.get("/api/conversations")
def get_conversations():
    return {"conversations": []}


@app.delete("/api/conversations/{thread_id}")
def delete_conversation(thread_id: str):
    return {"ok": True, "thread_id": thread_id}


# ====================== WebSocket 聊天 ======================

@app.websocket("/chat/{thread_id}")
async def chat_websocket(websocket: WebSocket, thread_id: str):
    await websocket.accept()
    logger.info("WS 连接建立: thread_id=%s", thread_id)

    router = _get_router()

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            user_input = msg.get("content", "")
            msg_type = msg.get("type", "message")

            if msg_type != "message" or not user_input.strip():
                continue

            await websocket.send_json({"type": "thinking", "content": "正在思考..."})

            # 每次请求前清空上一次的 travel 地图数据残留，防止跨请求污染
            try:
                from graph.travel_node import _last_travel_map_data
                import graph.travel_node as tn
                tn._last_travel_map_data = None
            except (ImportError, AttributeError):
                pass

            full_text = await asyncio.to_thread(router.route, user_input, thread_id)

            # 检查 Travel Agent 是否生成了地图数据，如果有则先推送地图
            try:
                from graph.travel_node import get_travel_map_data
                map_data = get_travel_map_data()
                if map_data:
                    logger.info(f"[WS] Travel map_data: type={map_data.get('type')}, points={len(map_data.get('points',[]))}")
                    await websocket.send_json({"type": "map_data", "data": map_data})
                else:
                    logger.info("[WS] Travel map_data: None (无地图数据)")
            except Exception as e:
                logger.warning(f"[WS] Travel map_data 发送异常: {e}")

            chunk_size = 3
            for i in range(0, len(full_text), chunk_size):
                await websocket.send_json({
                    "type": "text",
                    "content": full_text[i:i + chunk_size],
                })
                await asyncio.sleep(0.02)

            await websocket.send_json({"type": "done"})

    except WebSocketDisconnect:
        logger.info("WS 连接断开: thread_id=%s", thread_id)
    except Exception as e:
        logger.error("WS 错误: %s", e)
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass


# ====================== 启动 ======================

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("[LifeOps] Agent API Server V3.0")
    print("   [REST] API: http://0.0.0.0:8000")
    print("   [WS] WebSocket: ws://0.0.0.0:8000/chat/{thread_id}")
    print("   [BILL] /api/bills/*")
    print("   [DOCS] /api/docs/*")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
