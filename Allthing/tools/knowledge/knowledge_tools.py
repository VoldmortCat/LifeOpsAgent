"""
知识库检索工具 — 基于本地 Markdown 文件的 RAG（v3 · Milvus 后端）

检索架构：
  主路径   Milvus 2.5 服务端混合检索：稠密向量 + 内置中文 BM25 全文检索，
           WeightedRanker 融合；city(partition key)/价格/场景标签 expr 服务端下推。
           —— 替代旧版手写 numpy 余弦 + jieba + rank_bm25 流程
  降级路径 Milvus 不可用时：加载本地 JSON 快照(data/knowledge_snapshot.json)，
           回退旧版应用层管线（关键词加权检索），保证 RAG 不至于完全瘫痪
  语义路由 标签向量缓存 + 查询激活（两版共用，见 _route_semantic_tags）

知识库文件格式：Markdown 自然段落，以 ## 标题分隔数据块。
原始 .md 文件不做结构化清洗。标签导入时按词库自动提取；
价格区间导入时正则抽取为结构化字段（price_min/max/level）。
"""
import sys
import os
import re
import json
import socket
import logging
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from langchain_core.tools import tool
from dashscope import TextEmbedding

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config.config_loader import config
try:
    from tools.knowledge import milvus_store as store
except Exception:  # 循环依赖防护等极端情况
    store = None

logger = logging.getLogger("lifeops.knowledge")

KNOWLEDGE_DIR = Path(config.get("paths.knowledge_base_dir", "knowledge_base"))
VECTORDB_DIR = Path(config.get("paths.vectordb_dir", "data/vectordb"))

# ===== Embedding 配置 =====
EMBEDDING_MODEL = "text-embedding-v2"
EMBEDDING_DIM = 1536
EMBEDDING_BATCH_SIZE = 25

# ===== 语义匹配阈值 =====
CONFIDENCE_THRESHOLD = 0.3

# ===== 向量索引缓存 =====
_entries_cache: Optional[List[Dict]] = None
_embeddings_cache: Optional[np.ndarray] = None
_index_mtime: float = 0

# ===== Milvus 后端配置 =====
_MILVUS_URI = config.get("vectordb.uri", "http://127.0.0.1:19530")
_MILVUS_ENABLED = bool(store and store.is_available())

# Milvus 熔断。
# is_available() 只校验配置与客户端能否构造，不代表真能连上服务端 ——
# 实测 milvus-lite 未安装时它返回 True，但每次查询都要先卡一次连接超时
# （单题最坏 300 秒）才降级，代价极高。连续失败达阈值后直接走降级管线。
_MILVUS_FAIL_COUNT = 0
_MILVUS_FAIL_THRESHOLD = 3
_MILVUS_CIRCUIT_OPEN = False


def _milvus_reachable(uri: str, timeout: float = 1.5) -> bool:
    """
    快速 TCP 探活：不依赖 pymilvus 握手，避免每次查询都卡在 Milvus 连接超时。

    为什么需要它：pymilvus 的 MilvusClient(uri=...) 在远端不可达时会阻塞到
    内部超时（实测单题最坏 300s），而 is_available() 只检查 SDK 能否 import、
    不验证网络可达性。本函数用裸 socket 在 1.5s 内判定端口是否可连，连不上
    直接开熔断走降级路径，整次评测/查询不再为每个 query 付一次超时代价。
    """
    try:
        from urllib.parse import urlparse
        raw = uri if "://" in uri else "http://" + uri
        p = urlparse(raw)
        host = p.hostname or "127.0.0.1"
        port = p.port or 19530
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

# ===== 本地快照（Milvus 断连时的降级数据源） =====
_SNAPSHOT_PATH = Path(config.get("paths.data_dir", "data")) / "knowledge_snapshot.json"
_BUILD_INFO_PATH = Path(config.get("paths.vectordb_dir", "data/vectordb")) / "build_info.json"

# ===== 标签词库 =====
# 导入时从段落全文自动匹配这些词作为标签，不改原始文件。
# 格式：标签名 → 匹配模式列表（任一命中即打标）
#
# 词库维护规则（v2 — 修复标签污染）：
#   1. 禁止单字模式："山"曾把"孙中山"打成自然风光、"虾"曾把"虾饺"(早茶)打成
#      海鲜、"买"命中一切购物语境。单字一律展开为 ≥2 字的具体词。
#   2. 禁止泛动词/泛名词："建议""提醒""预约""预算"曾让「攻略」标签几乎全库命中，
#      失去区分度。只保留内容类型词（攻略/避坑/路线…）。
#   3. 歧义搭配用短语级模式："凌晨"会误标日出观景段落，改用"开到凌晨"等短语。
#   4. 区镇类是闭集专有名词，可参与硬过滤；其余类型标签仅作软加分信号，
#      个性化场景意图由语义标签路由（_route_semantic_tags）负责。
_TAG_DICT: Dict[str, List[str]] = {
    # ----- 地区和方位（闭集专有名词，可做硬过滤）-----
    "石岐区": ["石岐区", "石岐街道", "石岐老城", "孙文西路", "白水井", "兴中广场", "凤鸣路", "烟墩山", "康华路", "张溪", "莲员东路"],
    "东区": ["东区街道", "长江水世界", "新安村", "库充村", "景观路", "中山三路", "利和广场", "紫马岭"],
    "南区": ["南区街道", "詹园", "北台村", "树木园", "银潭二路"],
    "西区": ["西区街道", "岐江西岸", "岐江公园"],
    "沙溪镇": ["沙溪", "隆都", "星宝", "岐江公路乐群", "翠景南路"],
    "三乡镇": ["三乡镇", "三乡", "雍陌村", "古鹤村", "泉林", "白石村", "罗三妹", "南龙村", "东街里"],
    "坦洲镇": ["坦洲", "大冲口", "坦神北路", "界狮南路", "同明街"],
    "小榄镇": ["小榄", "孖宝庄园", "樱花里"],
    "古镇镇": ["古镇镇", "灯都", "灯饰"],
    "南朗街道": ["南朗", "崖口村", "翠亨", "孙中山故居", "孙中山故里", "影视城"],
    "五桂山街道": ["五桂山", "逍遥谷", "旗溪村", "桂南村", "南桥"],
    "翠亨新区": ["马鞍岛", "翠亨新区", "深中大桥", "湿地公园", "滨海步道"],
    "港口镇": ["港口镇", "港福路"],
    "黄圃镇": ["黄圃", "腊味", "新丰北"],
    "东升镇": ["东升镇", "脆肉鲩"],
    "火炬开发区": ["火炬开发区", "火炬路"],
    "神湾镇": ["神湾", "菠萝"],
    # ----- 美食类型 -----
    "乳鸽": ["乳鸽", "鸽子", "妙龄鸽", "盐焗鸽", "药膳鸽", "鸽血", "鸽皇", "鸽肉", "香茅焗鸽"],
    "早茶": ["早茶", "茶楼", "点心", "虾饺", "金钱肚", "牛仔骨", "凤爪", "烧卖", "茶位", "饮茶", "鸭脚扎"],
    "海鲜": ["海鲜", "生蚝", "扇贝", "海螺", "贝壳", "鱿鱼", "龙虾", "大闸蟹", "肉蟹", "膏蟹", "醉蟹",
             "避风塘", "渔村", "渔获", "九节虾", "基围虾", "白灼虾", "海胆", "水产", "河鲜", "海鸭",
             "鱼生", "鱼片", "蒸鱼", "焖鱼", "鱼头", "鱼嘴", "鱼腩", "脆肉鲩", "笋壳鱼", "桂花鱼",
             "三文鱼", "烤生蚝", "水鱼"],
    "火锅": ["火锅", "椰子鸡", "砂锅粥", "打边炉", "鸡煲"],
    "烧烤": ["烧烤", "烤肉", "烧鸡", "炭烤", "烤五花", "烤鱼", "烤串", "羊肉串", "炭火慢烤", "篝火"],
    "宵夜": ["宵夜", "夜宵", "深夜", "通宵", "开到凌晨", "营业到凌晨", "烧鸡铺", "烤吧"],
    "小吃": ["小吃", "濑粉", "肠粉", "云吞", "煲仔饭", "煎堆", "米酒", "芦兜粽", "炸鱼球", "炸云吞",
             "烧饼", "鸡仔饼", "满足面", "云吞面"],
    "咖啡": ["咖啡", "手冲", "美式", "冷萃", "拿铁", "咖啡店", "咖啡馆", "咖啡厅", "精酿啤酒"],
    "异国风味": ["印度", "土耳其", "意大利", "东南亚", "南洋", "披萨", "烤肉拼盘", "日料", "西餐",
                 "寿司", "意面", "泰国菜", "越南菜", "韩国料理", "异国风情美食街"],
    # ----- 旅行类型 -----
    "历史文化": ["博物馆", "故居", "历史", "非遗", "明代", "清代", "清末", "民国", "古建筑", "华侨",
                 "文塔", "文化馆", "纪念公园", "遗址", "百年老"],
    # 注：不放裸"公园"——"纪念公园/主题公园"会误标历史类段落；
    # 真自然场景在语料中均有更强信号（湿地/森林/绿道/水库/日落…）
    "自然风光": ["湿地", "森林", "水库", "稻田", "绿道", "树木园", "溪流", "竹海", "爬山",
                 "登山", "郊野", "田园", "观景台", "日出", "日落", "红树林", "候鸟", "徒步", "溯溪",
                 "天然氧吧", "绿肺"],
    "网红打卡": ["打卡", "网红", "小红书", "拍照", "出片", "摩天轮", "稻田咖啡", "电厂工坊", "碉楼",
                 "霸屏"],
    "温泉": ["温泉", "泡池", "泡汤"],
    "住宿": ["酒店", "民宿", "宾馆", "度假", "住宿", "入住", "一晚", "客栈", "别墅", "木屋"],
    "交通出行": ["城轨", "自驾", "公交", "深中通道", "跨市公交", "高速", "网约车", "打车", "骑行",
                 "停车", "共享单车", "BRT", "码头"],
    "购物": ["购物", "商圈", "商场", "手信", "特产", "腊味", "杏仁饼", "百货", "伴手礼", "逛街",
             "购物中心", "卖场", "采购", "广场"],
    "夜市": ["夜市", "夜经济", "酒吧街", "美食街", "不夜城", "宵夜街"],
    # ----- 主题 -----
    "攻略": ["攻略", "避坑", "贴士", "最佳时间", "行程", "路线", "注意事项", "怎么玩", "优先级",
             "防坑", "预算参考"],
    "亲子": ["亲子", "儿童", "水上乐园", "游乐园", "滑草", "遛娃", "小孩", "家庭出游", "机动游戏"],
    "情侣": ["情侣", "约会", "求婚", "浪漫", "蜜月"],
}

