"""提示词版本管理 —— 每次修改各层 prompt 时递增对应版本号。

用于 A/B 测试、回滚追踪、变更审计。
"""

PROMPT_VERSIONS = {
    "bill_base": "2.0.0",
    "bill_decision": "2.0.0",
    "bill_runtime": "2.0.0",
    "bill_failure": "2.0.0",
    "travel_base": "2.0.0",
    "travel_decision": "2.0.0",
    "travel_runtime": "2.0.0",
    "travel_failure": "2.0.0",
    "assembler": "2.0.0",
}

# 变更日志
CHANGELOG = {
    "2.0.0": "分层重构：从单文件 prompt_templates.py 拆分为 4 层独立模块",
    "1.0.0": "原始版本：prompt_templates.py 单体文件",
}


def get_version(component: str) -> str:
    """获取指定组件的版本号。"""
    return PROMPT_VERSIONS.get(component, "unknown")


def get_all_versions() -> dict:
    """获取所有组件的版本号。"""
    return dict(PROMPT_VERSIONS)
