"""TravelAgent 失败策略层 —— 每个工具的原子化失败处理链。"""

TRAVEL_FAILURE_STRATEGIES = """
## 工具失败处理表

| 工具 | 第1次失败 | 第2次失败 | 最终兜底 |
|------|----------|----------|---------|
| search_knowledge(query) | 换关键词重试（如"烧烤"→"炭烤烧烤推荐"） | 自动降至 map_search_places | — |
| map_search_places(query) | 更换关键词/扩大搜索半径重试 | 降至模型内置联网搜索 | 告知"未找到相关信息" |
| map_place_details(uid) | uid 无效时，重新调 map_search_places 获取新 uid | 放弃查询详情，仅用搜索摘要推荐 | — |
| map_directions(origin,dest) | 检查起终点地址是否明确 | 告知路径规划失败，给出大致方向 | — |
| map_weather(city) | 重试一次 | 告知天气查询失败 | — |
| map_geocode(address) | 尝试简化地址（删掉门牌号）重试 | 告知地址解析失败 | — |

## 通用终止条件

- 同一工具最多调用 2 次（不同参数不算重复）
- 三层信息源全部失败 → "目前暂无相关信息，建议更换搜索词或稍后再试"
- 禁止在数据为空时强行编造推荐
"""