# ===== 标签语义描述（v3：供语义标签路由向量化用） =====
# 模式词只覆盖字面命中；语义激活需要"场景化白话描述"，才能接住
# "带爸妈去玩"->亲子 这类零词汇重叠的意图。区镇是闭集枚举走词面即可，不参与。
_TAG_DESCRIPTIONS: Dict[str, str] = {
    "乳鸽": "中山招牌红烧乳鸽妙龄鸽，想吃鸽子禽类菜的场合",
    "早茶": "广式早茶点心茶楼饮茶虾饺凤爪，一盅两件的早餐",
    "海鲜": "海鲜水产鱼虾蟹贝生蚝扇贝，吃海味河鲜的场合",
    "火锅": "打边炉涮锅椰子鸡砂锅粥鸡煲，围炉热乎菜",
    "烧烤": "炭火烤串烤肉，晚上撸串吃烤物的场合",
    "宵夜": "深夜营业的大排档夜宵，晚上十点后出门吃东西",
    "小吃": "本地特色粉面云吞肠粉煲仔饭，街边平价地道小食",
    "咖啡": "咖啡馆手冲拿铁精品咖啡，坐下来喝一杯歇脚",
    "异国风味": "外国餐厅东南亚菜日料韩料西餐披萨，换换口味的异国料理",
    "历史文化": "名人故居博物馆非遗古建筑遗址，有人文故事可看的地方",
    "自然风光": "山水田园湿地绿道森林徒步，看风景亲近大自然的户外景点",
    "网红打卡": "出片好看适合拍照分享社交平台的热门地点",
    "温泉": "温泉度假村泡汤泡池，想泡温泉放松身心",
    "住宿": "酒店民宿宾馆客栈，外地或过夜要订住的地方",
    "交通出行": "怎么前往的交通方式城轨公交自驾停车，路上怎么走",
    "购物": "逛街买特产手信商场超市伴手礼，购物消费的场所",
    "夜市": "夜市美食街酒吧街，晚上热闹的夜生活街区",
    "攻略": "实用建议避坑提醒行程规划最佳时间注意事项，出行前要看的经验",
    "亲子": "适合带小孩孩子爸爸妈妈父母长辈全家老少一起玩的亲子乐园与户外活动",
    "情侣": "适合情侣两个人约会浪漫求婚纪念日的浪漫去处",
}

# ===== 城市 → 区镇标签映射（用于判断检索结果是否匹配用户所在城市）=====
CITY_DISTRICTS = {
    "中山": [
        "石岐区", "东区", "南区", "西区", "沙溪镇", "三乡镇", "坦洲镇",
        "小榄镇", "古镇镇", "南朗街道", "五桂山街道", "翠亨新区",
        "港口镇", "黄圃镇", "东升镇", "火炬开发区", "神湾镇",
    ],
    # 后续添加其他城市时在这里补充
}


# ============================================================
# 本地快照 & 构建信息（Milvus 降级方案）
# ============================================================

def _save_snapshot(entries: List[Dict], embeddings) -> None:
    """把全量条目+向量写 JSON 快照，供 Milvus 断连时降级检索用。"""
    try:
        _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SNAPSHOT_PATH.write_text(json.dumps({
            "count": len(entries),
            "entries": entries,
            "embeddings": [[float(x) for x in row] for row in embeddings],
        }, ensure_ascii=False), encoding="utf-8")
        logger.info("快照已保存: %s (%d 条)", _SNAPSHOT_PATH.name, len(entries))
    except Exception as e:
        logger.warning("快照写入失败(不影响主流程): %s", e)


def _load_snapshot() -> Tuple[Optional[List[Dict]], Optional["np.ndarray"]]:
    """读取降级快照。不存在返回 (None, None)。"""
    try:
        data = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        import numpy as np
        return data["entries"], np.array(data["embeddings"], dtype=np.float32)
    except Exception:
        return None, None


def _read_build_info() -> Dict:
    try:
        return json.loads(_BUILD_INFO_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_build_info(mtime: float) -> None:
    try:
        _BUILD_INFO_PATH.parent.mkdir(parents=True, exist_ok=True)
        _BUILD_INFO_PATH.write_text(json.dumps({"build_mtime": mtime}), encoding="utf-8")
    except Exception as e:
        logger.warning("构建信息写入失败: %s", e)


def _read_frontmatter(filepath: str) -> Dict[str, str]:
    """
    读取 md 文件头的 YAML frontmatter（--- 包裹的元数据块）。
    返回 frontmatter 字段字典；无 frontmatter 时返回空字典。

    格式示例：
        ---
        city: 中山
        category: 美食
        ---
        # 正文标题
    """
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
    except Exception:
        return {}

    if not content.startswith("---"):
        return {}

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}

    meta: Dict[str, str] = {}
    for line in parts[1].strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()

    return meta


