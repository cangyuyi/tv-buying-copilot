"""LLM 客户端：OpenAI-compatible 接口，3 次指数退避重试，失败返回 None。

零第三方依赖，仅使用标准库 urllib。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """运行时配置，从环境变量读取。"""

    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    weak_model: str = "gpt-4o-mini"  # 用于简单分类、格式转换等弱模型场景

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_key=os.getenv("AI_API_KEY", ""),
            base_url=os.getenv("AI_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("AI_MODEL", "gpt-4o-mini"),
            weak_model=os.getenv("AI_WEAK_MODEL", os.getenv("AI_MODEL", "gpt-4o-mini")),
        )


class LLMClient:
    """OpenAI-compatible Chat Completion 客户端。

    - 3 次指数退避重试（0.4s, 0.8s, 1.6s）
    - 全部失败返回 None，由调用方降级到确定性模板
    - 支持 model 参数覆盖，用于模型分级（成本优化手段一）
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()

    @property
    def available(self) -> bool:
        return bool(self.settings.api_key)

    def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        model: str | None = None,
        timeout: int = 30,
    ) -> str | None:
        """调用 Chat Completion 接口，失败返回 None。

        Args:
            system: 系统提示词
            user: 用户输入
            temperature: 采样温度，合规审核等场景用 0
            model: 覆盖默认模型（弱模型用于简单任务）
            timeout: 单次请求超时秒数
        """
        if not self.available:
            return None
        use_model = model or self.settings.model
        payload = json.dumps(
            {
                "model": use_model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.settings.base_url.rstrip('/')}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                return body["choices"][0]["message"]["content"].strip()
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError, json.JSONDecodeError):
                if attempt < 2:
                    time.sleep(0.4 * (2**attempt))
        return None
