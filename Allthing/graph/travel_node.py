"""Travel Agent 子图 — ReAct 循环：
LLM 观察 → 决策（调工具/回复）→ 工具执行 → 结果反馈 → 循环，直到 LLM 决定直接回复。

职责边界：
- 本模块只负责 Travel Agent 的 ReAct 循环编排和地图数据提取
- 提示词在 prompts/ 中管理，通过 assembler.py 拼接
- 工具列表通过 _build_travel_tools() 动态组装（优先 MCP 百度地图）
- 对外接口 run_travel_agent() 供主 Agent 的 cross_agent.py 调用
"""

import json
import logging
import math
from typing import Optional, Dict, Any, Annotated, List

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import (
    BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage
)
from langgraph.graph.message import add_messages

logger = logging.getLogger("lifeops.travel")

from tools.knowledge.knowledge_tools import search_knowledge
from tools.time.time_tools import get_current_time
from tools.savings.savings_tools import get_financial_context, set_savings_goal
from prompts.assembler import assemble_travel_prompt
from .tool_tracer import TracedToolNode, dump_reasoning


def _build_travel_tools(allow_cross_agent: bool = True) -> list:
    """动态构建 Travel Agent 工具列表：优先使用 MCP 百度地图工具，失败时 fallback 到 @tool。

    百度地图 6 工具 → MCP Server（mcp-server-baidu-maps，独立进程）
    其他工具 → 直接 @tool 函数
    """
    from tools.maps.baidu_maps_mcp import get_baidu_mcp_tools

    mcp_baidu = get_baidu_mcp_tools()

    non_baidu = [
        search_knowledge,
        get_current_time,
        get_financial_context,
        set_savings_goal,
    ]
    if allow_cross_agent:
        from .cross_agent import query_bill_budget
        non_baidu.append(query_bill_budget)

    if mcp_baidu:
        return list(mcp_baidu) + non_baidu
    else:
        from tools.maps import (
            search_nearby_places, get_place_details, search_and_get_details,
            get_route_plan, get_weather_by_location, geocode_address,
        )
        return [
            search_nearby_places, get_place_details, search_and_get_details,
            get_route_plan, get_weather_by_location, geocode_address,
        ] + non_baidu

# ---- LLM 工厂 ----
from langchain_core.language_models import BaseChatModel
from llm.llm_registry import get_travel_llm

_travel_llm: BaseChatModel = None


def _get_travel_llm() -> BaseChatModel:
    global _travel_llm
    if _travel_llm is None:
        _travel_llm = get_travel_llm()
    return _travel_llm


# ---- 内部 State（仅用于 ReAct 子图，不对外暴露） ----
class TravelSubState(dict):
    messages: Annotated[List[BaseMessage], add_messages]
    data_status: str
    financial_context: Optional[Dict[str, Any]]
    cross_agent_request: Optional[Dict[str, Any]]


# ---- 对外接口：沙箱执行 ----

_last_travel_map_data: Optional[Dict[str, Any]] = None


def get_travel_map_data() -> Optional[Dict[str, Any]]:
    """供 server.py 调用：获取最近一次 Travel Agent 生成的地图可视化数据，读取后清空。"""
    global _last_travel_map_data
    data = _last_travel_map_data
    _last_travel_map_data = None
    return data


