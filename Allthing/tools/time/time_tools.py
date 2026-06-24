from datetime import datetime
from langchain_core.tools import tool

WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]


@tool
def get_current_time() -> str:
    """获取当前真实的日期和时间（精确到秒）。
    当用户问"今天几号"、"现在几点"、"当前时间"、"星期几"等时间相关问题时，必须调用此工具获取准确时间，禁止自行编造或猜测。"""
    now = datetime.now()
    return (
        f"当前时间：{now.year}年{now.month}月{now.day}日，"
        f"星期{WEEKDAY_CN[now.weekday()]}，"
        f"{now.hour:02d}时{now.minute:02d}分{now.second:02d}秒"
        f"\n（系统本地时间，UTC+8）"
    )
