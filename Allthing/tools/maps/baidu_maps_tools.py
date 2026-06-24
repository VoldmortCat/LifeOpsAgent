import os
import requests
from langchain_core.tools import tool

BAIDU_MAPS_AK = os.environ.get("BAIDU_MAPS_API_KEY", "")


@tool
def search_nearby_places(keyword: str, city: str = "中山", radius: int = 2000) -> str:
    """搜索附近的地点（POI检索）。参数：keyword搜索关键词, city城市(默认中山), radius半径米(默认2000)。
    返回结果包含 UID，后续可用 get_place_details(uid=...) 查询详情。"""
    if not BAIDU_MAPS_AK:
        return "❌ 未配置百度地图API Key"
    resp = requests.get("http://api.map.baidu.com/place/v2/search", params={
        "query": keyword, "region": city, "radius": radius,
        "output": "json", "ak": BAIDU_MAPS_AK, "scope": 2
    }, timeout=10).json()
    if resp.get("status") != 0 or not resp.get("results"):
        return f"在{city}半径{radius}米内未找到与'{keyword}'相关的地点"
    out = f"✅ 在{city}找到以下{keyword}相关地点：\n\n"
    for i, p in enumerate(resp["results"][:5], 1):
        uid = p.get("uid", "")
        tel = p.get("telephone", "") or "无"
        dist = f"距离{int(p['distance'])}米" if p.get("distance") else ""
        out += (f"{i}. 【{p.get('name', '未知')}】\n"
                f"   📍 {p.get('address', '地址未知')}  {dist}\n"
                f"   📞 {tel}  |  ⭐{p.get('detail_info', {}).get('overall_rating', '?')}分"
                f"  |  💰¥{p.get('detail_info', {}).get('avg_price', '?')}\n"
                f"   🆔 uid={uid}\n\n")
    return out.strip()


@tool
def get_place_details(uid: str) -> str:
    """获取POI详细信息（评分/价格/营业时间/评价等）。参数：uid POI唯一标识符。
    注意：uid 必须来自 search_nearby_places 返回结果中的 uid= 字段，不能自己编造。"""
    if not BAIDU_MAPS_AK:
        return "❌ 未配置百度地图API Key"
    if not uid or len(uid) < 10:
        return f"❌ UID 格式无效: '{uid}'。请使用 search_nearby_places 返回的真实 UID（通常24位字符）。"
    resp = requests.get("http://api.map.baidu.com/place/v2/detail", params={
        "uid": uid, "output": "json", "scope": 2,
        "ak": BAIDU_MAPS_AK, "extensions_all": 1
    }, timeout=10).json()
    if resp.get("status") != 0:
        return f"❌ 获取详情失败：{resp.get('message', '未知错误')}。请确认 UID 来自 search_nearby_places 的返回结果。"
    r = resp["result"]; di = r.get("detail_info", {})
    hours = di.get("shop_hours", [])
    if isinstance(hours, list): hours = "; ".join(hours) if hours else "营业时间未知"
    svcs = []
    if di.get("has_parking"): svcs.append("🅿️ 停车场")
    if di.get("has_wifi"): svcs.append("📶 WiFi")
    if di.get("has_reservation"): svcs.append("📞 可预订")
    out = f"✅ 【{r.get('name', '未知')}】详细信息：\n\n"
    out += f"📍 地址：{r.get('address', '未知')}\n📞 电话：{r.get('telephone', '未提供')}\n\n"
    out += f"⭐ 综合评分：{di.get('overall_rating', '暂无')}/5.0\n"
    if di.get("taste_rating"): out += f"🍽️ 口味：{di['taste_rating']}/5.0\n"
    if di.get("service_rating"): out += f"🛎️ 服务：{di['service_rating']}/5.0\n"
    out += f"💰 人均消费：¥{di.get('avg_price', '未知')}元\n💬 用户评价：{di.get('comment_number', 0)}条\n\n"
    out += f"🕐 营业时间：{hours}\n🏷️ 类型：{di.get('tag', '')}\n"
    if svcs: out += f"\n🎁 特色服务：{' | '.join(svcs)}\n"
    return out


@tool
def search_and_get_details(keyword: str, city: str = "中山") -> str:
    """搜索地点并自动获取完整信息（推荐优先使用此工具）。参数：keyword地点名称, city城市(默认中山)"""
    if not BAIDU_MAPS_AK:
        return "❌ 未配置百度地图API Key"
    sr = requests.get("http://api.map.baidu.com/place/v2/search", params={
        "query": keyword, "region": city, "output": "json",
        "ak": BAIDU_MAPS_AK, "scope": 2, "page_size": 3
    }, timeout=10).json()
    if sr.get("status") != 0 or not sr.get("results"):
        return f"❌ 在{city}未找到'{keyword}'相关地点"
    first = sr["results"][0]; uid = first.get("uid", ""); name = first.get("name", keyword)
    if not uid: return f"⚠️ 找到了'{name}'但缺少UID"
    dr = requests.get("http://api.map.baidu.com/place/v2/detail", params={
        "uid": uid, "output": "json", "scope": 2,
        "ak": BAIDU_MAPS_AK, "extensions_all": 1
    }, timeout=10).json()
    if dr.get("status") != 0:
        return f"⚠️ 找到了'{name}'但获取详情失败: {dr.get('message', '未知错误')}"
    r = dr["result"]; di = r.get("detail_info", {})
    hours = di.get("shop_hours", [])
    if isinstance(hours, list): hours = "; ".join(hours) if hours else "营业时间未知"
    svcs = []
    if di.get("has_parking"): svcs.append("停车场")
    if di.get("has_wifi"): svcs.append("WiFi")
    if di.get("has_reservation"): svcs.append("可预订")
    out = f"✅ 【{name}】完整信息：\n\n"
    out += f"📍 地址：{r.get('address', '未知')}\n📞 电话：{r.get('telephone', '未提供')}\n\n"
    out += f"⭐ 综合评分：{di.get('overall_rating', '暂无')}/5.0\n"
    if di.get("taste_rating"): out += f"🍽️ 口味：{di['taste_rating']}/5.0\n"
    if di.get("service_rating"): out += f"🛎️ 服务：{di['service_rating']}/5.0\n"
    out += f"💰 人均消费：¥{di.get('avg_price', '未知')}元\n💬 评价：{di.get('comment_number', 0)}条\n\n"
    out += f"🕐 营业时间：{hours}\n🏷️ 菜系/类型：{di.get('tag', '')}\n"
    if svcs: out += f"🎁 服务：{' | '.join(svcs)}\n"
    out += f"\n---\n💡 需要我帮你规划到该店的路线？查看附近同类餐厅？了解交通情况？"
    return out