def _print_final_map_data(map_data: Dict[str, Any]):
    """在控制台打印最终提供给前端的地图数据，方便调试"""
    print(f"\n{'='*60}")
    print(f"[DEBUG] ✅ 准备提供给前端的地图数据")
    print(f"{'='*60}")
    
    print(f"\n📌 类型: {map_data.get('type', 'unknown')}")
    print(f"📍 中心点: {map_data.get('center', [])}")
    print(f"🔍 缩放: {map_data.get('zoom', 0)}")
    
    points = map_data.get('points', [])
    print(f"\n📍 点列表 ({len(points)} 个):")
    for i, p in enumerate(points):
        print(f"  [{i}] {p.get('name', '?')} | {p.get('tag', '')} "
              f"| lng={p.get('lng', 0)}, lat={p.get('lat', 0)}")
    
    route = map_data.get('route')
    if route:
        print(f"\n🛤️ 路线: {route.get('mode', '')} | {route.get('duration', '')} | {route.get('distance', '')}")
    
    polyline = map_data.get('polyline_points', [])
    print(f"\n🛤️ 路线坐标点 ({len(polyline)} 个):")
    if polyline:
        sample = polyline[:3]
        for i, pt in enumerate(sample):
            print(f"  [{i}] lng={pt[0]}, lat={pt[1]}")
        if len(polyline) > 3:
            print(f"  ... 共 {len(polyline)} 个点")
    
    print(f"\n{'='*60}")
    print(f"[DEBUG] 完整 JSON 数据:")
    print(f"{'='*60}")
    filtered = {k: v for k, v in map_data.items() if k != 'polyline_points'}
    import json as _json
    print(_json.dumps(filtered, ensure_ascii=False, indent=2))
    print(f"{'='*60}\n")


# ---- 地图数据提取和 fallback ----

