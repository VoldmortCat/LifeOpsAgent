"""BillAgent 失败策略层 —— 每个工具的原子化失败处理链。

LLM 不需要"自己琢磨"失败后该干嘛，直接查表执行。
"""

BILL_FAILURE_STRATEGIES = """
## 工具失败处理表（必须严格按顺序执行）

| 工具 | 第1次失败 | 第2次失败 | 最终兜底 |
|------|----------|----------|---------|
| get_daily_spending_baseline | 检查 data/bills/ 是否有完整月CSV文件，用 get_data_inventory 确认 | 若最近完整月无数据或筛选后无记录 → 告知"暂无日常开销基线数据" | 告知调用方"暂无日常开销基线数据"，不编造数字 |
| get_date_range_bill_data(start,end) | 检查日期格式是否正确，修正后重试 | 改用 get_data_inventory 检查本地是否有该时段文件 | 告知用户该时段无数据 |
| get_data_inventory | 重试一次（纯网络/文件IO问题） | 告知用户数据系统暂时不可用 | 引导手动检查 data/ 目录 |
| check_and_download_bill_email | 提示用户检查邮箱配置/网络 | 告知用户手动下载路径 | 给出微信支付→账单→下载的详细步骤 |
| unzip_latest_wechat_bill(password) | 确认密码是否正确（微信支付公众号查看） | 告知用户密码错误 | 给出重新获取密码的步骤 |
| get_financial_context | 告知用户"尚未设置财务信息" | 引导用户告知预算/支出数字 | 继续用已有账单数据回答 |
| get_current_time | 几乎不失败 | — | — |

## 通用终止条件

- 同一工具最多调用 2 次
- 超过 2 次后执行"最终兜底"，不再调用任何工具
- 禁止在兜底阶段编造数据
"""