# 标签匹配模式的最短长度防线：单字子串匹配是标签污染的主要来源
# （"山"命中"孙中山"、"虾"命中"虾饺"、"鱼"命中一切），低于此长度的模式直接跳过
MIN_TAG_PATTERN_LEN = 2


def _extract_tags(title: str, content: str) -> List[str]:
    """
    从段落全文（标题 + 正文）中按预定义词库匹配标签。
    不改原始文件，仅在导入时自动提取。
    返回去重的标签列表。

    防线：< MIN_TAG_PATTERN_LEN 的模式会被跳过并记警告，
    保证词库维护失误（混入单字模式）不会重新引入标签污染。
    """
    full_lower = (title + " " + content).lower()
    matched_tags: Set[str] = set()

    for tag_name, patterns in _TAG_DICT.items():
        for pattern in patterns:
            if len(pattern) < MIN_TAG_PATTERN_LEN:
                logger.warning("标签[%s]的模式'%s'长度<%d，已跳过（防污染）",
                               tag_name, pattern, MIN_TAG_PATTERN_LEN)
                continue
            if pattern.lower() in full_lower:
                matched_tags.add(tag_name)
                break  # 一个标签只加一次

    return sorted(matched_tags)


# ============================================================
# 价格结构化抽取（v2 新增）
# ============================================================
# 从段落文本中抽取人均消费区间，作为可过滤的结构化字段。
# 只认"人均"语境——单菜价格（"乳鸽80元一只"）不代表消费档位，不参与。
# 抽不到时 price_min/price_max 为 None，检索时按"未知"处理，不会被价格过滤误杀。

_RE_PRICE_RANGE = re.compile(r"人均[^0-9]{0,4}(\d{1,4})\s*(?:到|至|-|~|—)\s*(\d{1,4})")
_RE_PRICE_SINGLE = re.compile(r"人均[^0-9]{0,4}(\d{1,4})")
# scene_guide 风格："人均预算：15-35元" / "人均<30元"
_RE_PRICE_BUDGET = re.compile(r"人均预算[:：]\s*(\d{1,4})\s*(?:[-~到至—]\s*(\d{1,4}))?")
_RE_PRICE_LT = re.compile(r"人均[<＜]\s*(\d{1,4})")

# 人均档位：0=未知 1=省钱(≤35) 2=日常(35<x≤90) 3=高端(>90)
PRICE_LEVEL_UNKNOWN = 0
PRICE_LEVEL_BUDGET_MAX = 35
PRICE_LEVEL_MID_MAX = 90


def _price_level(price_min: Optional[int], price_max: Optional[int]) -> int:
    """根据人均区间推导消费档位。"""
    if price_min is None and price_max is None:
        return PRICE_LEVEL_UNKNOWN
    lo = price_min if price_min is not None else price_max
    hi = price_max if price_max is not None else price_min
    avg = (lo + hi) / 2
    if avg <= PRICE_LEVEL_BUDGET_MAX:
        return 1
    if avg <= PRICE_LEVEL_MID_MAX:
        return 2
    return 3


def _extract_price(text: str) -> Tuple[Optional[int], Optional[int]]:
    """
    从段落文本抽取人均消费区间 (price_min, price_max)。

    支持写法：
      人均80到120 / 人均50多 / 人均75左右 / 人均30-50块
      人均预算：15-35元 / 人均<30元
    多处命中时取并集（min 取最小、max 取最大），适配一段介绍多家店的块。
    """
    mins: List[int] = []
    maxs: List[int] = []

    for m in _RE_PRICE_RANGE.finditer(text):
        mins.append(int(m.group(1)))
        maxs.append(int(m.group(2)))

    for regex in (_RE_PRICE_BUDGET, _RE_PRICE_SINGLE):
        for m in regex.finditer(text):
            v = int(m.group(1))
            if m.lastindex and m.lastindex >= 2 and m.group(2):
                mins.append(v)
                maxs.append(int(m.group(2)))
            else:
                # 单点值：视为 min=max（如"人均50多"、"人均75左右"）
                mins.append(v)
                maxs.append(v)

    for m in _RE_PRICE_LT.finditer(text):
        # "人均<30"是上限语义：min 视为 0
        mins.append(0)
        maxs.append(int(m.group(1)))

    if not mins:
        return None, None
    return min(mins), max(maxs)


def _parse_blocks(filepath: str, category: str, rel_path: str) -> List[Dict]:
    """
    解析一个 .md 文件为自然段落块。
    按 ## 标题切分；每个 ## 下的整段文字作为一个检索单元。
    原文不做任何清洗——保留冗余和自由格式。
    标签在解析时自动提取，存储在 entry.tags 中。
    """
    blocks = []
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
    except Exception:
        return blocks

    # 读取 frontmatter（文件级元数据：city/category 等）
    file_meta = _read_frontmatter(filepath)
    file_city = file_meta.get("city", "未知")
    file_category = file_meta.get("category", category)

    # 剥离 frontmatter 块，避免它被当作正文 chunk
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            content = parts[2].lstrip("\n")

    raw_chunks = re.split(r"\n(?=##\s)", content)

    for chunk in raw_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        # 跳过纯注释和元信息行（# 开头但不是 ## 开头的）
        if chunk.startswith("# ") and not chunk.startswith("## "):
            continue

        lines = chunk.split("\n")
        title_line = lines[0].strip()
        title = re.sub(r"^#+\s*", "", title_line).strip()
        # 去掉标题中括号注释
        title = re.sub(r"\s*\([^)]*\)", "", title).strip()

        body_lines = [l for l in lines[1:] if l.strip()]
        body = "\n".join(body_lines) if body_lines else title

        full_text = f"{title}\n{body}"

        # 清洗掉来源标记行
        clean_body = []
        for bl in body_lines:
            low = bl.strip().lower()
            if re.match(r"^(source|references?|data\s*source|抓取|来源|参考)[:：]", low):
                continue
            clean_body.append(bl)
        content_text = "\n".join(clean_body) if clean_body else body

        # 自动提取标签
        tags = _extract_tags(title, content_text)

        # 抽取人均消费区间（结构化字段，支持按预算过滤）
        price_min, price_max = _extract_price(full_text)

        blocks.append({
            "title": title,
            "content": content_text,
            "tags": tags,
            "category": file_category,
            "city": file_city,
            "source_file": rel_path,
            "full_text": full_text,
            "price_min": price_min,
            "price_max": price_max,
            "price_level": _price_level(price_min, price_max),
        })

    return blocks


def _parse_all_blocks() -> Tuple[List[Dict], List[str]]:
    """扫描 knowledge_base/ 全部 .md 并分块解析。返回 (entries, 待向量化文本)。"""
    entries, texts = [], []
    for root, _, files in os.walk(KNOWLEDGE_DIR):
        for f in sorted(files):
            if not f.endswith(".md") or f.startswith("."):
                continue
            filepath = os.path.join(root, f)
            rel_path = os.path.relpath(filepath, KNOWLEDGE_DIR)
            category = os.path.basename(root)
            for block in _parse_blocks(filepath, category, rel_path):
                entries.append(block)
                texts.append(block["full_text"])
    return entries, texts


