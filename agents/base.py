"""Agent 基类：统一接口、执行轨迹记录、节点 PRD 元数据。

每个 Worker Agent 必须实现 run() 方法，返回 AgentResult。
节点 PRD 六要素（来自课程笔记）通过类属性声明，作为 AI PM 产出物。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    """Agent 执行结果。"""

    agent_name: str
    success: bool
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, str]] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str = ""


@dataclass
class NodePRD:
    """节点 PRD 六要素（课程笔记：AI PM 核心产出）。

    节点名称 / 输入字段 / 输出格式 / 权重规则 / 异常处理 / 枚举值
    """

    name: str
    input_fields: list[dict[str, str]]  # [{name, type, required, source}]
    output_format: str
    weight_rules: str
    exception_handling: str
    enum_values: dict[str, list[str]] = field(default_factory=dict)
    description: str = ""


class BaseAgent:
    """所有 Agent 的基类。"""

    name: str = "base"
    description: str = ""
    prd: NodePRD | None = None

    def __init__(self, kb=None, llm=None, memory=None):
        self.kb = kb
        self.llm = llm
        self.memory = memory

    def _trace(self, kind: str, name: str, status: str, detail: str) -> dict[str, str]:
        return {"kind": kind, "name": name, "status": status, "detail": detail}

    def run(self, message: str, slots: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        """执行 Agent 逻辑，子类必须实现。"""
        raise NotImplementedError