@tool
def get_route_plan(origin: str, destination: str, mode: str = "driving") -> str:
    """规划两点之间路线。参数：origin起点, destination终点(均可为地址文本或"lat,lng"坐标), mode方式(driving/walking/transit/riding)。
    注意：walking模式仅适用于短距离(<5km)，跨城区请用driving或transit。"""
    if not BAIDU_MAPS_AK:
        return "❌ 未配置百度地图API Key"

    # 清洗坐标格式：去掉中文描述，统一为 lat,lng
    def _clean_coord(s: str) -> str:
        import re
        # "东经113.4151°，北纬22.5188°" → "22.5188,113.4151"
        m = re.search(r'经[度]?\s*[:：]?\s*([\d.]+).*?纬[度]?\s*[:：]?\s*([\d.]+)', s)
        if m:
            return f"{m.group(2)},{m.group(1)}"
        # "lng,lat" → "lat,lng" (百度API需要lat在前)
        m = re.match(r'^\s*([\d.]+)\s*,\s*([\d.]+)\s*$', s)
        if m:
            return f"{m.group(2)},{m.group(1)}"
        return s

    origin = _clean_coord(origin)
    destination = _clean_coord(destination)

    mn = {"driving": "驾车", "walking": "步行", "transit": "公交", "riding": "骑行"}
    resp = requests.get(f"http://api.map.baidu.com/direction/v2/{mode}", params={
        "origin": origin, "destination": destination,
        "ak": BAIDU_MAPS_AK, "output": "json"
    }, timeout=10).json()

    if resp.get("status") != 0:
        msg = resp.get('message', '未知错误')
        hint = ""
        if mode == "walking":
            hint = "（步行模式仅支持短距离，跨城区请改用 mode='driving' 或 mode='transit'）"
        return f"❌ 路线规划失败：{msg}{hint}"

    res = resp["result"]
    if mode == "transit":
        sc = res.get("schemes", [])
        if sc:
            d = sc[0]
            return (f"✅ {mn[mode]}路线：{origin} → {destination}\n"
                    f"⏱️ 用时：约{int(d.get('duration',0))//60}分钟\n"
                    f"📏 距离：{int(d.get('distance',0))/1000:.1f}公里")
    else:
        rt = res.get("routes", [])
        if rt:
            d = rt[0]
            return (f"✅ {mn[mode]}路线：{origin} → {destination}\n"
                    f"⏱️ 用时：约{int(d.get('duration',0))//60}分钟\n"
                    f"📏 距离：{int(d.get('distance',0))/1000:.1f}公里")
    return f"未找到可行的{mn.get(mode, mode)}路线"


@tool
def get_weather_by_location(location: str) -> str:
    """查询指定地点天气。参数：location地点名称"""
    if not BAIDU_MAPS_AK:
        return "❌ 未配置百度地图API Key"
    resp = requests.get("https://api.map.baidu.com/weather/v1/", params={
        "district_id": location, "ak": BAIDU_MAPS_AK, "output": "json"
    }, timeout=10).json()
    if resp.get("status") != 0:
        return f"❌ 天气查询失败：{resp.get('message', '未知错误')}"
    fc = resp.get("result", {}).get("forecasts", [])
    if fc:
        t = fc[0]
        return f"{location}天气：\n温度：{t.get('low_temp','N/A')}°C ~ {t.get('high_temp','N/A')}°C\n天气：{t.get('text_day', '未知')}"
    return f"未获取到{location}的天气数据"


@tool
def geocode_address(address: str) -> str:
    """地址转经纬度坐标。参数：address地址文本"""
    if not BAIDU_MAPS_AK:
        return "❌ 未配置百度地图API Key"
    resp = requests.get("http://api.map.baidu.com/geocoding/v3/", params={
        "address": address, "output": "json", "ak": BAIDU_MAPS_AK
    }, timeout=10).json()
    if resp.get("status") != 0:
        return f"❌ 地理编码失败：{resp.get('message', '未知错误')}"
    r = resp["result"]; loc = r.get("location", {})
    return f"地理编码结果：\n原始地址：{address}\n标准化：{r.get('formatted_address', address)}\n经度：{loc.get('lng', '未知')}\n纬度：{loc.get('lat', '未知')}"
