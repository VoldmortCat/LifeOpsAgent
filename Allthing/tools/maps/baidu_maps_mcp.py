"""百度地图 MCP 客户端 — 通过 langchain-mcp-adapters 连接 mcp-server-baidu-maps。

使用方式：
    from tools.maps.baidu_maps_mcp import get_baidu_mcp_tools
    mcp_tools = get_baidu_mcp_tools()

返回的是标准 LangChain BaseTool 列表，已做 sync 适配（MCP 原是纯异步），
可以直接 bind_tools 给 LLM、投入 LangGraph ToolNode 同步调用。

原理：
    Agent 进程（主）── JSON-RPC over stdio ──→ mcp-server-baidu-maps 子进程
                                              └─→ 百度地图 HTTP API

核心工具及参数：
    map_weather      — district_id(6位区划码如442000) 或 location(lng,lat)
    map_search_places — query* 关键词, region 城市, radius 半径(米), tag 分类
    map_place_details — uid* 来自map_search_places结果
    map_directions    — origin* 起点, destination* 终点, model(driving/transit/walking/riding)
    map_geocode       — address* 地址文本
    map_reverse_geocode — latitude*, longitude*
"""
import asyncio
import os
import logging
import json
import warnings
import math
from typing import List

from langchain_core.tools import StructuredTool

logger = logging.getLogger("lifeops.mcp")


_mcp_tools: List = []
_initialized: bool = False

# 中国主要城市的近似坐标（lng, lat），用于校验 LLM 传入的 location 是否合理
_CITY_COORDS = {
    "深圳": (113.87, 22.55), "中山": (113.38, 22.52), "广州": (113.26, 23.13),
    "梅州": (116.12, 24.29), "珠海": (113.58, 22.27), "东莞": (113.75, 23.02),
    "佛山": (113.12, 23.03), "惠州": (114.42, 23.11), "北京": (116.41, 39.90),
    "上海": (121.47, 31.23),
}


def _get_default_city() -> str:
    try:
        from config.config_loader import config as cfg
        return cfg.get("maps.default_city", "中山")
    except Exception:
        return "中山"


def _coord_distance_km(lng1, lat1, lng2, lat2) -> float:
    """计算两个经纬度之间的大致距离（km）"""
    return math.hypot((lng1 - lng2) * 111.32 * math.cos(math.radians((lat1 + lat2) / 2)),
                      (lat1 - lat2) * 110.54)


def _validate_location_coords(kwargs: dict) -> dict:
    """校验 map_search_places 的 location 参数，并确保 region 存在。

    核心原则：用户的真实位置（来自 geocode）不可被默认城市覆盖。
    - location 来自 geocode → 坐标本身就是准确的 → 直接通过，不做城市距离校验
    - 调用方显式传了 region/city → 校验 location 是否在该城市范围内（>200km 丢弃）
    - 既没 location 也没 region → 注入默认城市作为兜底
    """
    default_city = _get_default_city()

    # LLM 可能传 city=XX 而非 region=XX，映射之
    if "city" in kwargs and "region" not in kwargs:
        kwargs["region"] = kwargs.pop("city")

    # 调用方是否显式指定了 region
    has_explicit_region = "region" in kwargs

    location = kwargs.get("location", "")

    # 情况1：既没 location 也没 region → 注入默认城市兜底
    if not location and not has_explicit_region:
        kwargs["region"] = default_city
        return kwargs

    # 情况2：没 location 但有 region → 直接用 region 搜，不改动
    if not location:
        return kwargs

    # 情况3：有 location → 解析坐标
    parts = str(location).split(",")
    if len(parts) != 2:
        # 解析失败，保留 region 或注入默认
        if not has_explicit_region:
            kwargs["region"] = default_city
        return kwargs
    try:
        coord_a, coord_b = float(parts[0]), float(parts[1])
    except ValueError:
        if not has_explicit_region:
            kwargs["region"] = default_city
        return kwargs

    # 尝试两种排列：coord_a 是 lng 还是 lat？
    # lng 范围 73~135，lat 范围 3~54
    lng, lat = None, None
    if (73 <= coord_a <= 135) and (3 <= coord_b <= 54):
        lng, lat = coord_a, coord_b
    elif (73 <= coord_b <= 135) and (3 <= coord_a <= 54):
        lng, lat = coord_b, coord_a
    else:
        logger.warning(f"[MCP] location 坐标无法识别(lng/lat): {location}，丢弃 location")
        kwargs.pop("location", None)
        if not has_explicit_region:
            kwargs["region"] = default_city
        return kwargs

    # ===== 关键分叉 =====
    if has_explicit_region:
        # 有显式 region → 校验 location 是否在该城市范围内
        region_city = kwargs["region"]
        city_coord = _CITY_COORDS.get(region_city)
        if city_coord:
            dist = _coord_distance_km(lng, lat, city_coord[0], city_coord[1])
            if dist > 200:
                logger.warning(
                    f"[MCP] location ({lng},{lat}) 偏离目标城市 {region_city}({city_coord[0]},{city_coord[1]}) "
                    f"约 {dist:.0f}km，丢弃 location 改用 region={region_city}"
                )
                kwargs.pop("location", None)
            else:
                kwargs["location"] = f"{lat},{lng}"
        else:
            # region 城市不在映射表（如梅州/福州）→ 直接通过
            kwargs["location"] = f"{lat},{lng}"
    else:
        # 无显式 region → location 来自 geocode，坐标本身就是准确的，直接通过
        # 不要用默认城市做距离比对！会误杀其他城市的有效坐标
        kwargs["location"] = f"{lat},{lng}"

    return kwargs