def _build_index() -> Tuple[List[Dict], np.ndarray]:
    """
    扫描 knowledge_base/ 下所有 .md 文件，按 ## 分块解析段落并生成向量。

    存储优先级：
      1. Milvus（主）：新鲜则 load_all；过期则重建并全量写入
      2. 本地 JSON 快照（降级）：Milvus 不可用时只读，保证 RAG 不瘫痪
      3. 纯解析兜底：连快照都没有时返回无向量条目，检索走关键词路径

    返回 (条目列表, 向量矩阵)——向量矩阵可能为空 (0, DIM)，调用方需容忍。
    """
    global _entries_cache, _embeddings_cache, _index_mtime

    # 1. 检查知识库文件是否有更新
    latest_mtime = 0.0
    for root, _, files in os.walk(KNOWLEDGE_DIR):
        for f in files:
            if f.endswith(".md") and not f.startswith("."):
                mtime = os.path.getmtime(os.path.join(root, f))
                if mtime > latest_mtime:
                    latest_mtime = mtime

    # 2. 内存缓存命中
    if _entries_cache is not None and _embeddings_cache is not None and latest_mtime <= _index_mtime:
        return _entries_cache, _embeddings_cache

    # 3. Milvus 主路径
    if _MILVUS_ENABLED:
        try:
            client = store.get_client(_MILVUS_URI)
            store.ensure_collection(client)
            cnt = store.count(client)
            db_mtime = float(_read_build_info().get("build_mtime", 0.0))

            if cnt > 0 and latest_mtime > 0 and db_mtime >= latest_mtime:
                # 新鲜：直接加载
                entries, vectors = store.load_all(client)
                emb = np.array(vectors, dtype=np.float32) if vectors else np.empty((0, EMBEDDING_DIM))
                _entries_cache, _embeddings_cache, _index_mtime = entries, emb, db_mtime
                logger.info("Milvus 命中: %d 条", len(entries))
                return entries, emb

            # 过期或为空 → 重建
            entries, texts_to_embed = _parse_all_blocks()
            embeddings = _batch_embed(texts_to_embed) if texts_to_embed else np.empty((0, EMBEDDING_DIM))
            if len(embeddings):
                norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-8
                embeddings = embeddings / norms  # 单位化后 IP == 余弦
            if entries:
                store.drop_collection(client)
                store.ensure_collection(client)
                n = store.insert_entries(client, entries, embeddings)
                _write_build_info(latest_mtime)
                _save_snapshot(entries, embeddings)
                logger.info("Milvus 重建完成: %d 条", n)
            _entries_cache, _embeddings_cache, _index_mtime = entries, embeddings, latest_mtime
            return entries, embeddings
        except Exception as e:
            logger.warning("Milvus 主路径不可用(%s: %s)，尝试快照降级",
                           type(e).__name__, e)

    # 4. 快照降级 / 首次构建兜底
    snap_entries, snap_emb = _load_snapshot()
    if snap_entries:
        _entries_cache, _embeddings_cache, _index_mtime = snap_entries, snap_emb, latest_mtime
        logger.warning("已降级到本地快照: %d 条", len(snap_entries))
        return snap_entries, snap_emb

    # 5. 无任何持久化数据 → 解析出结构化条目（无向量，走关键词检索路径）
    entries, _texts = _parse_all_blocks()
    _entries_cache = entries
    _embeddings_cache = np.empty((0, EMBEDDING_DIM))
    _index_mtime = latest_mtime
    return entries, _embeddings_cache


# ============================================================
# Embedding API
# ============================================================

def _batch_embed(texts: List[str]) -> np.ndarray:
    """批量调用 DashScope 文本转向量"""
    all_vectors = []
    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i:i + EMBEDDING_BATCH_SIZE]
        resp = TextEmbedding.call(model=EMBEDDING_MODEL, input=batch)

        if resp.status_code != 200:
            raise RuntimeError(
                f"Embedding API 调用失败 (batch {i // EMBEDDING_BATCH_SIZE}): "
                f"code={resp.status_code}, message={resp.message}"
            )

        for emb in resp.output["embeddings"]:
            all_vectors.append(emb["embedding"])

    return np.array(all_vectors, dtype=np.float32)


# ============================================================
# 检索策略
# ============================================================

# ===== 语义标签路由（v2 新增）=====
# 解决"个性化标签无法词面匹配"的问题：用户问"带爸妈去哪玩"和标签「亲子」零词汇重叠。
# 做法：给每个标签本身算一个 embedding（导入侧一次，进程内缓存），
# 查询时复用同一个查询向量算余弦，超过阈值的标签被"激活"，参与软加分与两段式过滤。
# 成本：~40 个标签 × 查询向量，纯 numpy 点积，可忽略。

# 激活阈值：text-embedding-v2 中文相关语义的余弦大多在 0.35~0.6 区间，
# 0.45 为保守起点——过高会漏激活（路由失效），过低会激活无关标签（加分变噪音）。可按日志调优。
TAG_SEMANTIC_THRESHOLD = 0.38   # 校准：真语义对地板≈0.40，噪声天花板≈0.27（7例实测，偏召回）
TAG_ROUTE_TOP_N = 4          # 单次查询最多激活的标签数
_TAG_VEC_CACHE: Optional[Tuple[List[str], Optional[np.ndarray]]] = None
_QUERY_EMB_CACHE: Dict[str, np.ndarray] = {}
_QUERY_EMB_CACHE_MAX = 128


def _embed_query_cached(query: str) -> Optional[np.ndarray]:
    """查询向量化（带进程内缓存）。同一次检索里主排序与标签路由共用同一个向量，
    不产生额外 API 调用。失败返回 None。"""
    cached = _QUERY_EMB_CACHE.get(query)
    if cached is not None:
        return cached
    try:
        resp = TextEmbedding.call(model=EMBEDDING_MODEL, input=[query])
        if resp.status_code != 200:
            logger.warning("查询向量化失败: %s", resp.message)
            return None
        vec = np.array(resp.output["embeddings"][0]["embedding"], dtype=np.float32)
    except Exception as e:
        logger.warning("查询向量化异常: %s", e)
        return None
    if len(_QUERY_EMB_CACHE) >= _QUERY_EMB_CACHE_MAX:
        _QUERY_EMB_CACHE.clear()  # 简单防膨胀；正常会话内不同 query 数量有限
    _QUERY_EMB_CACHE[query] = vec
    return vec


def _tag_gloss_text(tag_name: str) -> str:
    """标签的向量化文本。v3 教训：纯模式词与口语化查询零词汇重叠，
    余弦塌到 0.2x 区间无法激活；改用场景化白话描述为主、少量代表词落地为辅。"""
    desc = _TAG_DESCRIPTIONS.get(tag_name)
    if desc:
        patterns = _TAG_DICT.get(tag_name, [])
        return f"{tag_name}：{desc}（{'、'.join(patterns[:3])}）"
    # 区镇等无描述标签：退回模式词
    return f"{tag_name} " + " ".join(_TAG_DICT.get(tag_name, [])[:8])


def _get_tag_matrix() -> Tuple[List[str], Optional[np.ndarray]]:
    """惰性构建标签向量矩阵（每行已归一化）。API 失败时返回 (names, None)。"""
    global _TAG_VEC_CACHE
    if _TAG_VEC_CACHE is not None:
        return _TAG_VEC_CACHE
    names = list(_TAG_DICT.keys())
    try:
        matrix = _batch_embed([_tag_gloss_text(n) for n in names])
        norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-8
        _TAG_VEC_CACHE = (names, matrix / norms)
        logger.info("语义标签路由就绪：%d 个标签向量", len(names))
    except Exception as e:
        logger.warning("标签向量构建失败，语义路由降级关闭: %s", e)
        _TAG_VEC_CACHE = (names, None)
    return _TAG_VEC_CACHE


