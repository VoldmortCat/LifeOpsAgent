"""统一 LLM 注册中心 —— 集中管理所有 Agent 的 LLM 实例。

解决的问题：
  1. _get_main_llm / _get_bill_llm / _get_travel_llm 分散在三个文件中
  2. 切换模型需要改多个文件
  3. 无法追踪各 Agent 的 token 用量

使用方式：
  registry = get_llm_registry()
  llm = registry.get_llm("bill")
  registry.switch_model("travel", "qwen-plus")  # 运行时切换
  print(registry.get_usage_report())            # 用量报告
"""

import os
import time
import logging
import threading
from typing import Dict, Optional, Any

from langchain_core.language_models import BaseChatModel

logger = logging.getLogger("lifeops.llm")


class LLMRegistry:
    """统一 LLM 注册中心。

    单例模式，全局唯一。管理所有 Agent 的 LLM 实例生命周期。
    """

    _instance: Optional["LLMRegistry"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._instances: Dict[str, BaseChatModel] = {}
        self._configs: Dict[str, dict] = {}
        self._usage: Dict[str, Dict[str, int]] = {}  # {agent_type: {"calls": N, "tokens": N}}
        self._initialized = False

    @classmethod
    def get_instance(cls) -> "LLMRegistry":
        """获取全局单例。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def init_from_config(self, config: dict):
        """从 config.yml 的 agents 段初始化各 Agent 的 LLM 配置。

        config 示例:
          {"main": {"provider": "deepseek", "model": "deepseek-v4-pro", "temperature": 0.5},
           "bill": {"provider": "deepseek", "model": "deepseek-v4-pro", "temperature": 0.3},
           "travel": {"provider": "deepseek", "model": "deepseek-v4-pro", "temperature": 0.7}}
        """
        for agent_type, agent_cfg in config.items():
            self._configs[agent_type] = dict(agent_cfg)
            self._usage[agent_type] = {"calls": 0, "tokens": 0}
        self._initialized = True
        logger.info("LLM 注册中心已初始化: agents=%s", list(config.keys()))

    def get_llm(self, agent_type: str) -> BaseChatModel:
        """获取指定 Agent 的 LLM 实例（延迟创建 + 缓存）。

        Args:
            agent_type: "main" | "bill" | "travel"

        Returns:
            BaseChatModel 实例
        """
        if agent_type not in self._configs:
            raise KeyError(
                f"未知的 Agent 类型: {agent_type}。"
                f"可用: {list(self._configs.keys())}"
            )

        if agent_type not in self._instances:
            cfg = self._configs[agent_type]
            self._instances[agent_type] = self._create_llm(cfg)
            logger.info(
                "创建 LLM 实例: agent=%s provider=%s model=%s",
                agent_type, cfg.get("provider"), cfg.get("model"),
            )

        return self._instances[agent_type]

    def switch_model(self, agent_type: str, new_model: str, new_provider: Optional[str] = None):
        """运行时切换模型（清除缓存，下次 get_llm 时重新创建）。

        Args:
            agent_type: "main" | "bill" | "travel"
            new_model: 新模型名，如 "qwen-plus"
            new_provider: 新提供商，如 "tongyi"，None 则保持不变
        """
        if agent_type not in self._configs:
            raise KeyError(f"未知的 Agent 类型: {agent_type}")

        self._configs[agent_type]["model"] = new_model
        if new_provider:
            self._configs[agent_type]["provider"] = new_provider

        # 清除旧实例，强制重建
        self._instances.pop(agent_type, None)
        logger.info("切换模型: agent=%s → %s/%s", agent_type, new_provider or "不变", new_model)

    def get_model_info(self, agent_type: str) -> dict:
        """获取指定 Agent 的模型信息。"""
        cfg = self._configs.get(agent_type, {})
        return {
            "provider": cfg.get("provider", "?"),
            "model": cfg.get("model", "?"),
            "temperature": cfg.get("temperature", "?"),
        }

    def record_usage(self, agent_type: str, token_count: int = 0):
        """记录一次 LLM 调用（用于用量追踪）。"""
        if agent_type in self._usage:
            self._usage[agent_type]["calls"] += 1
            self._usage[agent_type]["tokens"] += token_count

    def get_usage_report(self) -> Dict[str, Any]:
        """获取各 Agent 的用量报告。"""
        total_calls = sum(u["calls"] for u in self._usage.values())
        total_tokens = sum(u["tokens"] for u in self._usage.values())
        return {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "by_agent": {
                agent: {
                    "calls": u["calls"],
                    "tokens": u["tokens"],
                    "model": self._configs.get(agent, {}).get("model", "?"),
                }
                for agent, u in self._usage.items()
            },
        }

    def _create_llm(self, agent_cfg: dict) -> BaseChatModel:
        """根据配置创建 LLM 实例（内部方法）。"""
        provider = agent_cfg.get("provider", "deepseek")
        model = agent_cfg.get("model", "deepseek-v4-pro")
        temperature = agent_cfg.get("temperature", 0.5)
        streaming = agent_cfg.get("streaming", False)
        enable_thinking = agent_cfg.get("enable_thinking", True)

        if provider == "deepseek":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model,
                temperature=temperature,
                streaming=streaming,
                base_url="https://api.deepseek.com/v1",
                api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            )

        elif provider == "tongyi":
            from langchain_community.chat_models import ChatTongyi
            return ChatTongyi(
                model=model,
                temperature=temperature,
                streaming=streaming,
                model_kwargs={"enable_thinking": enable_thinking},
            )

        elif provider == "openai":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model,
                temperature=temperature,
                streaming=streaming,
            )

        else:
            raise ValueError(f"不支持的模型提供商: {provider}")


# ============================================================
# 便捷访问函数（替代分散的 _get_*_llm()）
# ============================================================

def get_llm_registry() -> LLMRegistry:
    """获取全局 LLM 注册中心（自动从 config.yml 初始化）。"""
    registry = LLMRegistry.get_instance()
    if not registry._initialized:
        from config.config_loader import config
        agents_config = config.get("agents", {})
        if agents_config:
            registry.init_from_config(agents_config)
        else:
            # 兜底：默认使用 deepseek
            registry.init_from_config({
                "main": {"provider": "deepseek", "model": "deepseek-v4-pro", "temperature": 0.5},
                "bill": {"provider": "deepseek", "model": "deepseek-v4-pro", "temperature": 0.3},
                "travel": {"provider": "deepseek", "model": "deepseek-v4-pro", "temperature": 0.7},
            })
            logger.warning("config.yml 中无 agents 配置，使用默认 deepseek")
    return registry


def get_main_llm() -> BaseChatModel:
    """获取主 Agent LLM（替换旧的 _get_main_llm）。"""
    return get_llm_registry().get_llm("main")


def get_bill_llm() -> BaseChatModel:
    """获取账单 Agent LLM（替换旧的 _get_bill_llm）。"""
    return get_llm_registry().get_llm("bill")


def get_travel_llm() -> BaseChatModel:
    """获取行程 Agent LLM（替换旧的 _get_travel_llm）。"""
    return get_llm_registry().get_llm("travel")
