"""记忆系统：短期记忆（会话内槽位）+ 长期记忆（跨会话用户偏好，线程安全）。

设计原则（来自课程笔记）：
- 不是每一步都写记忆，按需写入
- 不是每次都读全部历史，按需读取
- 长期记忆必须用户显式授权
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class ShortTermMemory:
    """会话内短期记忆：累积已确认的槽位和对话历史。

    对应课程笔记中的"任务状态"层：当前任务的关键数据和进度。
    """

    def __init__(self) -> None:
        self.slots: dict[str, Any] = {}
        self.history: list[dict[str, str]] = []
        self.turn: int = 0

    def update_slots(self, new_slots: dict[str, Any]) -> None:
        """合并新提取的槽位。use_cases 做去重合并而非覆盖。"""
        if "use_cases" in new_slots and "use_cases" in self.slots:
            prior = self.slots.get("use_cases", [])
            incoming = new_slots["use_cases"]
            new_slots["use_cases"] = list(dict.fromkeys(prior + incoming))
        self.slots.update(new_slots)

    def add_message(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})

    def recent_history(self, n: int = 5) -> list[dict[str, str]]:
        """按需读取最近 n 轮对话，不全量塞入上下文。"""
        return self.history[-n:]

    def reset(self) -> None:
        self.slots.clear()
        self.history.clear()
        self.turn = 0


class LongTermMemory:
    """跨会话长期记忆：用户授权后保存偏好到本地 JSON，线程安全。

    对应课程笔记中的"长期记忆"层：跨 session 的记忆。
    仅在用户主动勾选/确认后保存，符合隐私要求。
    """

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def get(self, user_id: str) -> dict[str, Any]:
        with self.lock:
            return dict(self._read().get(user_id, {}))

    def save(self, user_id: str, preferences: dict[str, Any]) -> None:
        with self.lock:
            data = self._read()
            data[user_id] = preferences
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