def _route_semantic_tags(query_vec: Optional[np.ndarray]) -> List[Tuple[str, float]]:
    """
    语义标签路由：query 向量 vs 全部标签向量，返回激活的 [(tag, score)]。
    未过阈值的标签不返回。查询向量为 None 或标签矩阵不可用时返回 []。
    """
    if query_vec is None:
        return []
    names, matrix = _get_tag_matrix()
    if matrix is None or len(names) == 0:
        return []
    qn = query_vec / (np.linalg.norm(query_vec) + 1e-8)
    scores = matrix @ qn
    order = np.argsort(scores)[::-1]
    out: List[Tuple[str, float]] = []
    for i in order[:TAG_ROUTE_TOP_N]:
        s = float(scores[i])
        if s >= TAG_SEMANTIC_THRESHOLD:
            out.append((names[int(i)], round(s, 4)))
    return out


def _vector_search(query: str, entries: List[Dict], emb_matrix: np.ndarray, top_k: int) -> List[Tuple[Dict, float]]:
    """向量语义检索：query 向量化 → 余弦相似度 → 取 top_k"""
    # v2: 改用带缓存的查询向量（与语义标签路由共享，省一次 API 调用）
    query_vec = _embed_query_cached(query)
    if query_vec is None:
        raise RuntimeError("查询向量化失败")

    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-8)
    doc_norms = emb_matrix / (np.linalg.norm(emb_matrix, axis=1, keepdims=True) + 1e-8)
    scores = np.dot(doc_norms, query_norm)

    if len(scores) == 0:
        return []
    top_indices = np.argsort(scores)[::-1][:top_k]
    return [(entries[i], float(scores[i])) for i in top_indices if scores[i] > 0]


def _keyword_boost(entry: Dict, keywords: List[str]) -> float:
    """
    关键词命中加权：全文匹配 + 标签匹配双路加权。
    标签命中比普通正文命中权重更高（因为标签是语义浓缩）。
    """
    boost = 0.0
    full_text = entry.get("full_text", "").lower()
    title = entry.get("title", "").lower()
    tags = [t.lower() for t in entry.get("tags", [])]

    for kw in keywords:
        kw_lower = kw.lower()

        # 标签命中：高权重（语义级别匹配）
        for tag in tags:
            if kw_lower in tag:
                boost += 0.20
                break

        # 标题命中：中权重
        if kw_lower in title:
            boost += 0.12

        # 正文命中：低权重累积
        count = full_text.count(kw_lower)
        boost += min(count * 0.03, 0.15)

    return min(boost, 0.6)


def _tag_boost(entry_tags: List[str], query_tags: List[str]) -> float:
    """
    标签级别匹配：如果查询中提取到的标签和 entry 的标签有交集，
    给额外加权（标签匹配是精准的语义对齐）。
    """
    if not query_tags or not entry_tags:
        return 0.0
    entry_set = set(t.lower() for t in entry_tags)
    query_set = set(t.lower() for t in query_tags)
    overlap = len(entry_set & query_set)
    if overlap > 0:
        return min(overlap * 0.15, 0.45)
    return 0.0


def _extract_query_tags(query: str) -> List[str]:
    """从查询文本中提取可能匹配的标签（用于标签级别的精准匹配）"""
    query_lower = query.lower()
    matched = []
    for tag_name, patterns in _TAG_DICT.items():
        for pattern in patterns:
            if pattern.lower() in query_lower:
                matched.append(tag_name)
                break
    return matched


# RRF 平滑常数。原论文(Cormack et al. SIGIR 2009)在 TREC 大语料上取 60，
# 语料规模越小平滑常数越要小 —— 否则名次差异会被压平，融合退化成"是否命中"的投票。
# 本库 50 题 Golden Set 上扫描 k ∈ {1,5,10,20,60} 的 Recall@5：
#     k=1  0.8200 | k=5  0.8200 | k=10 0.7900 | k=20 0.7900 | k=60 0.7900
# k=5 已到最优平台，且不像 k=1 那样过度依赖单路头名，故取 5。
RRF_K = 5

# BM25 融合检索器缓存：构建索引要对全库 jieba 分词，逐 query 重建是延迟虚高的主因
_HYBRID_RETRIEVER_CACHE = {}


def _get_hybrid_retriever(entries, emb_matrix, fusion="rrf", rrf_k=RRF_K):
    """
    取（或构建）BM25 融合检索器，按语料指纹缓存复用。

    以 (融合策略, k, 条目数, 标题序列) 为 key —— 知识库内容变化会改变标题序列，
    从而自然失效重建，不会用到过期索引。
    """
    from tools.knowledge.hybrid_retriever import BM25HybridRetriever

    key = (fusion, rrf_k, len(entries),
           tuple(e.get("title", "") for e in entries))
    retriever = _HYBRID_RETRIEVER_CACHE.get(key)
    if retriever is None:
        retriever = BM25HybridRetriever(entries, emb_matrix,
                                        fusion=fusion, rrf_k=rrf_k)
        if len(_HYBRID_RETRIEVER_CACHE) > 16:
            _HYBRID_RETRIEVER_CACHE.clear()
        _HYBRID_RETRIEVER_CACHE[key] = retriever
    return retriever


def _bm25_fused_rank(query: str, entries: List[Dict], emb_matrix,
                     max_results: int, fusion: str = "rrf",
                     rrf_k: int = RRF_K) -> List[Dict]:
    """
    降级管线的 BM25 + 向量双路融合检索。

    产出与 _hybrid_search 同构的 ranked 列表（含 _score），下游置信度与
    城市匹配逻辑可零改动复用。
    """
    retriever = _get_hybrid_retriever(entries, emb_matrix,
                                      fusion=fusion, rrf_k=rrf_k)
    fused = retriever.search(query, top_k=max_results,
                             candidate_k=max(max_results * 2, 20))
    ranked = []
    for idx, score in fused:
        entry = dict(entries[idx])
        entry["_vector_score"] = 0.0
        entry["_kw_boost"] = 0.0
        entry["_tag_boost"] = 0.0
        entry["_score"] = round(float(score), 4)
        ranked.append(entry)
    return ranked