def _unwrap_mcp_response(content: str) -> Optional[dict]:
    """通用 MCP 响应解包：处理 [[{type,text,id}]] 双层嵌套。

    ToolMessage 内容可能是：
      [[{"type":"text","text":"{...}","id":"..."}]]   — 双层数组
      [{"type":"text","text":"{...}","id":"..."}]     — 单层数组
      {"result":{...}}                                — 直接 JSON
    返回解包后的 dict（如 {"result":{...}}），失败返回 None。
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None

    # 逐层剥离外层 list
    while isinstance(data, list) and len(data) > 0:
        data = data[0]

    # 如果得到的是 MCP content block {type, text, id}，继续解 text
    if isinstance(data, dict) and "text" in data:
        try:
            data = json.loads(data["text"])
        except (json.JSONDecodeError, TypeError):
            return None

    if isinstance(data, dict):
        return data
    return None


def _parse_mcp_geocode_response(content: str) -> Optional[Dict[str, float]]:
    """从 map_geocode MCP 返回的嵌套 JSON 中提取 lng/lat"""
    geo = _unwrap_mcp_response(content)
    if geo is None:
        return None
    try:
        result = geo.get("result", {})
        loc = result.get("location", {})
        lng, lat = loc.get("lng"), loc.get("lat")
        if lng is not None and lat is not None:
            # 验证坐标是否在合理范围内（中国境内）
            if 73 <= float(lng) <= 135 and 3 <= float(lat) <= 54:
                return {"lng": float(lng), "lat": float(lat)}
            else:
                logger.warning(f"[GEOCODE] 坐标超出中国范围: lng={lng}, lat={lat}")
                return None
        return None
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def _parse_mcp_poi_response(content: str) -> list:
    """从 map_search_places MCP 返回的嵌套 JSON 中提取 POI 列表"""
    poi_data = _unwrap_mcp_response(content)
    if poi_data is None:
        return []
    try:
        results = poi_data.get("results", [])
        pois = []
        for r in results:
            loc = r.get("location", {})
            pois.append({
                "name": r.get("name", ""),
                "lng": float(loc.get("lng", 0)),
                "lat": float(loc.get("lat", 0)),
                "address": r.get("address", ""),
                "uid": r.get("uid", ""),
                "rating": str(r.get("detail_info", {}).get("overall_rating", "") or r.get("rating", "") or ""),
                "price": str(r.get("detail_info", {}).get("price", "") or ""),
                "tag": r.get("detail_info", {}).get("tag", "") or "",
            })
        return pois
    except (json.JSONDecodeError, TypeError, KeyError):
        return []


def _filter_poi_to_mentioned(poi_map_data: dict, final_reply: str) -> dict:
    """从 POI 列表中过滤出在 Agent 最终回复中被提及的店铺"""
    points = poi_map_data.get("points", [])
    mentioned = [p for p in points if p.get("name", "") and p["name"] in final_reply]
    if not mentioned:
        return poi_map_data
    return {
        "type": poi_map_data.get("type", "poi_list"),
        "center": poi_map_data.get("center", []),
        "zoom": poi_map_data.get("zoom", 14),
        "points": mentioned,
    }


def _build_data_brief(messages: list) -> str:
    """从历史消息中提取工具返回数据摘要"""
    lines = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            name = getattr(msg, "name", "?")
            content = msg.content or ""
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(f"[{name}]: {content}")
    return "\n".join(lines) if lines else "暂无数据"


def _extract_map_data(messages: list) -> Optional[Dict[str, Any]]:
    """从 Travel Agent 的消息历史中提取地图可视化数据供前端渲染。

    提取优先级：
    1. map_directions 的 ToolMessage → 构造 route 类型地图数据
    2. map_search_places / search_nearby_places 的 ToolMessage → 构造 poi_list 类型
    3. 都没有但有 geocode → fallback 构造简单路线
    """
    print(f"\n{'='*60}")
    print(f"[DEBUG] _extract_map_data called with {len(messages)} messages")
    print(f"{'='*60}\n")
    for i, msg in enumerate(messages):
        print(f"[DEBUG] Message {i}: type={type(msg)}")
        if isinstance(msg, ToolMessage):
            name = getattr(msg, "name", "?")
            content = msg.content or ""
            print(f"[DEBUG]   ToolMessage: name={name}, content_len={len(content)}")
            if name == "map_geocode":
                parsed = _parse_mcp_geocode_response(content)
                if parsed:
                    print(f"[DEBUG] geocode 解析成功: lng={parsed['lng']}, lat={parsed['lat']}")

    # 检查用户是否要求路线规划 + 检测出行方式
    user_asks_route = False
    travel_mode = "driving"  # 默认驾车
    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = msg.content or ""
            if any(kw in content for kw in ('路线', '规划路线', '怎么去', '导航')):
                user_asks_route = True
                # 根据关键词判断出行方式
                if any(kw in content for kw in ('步行', '走路', '走过去', '走路去')):
                    travel_mode = "walking"
                elif any(kw in content for kw in ('骑车', '骑行', '自行车', '电动车')):
                    travel_mode = "riding"
                elif any(kw in content for kw in ('公交', '地铁', '坐公交', '坐地铁', '乘车')):
                    travel_mode = "transit"
                # 否则默认 driving
                break

    # 第1优先级：从 map_directions 提取路线数据
    geocode_messages = []
    poi_messages = []

    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        name = getattr(msg, "name", "")

        if name in ("map_geocode", "geocode_address", "search_nearby_places", "map_search_places"):
            if name in ("map_geocode", "geocode_address"):
                geocode_messages.append(msg)
            else:
                poi_messages.append(msg)

        if name in ("map_directions", "get_route_plan"):
            content = msg.content or ""
            data = _unwrap_mcp_response(content)
            if data is None:
                continue
            try:
                result = data.get("result", data)
                routes = result.get("routes") or result.get("schemes", [])
                if routes:
                    route = routes[0]
                    polyline_points = []
                    if "steps" in route:
                        for step in route["steps"]:
                            if isinstance(step, list):
                                for sub_step in step:
                                    if isinstance(sub_step, dict):
                                        _extract_path_from_step(sub_step, polyline_points)
                            elif isinstance(step, dict):
                                _extract_path_from_step(step, polyline_points)

                    if not polyline_points:
                        continue

                    # 从 API 返回路线中提取起终点坐标，然后获取多模式路线
                    origin_coord = {"lng": polyline_points[0][0], "lat": polyline_points[0][1]}
                    dest_coord = {"lng": polyline_points[-1][0], "lat": polyline_points[-1][1]}

                    map_data = _build_multi_mode_route(origin_coord, dest_coord)
                    if map_data:
                        _print_final_map_data(map_data)
                        return map_data
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                pass

    # 第2优先级：从 map_search_places 或 search_nearby_places 提取 POI 列表
    _poi_map_data_for_route = None
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        name = getattr(msg, "name", "")
        if name not in ("map_search_places", "search_nearby_places"):
            continue

        content = msg.content or ""
        pois = _parse_mcp_poi_response(content)
        if not pois:
            continue

        poi_points = []
        lngs, lats = [], []
        for p in pois:
            lng, lat = p["lng"], p["lat"]
            if lng and lat:
                poi_points.append({
                    "lng": lng, "lat": lat, "name": p["name"],
                    "tag": p.get("tag") or "地图推荐",
                    "rating": p.get("rating", ""), "price": p.get("price", ""),
                    "address": p.get("address", ""),
                })
                lngs.append(lng)
                lats.append(lat)

        if not poi_points:
            continue

        center_lng = sum(lngs) / len(lngs)
        center_lat = sum(lats) / len(lats)

        map_data = {
            "type": "poi_list",
            "center": [center_lng, center_lat],
            "zoom": 14,
            "points": poi_points,
        }
        print(f"[DEBUG]   Got POI map_data ({len(poi_points)} results)!")
        # 保存 POI 数据供 fallback 路线使用，不要提前 return
        _poi_map_data_for_route = map_data

    # 没有任何地图数据
    if not _poi_map_data_for_route and not geocode_messages:
        if not user_asks_route:
            print("\n[DEBUG]   无地图数据可提取")
            return None
        print("\n[DEBUG]   用户要路线但无地图数据")
        return None

    # 用户没要路线 → 直接返回 POI 列表
    if not user_asks_route:
        return _poi_map_data_for_route

    # ---- 后端自动补路线 ----

    final_reply = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            final_reply = msg.content
            break

    # 情况A：有 ≥2 个 geocode → 起点→终点多模式路线
    if user_asks_route and len(geocode_messages) >= 2:
        geocode_messages.sort(key=lambda m: messages.index(m))
        first_geo = _parse_mcp_geocode_response(geocode_messages[0].content)
        last_geo = _parse_mcp_geocode_response(geocode_messages[-1].content)
        if first_geo and last_geo:
            map_data = _build_multi_mode_route(first_geo, last_geo)
            if map_data:
                print(f"[DEBUG]   Built multi-mode route from geocode pair!")
                _print_final_map_data(map_data)
                return map_data

    # 情况B：有 geocode + POI → 住址→最近店 多模式路线
    if user_asks_route and geocode_messages and _poi_map_data_for_route:
        origin_coord = _parse_mcp_geocode_response(geocode_messages[-1].content)
        if origin_coord:
            # 过滤到回复中提及的店，找最近的一个
            poi_data = _filter_poi_to_mentioned(_poi_map_data_for_route, final_reply)
            points = poi_data.get("points", [])
            if points:
                try:
                    import math as _math
                    def _dist(p):
                        return _math.hypot(p["lng"] - origin_coord["lng"], p["lat"] - origin_coord["lat"])
                    nearest = min(points, key=_dist)
                except (KeyError, TypeError):
                    nearest = points[0]

                dest_coord = {"lng": nearest.get("lng", 0), "lat": nearest.get("lat", 0)}
                dest_name = nearest.get("name", "终点")
                if dest_coord["lng"] and dest_coord["lat"]:
                    map_data = _build_multi_mode_route(origin_coord, dest_coord, dest_name=dest_name, origin_name="我的住址（起点）")
                    if map_data:
                        print(f"[DEBUG]   Built multi-mode route from geocode + POI!")
                        _print_final_map_data(map_data)
                        return map_data

    print("\n[DEBUG]   未能构建路线")
    return None


# ---- 百度 Directions API 直接调用（后端兜底）----

def _extract_path_from_step(step: dict, polyline_points: list):
    """从单个 step 中提取 path 坐标点，追加到 polyline_points 列表。
    兼容 driving/walking/riding 的平级 steps 和 transit 的嵌套 steps。
    """
    path_str = step.get("path", "")
    if not path_str:
        return
    for pt in path_str.split(";"):
        parts = pt.split(",")
        if len(parts) == 2:
            try:
                polyline_points.append([float(parts[0]), float(parts[1])])
            except (ValueError, TypeError):
                pass


def _fetch_baidu_directions(
    origin_lng: float, origin_lat: float,
    dest_lng: float, dest_lat: float,
    mode: str = "driving"
) -> Optional[Dict[str, Any]]:
    """后端直接调用百度 Directions API 获取真实路径点集。

    当 Agent 没有调用 map_directions 时，后端自动补调此 API
    确保前端拿到的 polyline_points 是真实道路路径，不是直线。
    """
    import os, urllib.request, urllib.parse
    import time

    ak = os.environ.get("BAIDU_MAPS_API_KEY", "")
    if not ak:
        logger.warning("[Directions] 未配置 BAIDU_MAPS_API_KEY，跳过")
        return None

    origin = f"{origin_lat},{origin_lng}"
    destination = f"{dest_lat},{dest_lng}"
    params = {
        "origin": origin,
        "destination": destination,
        "ak": ak,
        "coord_type": "bd09ll",
        "output": "json",
    }
    if mode == "walking":
        params["tactics"] = ""
    elif mode == "riding":
        pass
    elif mode == "transit":
        pass

    url = f"https://api.map.baidu.com/directionlite/v1/{mode}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"[Directions] API 调用失败: {e}")
        return None

    if data.get("status") != 0:
        logger.warning(f"[Directions] 返回错误: {data.get('message', '')}")
        return None

    result = data.get("result", {})
    # transit 返回 schemes，driving/walking/riding 返回 routes
    routes = result.get("routes") or result.get("schemes", [])
    if not routes:
        return None

    route = routes[0]
    steps = route.get("steps", [])
    polyline_points = []
    for step in steps:
        # transit 的 step 可能是嵌套 list（如 [[步行段], [公交段], [步行段]]）
        if isinstance(step, list):
            for sub_step in step:
                if isinstance(sub_step, dict):
                    _extract_path_from_step(sub_step, polyline_points)
        elif isinstance(step, dict):
            _extract_path_from_step(step, polyline_points)

    if not polyline_points:
        return None

    # 提取步骤说明文字
    step_texts = []
    for step in steps:
        if isinstance(step, list):
            for sub_step in step:
                if isinstance(sub_step, dict):
                    instr = sub_step.get("instruction") or sub_step.get("instructions", "")
                    if instr:
                        step_texts.append(str(instr).strip())
        elif isinstance(step, dict):
            instr = step.get("instruction") or step.get("instructions", "")
            if instr:
                step_texts.append(str(instr).strip())

    duration = route.get("duration", 0)
    distance = route.get("distance", 0)
    duration_str = f"{int(duration/60)}分钟" if duration >= 60 else f"{duration}秒"
    distance_str = f"{distance}米" if distance < 1000 else f"{distance/1000:.1f}公里"

    return {
        "polyline_points": polyline_points,
        "duration": duration_str,
        "distance": distance_str,
        "steps": step_texts[:8],  # 最多8条步骤
    }


def _build_multi_mode_route(
    origin_coord: Dict[str, float],
    dest_coord: Dict[str, float],
    dest_name: str = "终点",
    origin_name: str = "起点",
) -> Optional[Dict[str, Any]]:
    """一次构建驾车/公交/步行 3 种出行方式的路线，供前端切换展示。

    并行调用百度 Directions API 获取各 mode 的真实路径点集，
    某个 mode 失败（如步行超 5km）不影响其他 mode。
    """
    import concurrent.futures

    if not origin_coord or not dest_coord:
        return None

    origin_lng = origin_coord.get("lng", 0)
    origin_lat = origin_coord.get("lat", 0)
    dest_lng = dest_coord.get("lng", 0)
    dest_lat = dest_coord.get("lat", 0)

    if not origin_lng or not dest_lng:
        return None

    center_lng = (origin_lng + dest_lng) / 2
    center_lat = (origin_lat + dest_lat) / 2

    # 并行调用 3 种出行方式
    modes_to_try = [
        ("driving", "驾车"),
        ("transit", "公交"),
        ("walking", "步行"),
    ]

    def _fetch_one(mode_key: str) -> Optional[Dict[str, Any]]:
        """调用百度 API 获取单条路线，失败返回 None"""
        try:
            result = _fetch_baidu_directions(origin_lng, origin_lat, dest_lng, dest_lat, mode_key)
            if result and result.get("polyline_points"):
                return {
                    "mode": mode_key,
                    "duration": result.get("duration", ""),
                    "distance": result.get("distance", ""),
                    "polyline_points": result.get("polyline_points", []),
                    "steps": result.get("steps", []),
                }
        except Exception as e:
            logger.warning(f"[MultiMode] {mode_key} 路线获取失败: {e}")
        return None

    mode_routes = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_fetch_one, mk): mk for mk, _ in modes_to_try}
        for future in concurrent.futures.as_completed(futures):
            route_data = future.result()
            if route_data:
                mode_routes.append(route_data)

    if not mode_routes:
        logger.warning("[MultiMode] 所有出行方式均获取失败")
        return None

    # 按优先级排序：driving → transit → walking
    mode_order = {"driving": 0, "transit": 1, "walking": 2, "riding": 3}
    mode_routes.sort(key=lambda r: mode_order.get(r["mode"], 99))

    logger.info(f"[MultiMode] 成功获取 {len(mode_routes)} 种路线: {[r['mode'] for r in mode_routes]}")

    return {
        "type": "multi_mode_route",
        "center": [center_lng, center_lat],
        "zoom": 14,
        "points": [
            {"lng": origin_lng, "lat": origin_lat, "name": origin_name, "tag": "起点"},
            {"lng": dest_lng, "lat": dest_lat, "name": dest_name, "tag": "终点"},
        ],
        "mode_routes": mode_routes,
    }


def _build_two_point_route(
    origin_coord: Dict[str, float],
    dest_coord: Dict[str, float],
    travel_mode: str = "driving",
) -> Optional[Dict[str, Any]]:
    """纯导航场景：geocode 了起点和终点，构造路线图。
    适用场景：用户说"从A到B规划路线"，Agent geocode 了两个地址但没调 map_directions。
    后端自动调百度 Directions API 拿真实路径点，不再用直线。
    """
    if not origin_coord or not dest_coord:
        return None

    origin_lng = origin_coord.get("lng", 0)
    origin_lat = origin_coord.get("lat", 0)
    dest_lng = dest_coord.get("lng", 0)
    dest_lat = dest_coord.get("lat", 0)

    if not origin_lng or not dest_lng:
        return None

    import math as _math
    center_lng = (origin_lng + dest_lng) / 2
    center_lat = (origin_lat + dest_lat) / 2

    # 后端自动调百度 Directions API 拿真实路径
    directions = _fetch_baidu_directions(origin_lng, origin_lat, dest_lng, dest_lat, travel_mode)
    polyline_points = directions["polyline_points"] if directions else [[origin_lng, origin_lat], [dest_lng, dest_lat]]
    duration = directions["duration"] if directions else ""
    distance = directions["distance"] if directions else ""

    if not duration:
        straight_m = _math.hypot((dest_lng - origin_lng) * 111320, (dest_lat - origin_lat) * 110540)
        speed = {"driving": 600, "riding": 250, "walking": 80, "transit": 400}.get(travel_mode, 600)
        mins = max(1, int(straight_m / speed))
        duration = f"{mins}分钟"
        distance = f"{straight_m / 1000:.1f}公里" if straight_m >= 1000 else f"{int(straight_m)}米"

    mode_label = {"driving": "驾车", "riding": "骑行", "walking": "步行", "transit": "公交"}.get(travel_mode, "驾车")

    return {
        "type": "route",
        "center": [center_lng, center_lat],
        "zoom": 14,
        "points": [
            {"lng": origin_lng, "lat": origin_lat, "name": "起点", "tag": "起点"},
            {"lng": dest_lng, "lat": dest_lat, "name": "终点", "tag": "终点"},
        ],
        "route": {
            "mode": mode_label,
            "duration": duration,
            "distance": distance,
            "steps": ["从起点出发", "前往终点"],
        },
        "polyline_points": polyline_points,
    }


def _build_fallback_route(
    origin_coord: Dict[str, float],
    poi_map_data: dict,
    final_reply: str,
    travel_mode: str = "driving",
) -> Optional[Dict[str, Any]]:
    """当 Agent 没调 map_directions 但用户要求路线时，用 geocode + POI 构造路线。

    取 geocode 的坐标作为起点，POI 列表中第一个（最近/最匹配的）作为终点。
    后端自动调百度 Directions API 拿真实路径点，不再用直线。
    """
    if not origin_coord or not poi_map_data:
        return None

    # 过滤到回复中提及的店
    poi_map_data = _filter_poi_to_mentioned(poi_map_data, final_reply)
    points = poi_map_data.get("points", [])
    if not points:
        return None

    # 找最近的店（简单直线距离）
    try:
        import math as _math
        def _dist(p):
            return _math.hypot(p["lng"] - origin_coord["lng"], p["lat"] - origin_coord["lat"])
        nearest = min(points, key=_dist)
    except (KeyError, TypeError):
        nearest = points[0]

    origin_lng = origin_coord["lng"]
    origin_lat = origin_coord["lat"]
    dest_lng = nearest.get("lng", 0)
    dest_lat = nearest.get("lat", 0)
    dest_name = nearest.get("name", "终点")

    if not dest_lng or not dest_lat:
        return None

    center_lng = (origin_lng + dest_lng) / 2
    center_lat = (origin_lat + dest_lat) / 2

    # 后端自动调百度 Directions API 拿真实路径
    directions = _fetch_baidu_directions(origin_lng, origin_lat, dest_lng, dest_lat, travel_mode)
    polyline_points = directions["polyline_points"] if directions else [[origin_lng, origin_lat], [dest_lng, dest_lat]]
    duration = directions["duration"] if directions else ""
    distance = directions["distance"] if directions else ""

    if not duration:
        straight_m = _math.hypot((dest_lng - origin_lng) * 111320, (dest_lat - origin_lat) * 110540)
        speed = {"driving": 600, "riding": 250, "walking": 80, "transit": 400}.get(travel_mode, 600)
        mins = max(1, int(straight_m / speed))
        duration = f"{mins}分钟"
        distance = f"{straight_m / 1000:.1f}公里" if straight_m >= 1000 else f"{int(straight_m)}米"

    mode_label = {"driving": "驾车", "riding": "骑行", "walking": "步行", "transit": "公交"}.get(travel_mode, "驾车")

    return {
        "type": "route",
        "center": [center_lng, center_lat],
        "zoom": 14,
        "points": [
            {"lng": origin_lng, "lat": origin_lat, "name": "我的住址（起点）", "tag": "起点"},
            {"lng": dest_lng, "lat": dest_lat, "name": dest_name, "tag": "终点"},
        ],
        "route": {
            "mode": mode_label,
            "duration": duration,
            "distance": distance,
            "steps": ["从住址出发", f"前往{dest_name}"],
        },
        "polyline_points": polyline_points,
    }


# ---- 进度提示 ----

def _build_progress_note(history: list) -> str:
    """从历史消息判断当前阶段，生成注入到 system prompt 的进度提示"""
    if not history:
        return ""

    tool_msgs = [m for m in history if isinstance(m, ToolMessage)]
    ai_msgs = [m for m in history if isinstance(m, AIMessage)]

    has_geocode = any(
        getattr(m, "name", "") in ("map_geocode", "geocode_address")
        for m in tool_msgs
    )
    has_poi = any(
        getattr(m, "name", "") in ("map_search_places", "search_nearby_places")
        for m in tool_msgs
    )
    has_knowledge = any(
        getattr(m, "name", "") == "search_knowledge"
        for m in tool_msgs
    )
    has_directions = any(
        getattr(m, "name", "") in ("map_directions", "get_route_plan")
        for m in tool_msgs
    )

    if not tool_msgs:
        return ""

    note = "【🔍 当前进度 — 已有数据】\n"

    if has_knowledge:
        note += "✅ RAG 知识库已查询\n"
    if has_geocode:
        note += "✅ 地址已 geocode\n"
    if has_poi:
        note += "✅ POI 已获取\n"
    if has_directions:
        note += "✅ 路线已规划\n"

    note += "\n【下一步可选方向】"
    if not has_knowledge:
        note += "\n· 可调用 search_knowledge 补知识库"
    if has_geocode and not has_poi:
        note += "\n· 🚨 坐标已拿到，必须立即调 map_search_places 搜周边店铺！"
    if has_poi and not has_directions:
        note += "\n· 已有 POI，如用户问路线可调 map_directions"
    if not has_geocode:
        note += "\n· 用户给了地点但还没 geocode → 先 geocode"
    note += "\n· 数据齐全 → 应停止调工具、直接输出推荐"

    return note


# ---- 内部 ReAct 图 ----

def _build_reAct_graph(tools: list) -> StateGraph:
    """构建 TravelAgent ReAct 子图（内部使用，不对外暴露）。"""

    builder = StateGraph(TravelSubState)

    _call_count = {"total": 0}

    def llm_call(state: TravelSubState) -> dict:
        llm = _get_travel_llm()
        history = list(state["messages"])

        dynamic_prompt = assemble_travel_prompt(state)

        _call_count["total"] += 1
        if _call_count["total"] >= 8:
            dynamic_prompt += "\n\n【⚠️ 工具调用次数已达上限，请基于已有数据直接回复。】"

        llm_to_use = llm.bind_tools(tools)
        response = llm_to_use.invoke([SystemMessage(content=dynamic_prompt)] + history)

        # 首轮未调工具的强启逻辑
        if _call_count["total"] == 1 and (not hasattr(response, "tool_calls") or not response.tool_calls):
            logger.warning("首轮未调工具，注入强启指令重试...")
            retry_prompt = dynamic_prompt + (
                "\n\n【🔴 最后一次警告】你刚才没有调用任何工具就直接回复了！这是严重违规。\n"
                "你现在必须、立刻、马上调用 search_knowledge 或 map_search_places。\n"
                "在拿到数据之前，禁止说任何一个字。"
            )
            response = llm_to_use.invoke([SystemMessage(content=retry_prompt)] + history)

        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                args_str = str(tc.get("args", {}))
                if len(args_str) > 200:
                    args_str = args_str[:197] + "..."
                logger.debug("→ 调用 %s(%s)", tc.get("name", "?"), args_str)
        else:
            logger.debug("→ 直接回复（无工具调用）")

        dump_reasoning(response, "TRAVEL-AGENT")

        return {"messages": [response]}

    def should_continue(state: TravelSubState) -> str:
        last_msg = state["messages"][-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "tools"
        return "exit"

    builder.add_node("llm", llm_call)
    builder.add_node("tools", TracedToolNode(tools))
    builder.set_entry_point("llm")
    builder.add_conditional_edges("llm", should_continue, {"tools": "tools", "exit": END})
    builder.add_edge("tools", "llm")

    return builder.compile().with_config(recursion_limit=25)


# ---- 对外暴露的运行入口 ----


def run_travel_agent(
    query: str,
    financial_context: Optional[Dict[str, Any]] = None,
    data_status: str = "normal",
    allow_cross_agent: bool = True,
) -> str:
    """运行 Travel Agent 子图，返回最终的文本回复。

    参数：
    - query: 用户查询文本（旅行/美食/出行相关）
    - financial_context: 可选的用户财务快照（由主 Agent 传入）
    - data_status: 主 Agent 的数据可用状态
    - allow_cross_agent: 是否允许调用 cross_agent 工具（query_bill_budget）

    返回：Travel Agent 整理后的文本回复
    """
    global _last_travel_map_data

    tools = _build_travel_tools(allow_cross_agent)
    subgraph = _build_reAct_graph(tools)
    initial_state = {
        "messages": [HumanMessage(content=query)],
        "data_status": data_status,
        "financial_context": financial_context,
        "cross_agent_request": None,
    }

    try:
        result = subgraph.invoke(initial_state)
        messages = result.get("messages", [])

        # 提取地图可视化数据，并保存到全局变量供 server.py 读取
        map_data = _extract_map_data(messages)
        _last_travel_map_data = map_data

        # 获取最后一条 AI 回复
        final_reply = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                final_reply = msg.content
                break

        return final_reply or "抱歉，处理您的请求时没有生成回复。"

    except Exception as e:
        logger.error(f"Travel Agent 运行失败: {e}")
        raise