# MCP Server 是单线程 stdio 子进程，不支持并发调用，所有调用必须加锁串行化
import threading
_mcp_call_lock = threading.Lock()


def _make_sync_tool(async_tool) -> StructuredTool:
    """将 async-only 的 MCP StructuredTool 转为 sync-compatible。

    MCP 工具只有 coroutine（纯异步），LangGraph ToolNode 同步调用会报
    NotImplementedError: StructuredTool does not support sync invocation。
    这里包一层 sync func，内部用 asyncio.run() 驱动协程。
    同时对 map_search_places 做坐标校验，防止 LLM 幻觉传入错误坐标。
    """
    coro = async_tool.coroutine
    args_schema = async_tool.args_schema
    tool_name = async_tool.name

    def sync_func(**kwargs):
        # 对 map_search_places 做 location 坐标校验
        if tool_name == "map_search_places":
            kwargs = _validate_location_coords(kwargs)
        # MCP Server 是单线程 stdio 子进程，不支持并发调用，必须加锁串行化
        # LangGraph ToolNode 用线程池并发分发，两个调用几乎同时进入，加重试+延迟
        with _mcp_call_lock:
            last_err = None
            for attempt in range(3):
                try:
                    return asyncio.run(coro(**kwargs))
                except Exception as e:
                    last_err = e
                    if attempt < 2:
                        delay = 1.0 * (attempt + 1)
                        logger.warning(f"[MCP] {tool_name} 第{attempt+1}次调用失败，{delay}秒后重试: {e}")
                        import time; time.sleep(delay)
                    else:
                        logger.error(f"[MCP] {tool_name} 第3次调用仍失败: {e}")
            return json.dumps({"error": str(last_err), "status": -1, "message": f"服务异常(3次重试后仍失败): {last_err}"})

    return StructuredTool(
        name=async_tool.name,
        description=async_tool.description,
        func=sync_func,
        args_schema=args_schema,
    )


def _init_mcp_tools():
    global _mcp_tools, _initialized
    if _initialized:
        return

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        async def _load():
            client = MultiServerMCPClient({
                "baidu-maps": {
                    "command": "python",
                    "args": ["-m", "mcp_server_baidu_maps"],
                    "transport": "stdio",
                    "env": {"BAIDU_MAPS_API_KEY": os.environ.get("BAIDU_MAPS_API_KEY", "")},
                }
            })
            return await client.get_tools()

        raw_tools = asyncio.run(_load())
        _mcp_tools = [_make_sync_tool(t) for t in raw_tools]
        _initialized = True
        logger.info("百度地图 MCP Server 已连接，加载 %d 个工具（已 sync 适配）", len(_mcp_tools))

    except FileNotFoundError:
        warnings.warn(
            "mcp-server-baidu-maps 未找到，请执行: pip install mcp-server-baidu-maps\n"
            "回退到旧版 @tool 百度地图工具"
        )
        _mcp_tools = []
        _initialized = True
    except Exception as e:
        warnings.warn(f"MCP 客户端初始化失败: {e}\n回退到旧版 @tool 百度地图工具")
        _mcp_tools = []
        _initialized = True


def get_baidu_mcp_tools() -> List:
    """获取百度地图 MCP 工具（LangChain BaseTool 列表，已 sync 适配）。

    首次调用时自动初始化，连接 mcp-server-baidu-maps 子进程。
    初始化失败时返回空列表，调用方应 fallback 到旧版 @tool 工具。
    """
    _init_mcp_tools()
    return _mcp_tools