def _milvus_rank(query: str, city: str, max_price: int, max_results: int,
                 mode: str = "hybrid", rrf_k: int = 5) -> List[Dict]:
    """
    Milvus 主检索路径：服务端混合检索(稠密+中文BM25) + 应用层精排。

    mode: "vector"=纯稠密向量单路；"hybrid"=两路 RRF 融合（默认）；
          "linear"=两路 WeightedRanker 加权（对照实验用）。
          说明：服务端融合只决定"召回哪些条目"，最终排序仍由应用层重算的
          _score 决定（见下方 results.sort），置信度沿用本地余弦语义。

    返回与 _hybrid_search 完全同构的 ranked 列表（含 _score/_vector_score/
    _kw_boost/_tag_boost/_sem_tag_boost/_scenario_filtered/_semantic_tags），
    下游城市匹配/置信度/输出逻辑零改动复用。
    失败抛异常由调用方降级到旧管线。
    """
    client = store.get_client(_MILVUS_URI)
    qvec = _embed_query_cached(query)
    if qvec is None:
        raise RuntimeError("查询向量化失败")

    # 语义标签路由（与主检索共用同一个查询向量，零额外 API 成本）
    sem_tags = _route_semantic_tags(qvec)
    sem_tag_names = [t for t, _ in sem_tags]

    expr = store.build_filter(city=city, max_price=max_price)
    limit = max(max_results * 2, 10)
    hits = store.hybrid_search(
        client, query,
        [float(x) for x in qvec], expr, limit,
        ranker=("weighted" if mode == "linear" else "rrf"),
        rrf_k=rrf_k,
        use_sparse=(mode != "vector"),
    )

    keywords = re.split(r"[\s,，、]+", query.strip())
    keywords = [k for k in keywords if k]
    query_tags = _extract_query_tags(query)

    qn = qvec / (np.linalg.norm(qvec) + 1e-8)
    results = []
    for ent in hits:
        dvec = ent.pop("_dense_vec", None)
        ent.pop("_fused_score", None)

        # 服务端融合只负责排序；置信度沿用旧版余弦语义（本地精确计算）
        vec_score = 0.0
        if dvec:
            dv = np.array(dvec, dtype=np.float32)
            vec_score = float(np.dot(dv / (np.linalg.norm(dv) + 1e-8), qn))

        kw_boost = _keyword_boost(ent, keywords) if keywords else 0.0
        tg_boost = _tag_boost(ent.get("tags", []), query_tags) if query_tags else 0.0
        sem_boost = _semantic_tag_boost(ent.get("tags", []), sem_tag_names)
        final = vec_score + kw_boost + tg_boost + sem_boost

        r = dict(ent)
        r["_vector_score"] = round(vec_score, 4)
        r["_kw_boost"] = round(kw_boost, 4)
        r["_tag_boost"] = round(tg_boost, 4)
        r["_sem_tag_boost"] = round(sem_boost, 4)
        r["_score"] = round(final, 4)
        results.append(r)

    results.sort(key=lambda x: x["_score"], reverse=True)
    if not results or results[0]["_score"] < CONFIDENCE_THRESHOLD:
        return []

    # 两段式：优先命中激活场景的结果；覆盖不足自动放弃（防零召回）
    scenario_applied = False
    if sem_tag_names:
        act = set(sem_tag_names)
        covered = [x for x in results if set(x.get("tags", [])) & act]
        if len(covered) >= min(max_results, 3):
            results = covered
            scenario_applied = True

    top = results[:max_results]
    for r in top:
        r["_scenario_filtered"] = scenario_applied
        r["_semantic_tags"] = [{"tag": t, "score": s} for t, s in sem_tags]
    return top


def _semantic_tag_boost(entry_tags: List[str], sem_tag_names: List[str]) -> float:
    """
    语义激活标签的软加分。比词面标签匹配（0.15/个）更轻——语义激活带有不确定性，
    只做排序微调，不喧宾夺主。
    """
    if not sem_tag_names or not entry_tags:
        return 0.0
    overlap = len(set(t.lower() for t in entry_tags) & set(s.lower() for s in sem_tag_names))
    if overlap > 0:
        return min(overlap * 0.08, 0.24)
    return 0.0


def _hybrid_search(
    query: str, entries: List[Dict], emb_matrix: np.ndarray, max_results: int
) -> List[Dict]:
    """
    混合检索：
    1. 向量语义相似度（主排序）
    2. 关键词全文 + 标签命中加权（辅）
    3. 词面查询标签交集加分（精准对齐）
    4. 语义标签路由：激活场景标签 → 软加分 + 两段式场景过滤（覆盖不足自动放弃，防零召回）
    5. 置信度阈值过滤

    返回的每个条目带 _score / _vector_score / _kw_boost / _tag_boost /
    _sem_tag_boost / _scenario_filtered / _semantic_tags 字段。
    """
    keywords = re.split(r"[\s,，、]+", query.strip())
    keywords = [k for k in keywords if k]
    query_tags = _extract_query_tags(query)

    candidate_k = max(max_results * 2, 10)
    try:
        candidates = _vector_search(query, entries, emb_matrix, candidate_k)
    except Exception:
        return _keyword_only_search(entries, keywords, max_results)

    # ===== v2: 语义标签路由（复用主检索的同一个查询向量，零额外 API 成本）=====
    sem_tags: List[Tuple[str, float]] = []
    try:
        qvec = _embed_query_cached(query)
        sem_tags = _route_semantic_tags(qvec)
    except Exception as e:
        logger.debug("语义标签路由异常（不影响主流程）: %s", e)
    sem_tag_names = [t for t, _ in sem_tags]

    results = []
    for entry, vec_score in candidates:
        kw_boost = _keyword_boost(entry, keywords) if keywords else 0.0
        tg_boost = _tag_boost(entry.get("tags", []), query_tags) if query_tags else 0.0
        sem_boost = _semantic_tag_boost(entry.get("tags", []), sem_tag_names)
        final_score = vec_score + kw_boost + tg_boost + sem_boost

        result = dict(entry)
        result["_vector_score"] = round(vec_score, 4)
        result["_kw_boost"] = round(kw_boost, 4)
        result["_tag_boost"] = round(tg_boost, 4)
        result["_sem_tag_boost"] = round(sem_boost, 4)
        result["_score"] = round(final_score, 4)
        results.append(result)

    results.sort(key=lambda x: x["_score"], reverse=True)

    if not results or results[0]["_score"] < CONFIDENCE_THRESHOLD:
        return []

    # ===== v2 两段式：优先返回命中激活场景的条目；覆盖不足则整体放弃过滤 =====
    scenario_applied = False
    if sem_tag_names:
        act = set(sem_tag_names)
        covered = [r for r in results if set(r.get("tags", [])) & act]
        need = min(max_results, 3)
        if len(covered) >= need:
            results = covered
            scenario_applied = True

    top = results[:max_results]
    for r in top:
        r["_scenario_filtered"] = scenario_applied
        r["_semantic_tags"] = [{"tag": t, "score": s} for t, s in sem_tags]
    return top


def _keyword_only_search(entries: List[Dict], keywords: List[str], max_results: int) -> List[Dict]:
    """纯关键词检索（向量 API 失败时的回退方案）"""
    if not keywords:
        return [dict(e) for e in entries[:max_results]]

    scored = []
    for e in entries:
        s = 0.0
        full_text = e.get("full_text", "")
        title = e.get("title", "")
        tags = [t.lower() for t in e.get("tags", [])]

        for kw in keywords:
            kw_l = kw.lower()
            if kw_l in title.lower():
                s += 3.0
            for tag in tags:
                if kw_l in tag:
                    s += 2.5
            s += full_text.lower().count(kw_l)

        if s > 0:
            result = dict(e)
            result["_score"] = round(s, 4)
            result["_vector_score"] = 0.0
            result["_kw_boost"] = round(s, 4)
            result["_tag_boost"] = 0.0
            scored.append(result)

    scored.sort(key=lambda x: x["_score"], reverse=True)
    return scored[:max_results]


# ============================================================
# 对外暴露的 LangChain Tool
# ============================================================

def _monotonic_ms() -> float:
    """返回单调时钟毫秒数，用于高精度计时。"""
    import time
    return time.perf_counter() * 1000


# ===== RAG 详细日志（TXT 实时追加） =====
_RAG_LOG_PATH = Path("data/monitoring/rag_detail.log")


