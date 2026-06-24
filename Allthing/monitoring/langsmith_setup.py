import os
import logging

logger = logging.getLogger("lifeops.langsmith")


def init_langsmith():
    api_key = os.environ.get("LANGCHAIN_API_KEY", "")
    project = os.environ.get("LANGCHAIN_PROJECT", "LifeOps-Agent")

    if api_key:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_PROJECT", project)
        os.environ.setdefault("LANGCHAIN_ENDPOINT", os.environ.get(
            "LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"
        ))
        logger.info("LangSmith 追踪已启用 (project=%s)", project)
        return True
    else:
        logger.info("未设置 LANGCHAIN_API_KEY，LangSmith 追踪未启用")
        return False
