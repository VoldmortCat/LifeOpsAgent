import os
import yaml
from pathlib import Path
from langchain_core.language_models import BaseChatModel


def create_llm(agent_cfg: dict) -> BaseChatModel:
    """根据 yml 配置创建对应提供商的 ChatModel 实例。

    agent_cfg 示例：
        {"provider": "tongyi", "model": "qwen-plus", "temperature": 0.5, ...}
        {"provider": "openai", "model": "gpt-4o", "temperature": 0.5, ...}
        {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.5, ...}

    新增提供商只需在此函数添加一个分支。
    """
    provider = agent_cfg.get("provider", "tongyi")
    model = agent_cfg.get("model", "qwen-plus")
    temperature = agent_cfg.get("temperature", 0.5)
    streaming = agent_cfg.get("streaming", False)
    enable_thinking = agent_cfg.get("enable_thinking", True)

    if provider == "tongyi":
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
    elif provider == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            streaming=streaming,
            base_url="https://api.deepseek.com/v1",
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        )
    else:
        raise ValueError(f"不支持的模型提供商: {provider}")


class ConfigLoader:
    """统一配置加载器 - 二层加载：config.yml（系统默认）+ user_config.yml（用户覆盖）"""

    # 前端可见、用户可编辑的配置字段白名单
    USER_CONFIG_KEYS = [
        "email",
        "maps.default_city",
        "bill.skip_header_rows",
    ]

    # 返回前端时需脱敏的字段
    SENSITIVE_KEYS = {
        "email.password",
    }

    def __init__(self, config_dir=None):
        if config_dir is None:
            config_dir = Path(__file__).parent
        self.config_dir = Path(config_dir)
        self.config = {}
        self._base_config = {}
        self._user_config = {}
        self.load_config()

    def load_config(self):
        """加载配置：先读系统 config.yml，再用 user_config.yml 覆盖"""
        self._base_config = self._load_file("config.yml")
        self._user_config = self._load_file("user_config.yml")
        merged = self._deep_merge(self._base_config, self._user_config)
        self.config = self._resolve_env_vars(merged)

    def reload_config(self):
        """热重载配置（用户保存后调用）"""
        self.load_config()

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """深度合并两个 dict，override 中的值覆盖 base"""
        result = dict(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = ConfigLoader._deep_merge(result[k], v)
            elif v is not None and v != "":
                result[k] = v
            else:
                result[k] = v
        return result

    def _load_file(self, filename):
        file_path = self.config_dir / filename
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _resolve_env_vars(self, cfg):
        if isinstance(cfg, dict):
            return {k: self._resolve_env_vars(v) for k, v in cfg.items()}
        elif isinstance(cfg, str) and cfg.startswith("${") and cfg.endswith("}"):
            return os.getenv(cfg[2:-1], cfg)
        return cfg

    def get(self, key, default=None):
        keys = key.split(".")
        value = self.config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def __getitem__(self, key):
        return self.get(key)

    # ---------- 用户配置 API ----------

    def _get_by_path(self, data: dict, path: str):
        """按点号路径从 dict 中取值"""
        keys = path.split(".")
        value = data
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return None
        return value

    def _set_by_path(self, data: dict, path: str, new_value):
        """按点号路径写入 dict，自动创建中间层级"""
        keys = path.split(".")
        cur = data
        for i, k in enumerate(keys[:-1]):
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]
        cur[keys[-1]] = new_value

    def get_user_config(self) -> dict:
        """读取用户配置（用于前端展示），密码脱敏"""
        result = {}
        for key_path in self.USER_CONFIG_KEYS:
            value = self._get_by_path(self.config, key_path)
            if key_path in self.SENSITIVE_KEYS and value:
                value = "******"
            result[key_path] = value
        return result

    def save_user_config(self, data: dict) -> bool:
        """保存用户配置到 user_config.yml，触发重载"""
        current_user = self._load_file("user_config.yml")
        if not current_user:
            current_user = {}

        for key_path, value in data.items():
            if key_path not in self.USER_CONFIG_KEYS:
                continue
            if key_path in self.SENSITIVE_KEYS and value == "******":
                continue  # 密码未修改，保留原值
            self._set_by_path(current_user, key_path, value)

        file_path = self.config_dir / "user_config.yml"
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(current_user, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        self.reload_config()
        return True


config = ConfigLoader()