def _log_rag_query(query: str, ranked: list, latency_ms: float,
                   routing_info: Optional[dict] = None,
                   price_filter_applied: bool = False):
    """详细记录每次 RAG 检索到 TXT + RAGMonitor。"""
    import time as _time
    from datetime import datetime as _datetime

    now_str = _datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- 1. 写入详细 TXT 日志 ----
    try:
        _RAG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(str(_RAG_LOG_PATH), "a", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"[{now_str}] 查询: {query}\n")
            f.write(f"耗时: {latency_ms:.1f} ms | 命中数: {len(ranked)} | "
                    f"阈值: {CONFIDENCE_THRESHOLD}"
                    + (" | 价格过滤" if price_filter_applied else "") + "\n")
            if routing_info:
                acts = ", ".join(f"{t}({s})" for t, s in routing_info.get("activated", []))
                f.write(f"语义路由: 激活[{acts}] "
                        f"场景过滤={'生效' if routing_info.get('scenario_filtered') else '未生效(覆盖不足)'}\n")
            f.write("-" * 80 + "\n")

            if not ranked:
                f.write("(无匹配结果)\n")
            else:
                for i, r in enumerate(ranked, 1):
                    score = r.get("_score", 0)
                    vs = r.get("_vector_score", 0)
                    kw = r.get("_kw_boost", 0)
                    tg = r.get("_tag_boost", 0)
                    f.write(f"\n  [{i}] {r.get('title', '(无标题)')}\n")
                    f.write(f"      综合得分: {score:.4f}  "
                            f"(向量:{vs:.4f} + 关键词:{kw:.4f} + 标签:{tg:.4f})\n")
                    f.write(f"      标签: {r.get('tags', [])}\n")
                    f.write(f"      来源: {r.get('category', '')}/{r.get('source_file', '')}\n")
                    f.write(f"      内容: {r.get('content', '')[:300]}\n")
            f.write("\n")
    except Exception as e:
        logger.warning("RAG TXT 写入异常: %s", e)

    # ---- 2. 写入 RAGMonitor（仪表盘用） ----
    try:
        from monitoring.rag_logger import RAGMonitor, RAGLogEntry
        monitor = RAGMonitor.get_instance()
        top_scores = [r.get("_score", 0.0) for r in ranked[:3]]
        entry = RAGLogEntry(
            query=query,
            retrieved_count=len(ranked),
            top1_score=top_scores[0] if top_scores else 0.0,
            top3_scores=top_scores,
            avg_confidence=sum(top_scores) / len(top_scores) if top_scores else 0.0,
            latency_ms=round(latency_ms, 2),
            threshold=CONFIDENCE_THRESHOLD,
            passed_threshold=len(ranked) > 0,
        )
        monitor.log(entry)
        logger.debug("RAG 已记录: query=%s, count=%d, buffer=%d",
                     query[:40], len(ranked), len(monitor._buffer))
    except ImportError:
        logger.debug("RAGMonitor 未安装")
    except Exception as e:
        logger.warning("RAG 记录异常: %s: %s", type(e).__name__, e)


@tool
def search_knowledge(query: str, max_results: int = 6, city: str = "",
                     max_price: int = 0, mode: str = "hybrid",
                     rrf_k: int = 0) -> str:
    """
    在本地知识库中搜索中山美食/旅行/景点/住宿/交通/购物经验（向量语义检索）。
    这是本地经验库的首要检索工具。当用户询问以下任一类问题时，必须优先使用：
    - 美食推荐："推荐好吃的XX"、"XX哪家好吃"、"早茶/乳鸽/海鲜推荐"、"宵夜去哪"
    - 景点游玩："有什么景点"、"老城/古镇/山水/海滩有什么"、"XX好不好玩"、"游乐场"
    - 行程路线："一日游/两日游路线"、"怎么玩"、"行程规划"、"出行方案"、"怎么安排"
    - 住宿推荐："住哪里"、"推荐酒店/民宿"、"XX附近住宿"、"温泉酒店"
    - 交通出行："怎么去XX"、"深中通道"、"公交/自驾"、"城轨怎么坐"
    - 购物特产："去哪逛街"、"买手信/特产"、"商场推荐"、"杏仁饼/腊味去哪买"
    - 实用贴士："什么时候去最好"、"有什么注意事项"

    **重要**：务必传入 city 参数（用户的默认城市），系统会标注每条结果是否匹配该城市。
    如果大量结果 city_match 为 false，说明知识库中缺少该城市的数据，应如实告知用户。
    当用户表达预算约束（"月底没钱""人均50以内""省钱吃法"）时，传入 max_price（元/人）。

    系统内置语义场景路由：像"带爸妈去哪玩""约会去哪""周末遛弯"这类个性化意图，
    会自动激活对应场景标签（亲子/情侣/网红打卡等）参与排序与筛选，无需额外参数。

    Args:
        query: 搜索关键词或自然语言描述，如"中山一日游路线"、"推荐好吃的乳鸽"
        max_results: 最大返回条数，默认6
        city: 用户当前所在城市，如"中山"、"梅州"。用于标注结果是否属于该城市
        max_price: 人均消费上限（元）。0 表示不限制。按结构化 price_min 字段前置过滤，
                   价格未知的条目会保留。如月底省钱场景传 30~35
        mode: 检索模式，三选一：
              "hybrid"（默认）BM25+向量双路，RRF 融合（score=Σ 1/(k+rank)）
              "linear"        BM25+向量双路，min-max 归一化后线性加权（对照用）
              "vector"        纯稠密向量单路（评测 baseline）
              说明：Milvus 可用时服务端融合只决定召回集，最终排序仍由应用层
              重算的 _score 决定；两种模式下该行为一致。
        rrf_k: 覆盖 RRF 平滑常数（0=用模块默认 RRF_K=20）。调参/评测用。

    Returns:
        JSON 格式搜索结果，含 city_match_summary（城市匹配概况）、semantic_routing
        （语义场景路由详情）和每条结果的 city_match / price 标注
    """
    _t0 = _monotonic_ms()
    # rrf_k 由 LLM 传入时做范围钳制，防止异常值破坏融合
    _rrf_k = rrf_k if (isinstance(rrf_k, int) and 0 < rrf_k <= 1000) else RRF_K

    entries, emb_matrix = _build_index()

    if not entries:
        return json.dumps({"error": "知识库为空，请先导入数据", "total": 0}, ensure_ascii=False)

    # Milvus 熔断状态在函数内会被改写，声明为 global 避免被当成局部变量
    global _MILVUS_CIRCUIT_OPEN, _MILVUS_FAIL_COUNT

    # ===== v3: Milvus 主路径（服务端混合检索 + expr 下推过滤） =====
    ranked: Optional[List[Dict]] = None
    price_filter_applied = False
    if _MILVUS_ENABLED and not _MILVUS_CIRCUIT_OPEN:
        # 前置 TCP 探活：远端不可达时直接开熔断，避免每题卡一次连接超时
        if _milvus_reachable(_MILVUS_URI):
            try:
                ranked = _milvus_rank(query, city, max_price, max_results,
                                      mode=mode, rrf_k=_rrf_k)
                price_filter_applied = bool(max_price and max_price > 0)
                logger.debug("Milvus 路径: %d 条结果", len(ranked))
            except Exception as e:
                _MILVUS_FAIL_COUNT += 1
                logger.warning(
                    "Milvus 检索失败(%s: %s)，降级应用层管线 (失败计数 %d/%d)",
                    type(e).__name__, e, _MILVUS_FAIL_COUNT, _MILVUS_FAIL_THRESHOLD)
                if _MILVUS_FAIL_COUNT >= _MILVUS_FAIL_THRESHOLD:
                    _MILVUS_CIRCUIT_OPEN = True
                    logger.warning("Milvus 连续失败达阈值，熔断开启，后续查询直接走降级路径")
                ranked = None
        else:
            _MILVUS_CIRCUIT_OPEN = True
            logger.debug("Milvus 不可达（TCP 探活失败），熔断开启，走降级路径")

    # ===== 降级路径：旧版应用层管线（Milvus 不可用时的兜底） =====
    if ranked is None:
        # 前置过滤：按 city 字段过滤 entries（基于 frontmatter 显式标注）
        # 只保留 city 匹配的条目 + city="未知"的条目（旧数据兜底，不误杀）
        if city:
            filtered_indices = [
                i for i, e in enumerate(entries)
                if e.get("city", "未知") == city or e.get("city", "未知") == "未知"
            ]
            if filtered_indices and len(filtered_indices) < len(entries):
                entries = [entries[i] for i in filtered_indices]
                emb_matrix = emb_matrix[filtered_indices]

        # 前置过滤：按人均预算过滤（v2 结构化 price_min 字段）
        # 价格未知的条目保留（与 city="未知" 同一兜底哲学：不因信息缺失而误杀）
        if max_price and max_price > 0:
            filtered_indices = [
                i for i, e in enumerate(entries)
                if e.get("price_min") is None or (e.get("price_min") or 0) <= max_price
            ]
            if filtered_indices and len(filtered_indices) < len(entries):
                entries = [entries[i] for i in filtered_indices]
                emb_matrix = emb_matrix[filtered_indices]
                price_filter_applied = True

        # mode="hybrid" 走双路融合，"vector" 走单路语义检索。
        # 旧实现先无条件跑 _hybrid_search、再用融合结果覆盖，等于每次查询跑两遍
        # 完整检索（两次 Embedding 调用），延迟虚高约一倍 —— 这里按 mode 二选一。
        if mode in ("hybrid", "linear"):
            try:
                from tools.knowledge.hybrid_retriever import is_bm25_available
                if is_bm25_available():
                    ranked = _bm25_fused_rank(
                        query, entries, emb_matrix, max_results,
                        fusion="rrf" if mode == "hybrid" else "linear",
                        rrf_k=_rrf_k,
                    )
                    logger.debug("BM25 融合检索(%s): %d 条结果", mode, len(ranked))
                else:
                    logger.warning("BM25 依赖未安装，回退到纯向量检索")
                    ranked = _hybrid_search(query, entries, emb_matrix, max_results)
            except Exception as e:
                logger.warning("BM25 融合检索异常: %s，回退到纯向量检索", e)
                ranked = _hybrid_search(query, entries, emb_matrix, max_results)
        else:
            ranked = _hybrid_search(query, entries, emb_matrix, max_results)

    _latency_ms = _monotonic_ms() - _t0

    # 提取语义路由信息（由 _hybrid_search 附着在结果上）
    routing_info = None
    if ranked and ranked[0].get("_semantic_tags"):
        routing_info = {
            "activated": [(d["tag"], d["score"]) for d in ranked[0]["_semantic_tags"]],
            "scenario_filtered": bool(ranked[0].get("_scenario_filtered")),
        }
    _log_rag_query(query, ranked, _latency_ms, routing_info, price_filter_applied)

    # ===== 城市匹配检测（双层：frontmatter city 字段优先，tags 区镇兜底） =====
    target_districts = set()
    if city and city in CITY_DISTRICTS:
        target_districts = set(CITY_DISTRICTS[city])

    results = []
    city_match_count = 0
    for e in ranked:
        score = e.get("_score", 0.0)
        tags = e.get("tags", [])
        entry_city = e.get("city", "未知")  # 来自 frontmatter 的显式标注

        # 优先用 frontmatter 的 city 字段判断（准确）
        # 兜底用 tags 区镇匹配（旧数据无 frontmatter 时）
        entry_district_tags = set()
        city_detected = entry_city if entry_city != "未知" else ""
        city_match = True  # 无城市限制时默认为匹配

        if city:
            # 第1层：frontmatter city 字段直接判断
            if entry_city != "未知":
                if entry_city == city:
                    city_match = True
                    city_match_count += 1
                else:
                    city_match = False
                    city_detected = entry_city
            # 第2层：无 frontmatter 时，用 tags 区镇兜底判断
            elif target_districts:
                for tag in tags:
                    for cn, districts in CITY_DISTRICTS.items():
                        if tag in districts:
                            entry_district_tags.add(tag)
                            if cn != city:
                                city_detected = cn
                            break

                matched = bool(entry_district_tags & target_districts)
                has_other_city_tag = bool(entry_district_tags - target_districts)

                if matched:
                    city_match = True
                    city_match_count += 1
                elif has_other_city_tag:
                    city_match = False
                elif not entry_district_tags:
                    city_match = True
                    city_match_count += 1
                else:
                    city_match = False

        # 文本级信心指示器
        if score >= 0.70:
            level = "highly_reliable"
            label = "确信"
        elif score >= 0.45:
            level = "reliable"
            label = "比较确信"
        elif score >= CONFIDENCE_THRESHOLD:
            level = "uncertain"
            label = "低确信"
        else:
            level = "low"
            label = "低于阈值"

        # 人均消费档位标注（v2 结构化字段）
        _pmin, _pmax = e.get("price_min"), e.get("price_max")
        _plevel = e.get("price_level") or 0
        price_info = {
            "min": _pmin,
            "max": _pmax,
            "level": _plevel,
            "label": {0: "未知", 1: "省钱档(≤35/人)", 2: "日常档(36-90/人)", 3: "高端档(>90/人)"}.get(_plevel, "?"),
        }

        result_entry = {
            "title": e.get("title", ""),
            "tags": tags,
            "content": e.get("content", ""),
            "source": e.get("source_file", ""),
            "price": price_info,
            "confidence": {
                "score": score,
                "level": level,
                "label": label,
                "breakdown": {
                    "vector_similarity": e.get("_vector_score", 0.0),
                    "keyword_boost": e.get("_kw_boost", 0.0),
                    "tag_match_boost": e.get("_tag_boost", 0.0),
                    "semantic_tag_boost": e.get("_sem_tag_boost", 0.0),
                },
            },
        }

        if city:
            result_entry["city_match"] = city_match
            if city_detected:
                result_entry["city_detected"] = city_detected

        results.append(result_entry)

    # 城市匹配概况
    output = {
        "query": query,
        "threshold": CONFIDENCE_THRESHOLD,
        "total": len(results),
        "results": results,
    }
    if city:
        total = len(results)
        if total > 0:
            match_ratio = city_match_count / total
            if match_ratio == 0:
                summary = f"❌ 所有 {total} 条结果均不匹配当前城市「{city}」。知识库中暂无该城市的数据，请不要向用户展示这些结果，如实告知用户知识库仅覆盖中山等已收录城市。"
            elif match_ratio < 0.5:
                summary = f"⚠️ 仅 {city_match_count}/{total} 条匹配当前城市「{city}」，大部分内容可能属于其他城市，请谨慎引用。"
            else:
                summary = f"✅ {city_match_count}/{total} 条匹配当前城市「{city}」。"
        else:
            summary = f"未找到匹配「{city}」的结果。"
        output["city_match_summary"] = summary

    if max_price and max_price > 0:
        output["price_filter"] = (
            f"已按人均≤{max_price}元过滤" + ("" if price_filter_applied else "（无结构化价格数据，未实际生效）")
            if results else f"人均≤{max_price}元：无结果"
        )

    # 语义场景路由概况（v2）
    if routing_info:
        acts = ", ".join(f"{t}({s})" for t, s in routing_info["activated"])
        output["semantic_routing"] = {
            "activated_tags": acts,
            "scenario_filtered": routing_info["scenario_filtered"],
            "note": "已按激活的场景标签参与排序" + ("与筛选" if routing_info["scenario_filtered"] else "（覆盖不足，未做硬筛）"),
        }

    return json.dumps(output, ensure_ascii=False, indent=2)