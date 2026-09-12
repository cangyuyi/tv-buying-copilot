"""需求澄清 Agent：多轮追问补全槽位，每次只问一个关键问题。

设计原则（来自课程笔记 信息补全节点）：
- 给选项而非开放式问题，减少用户输入成本
- 每次只补一个最关键的缺失项
- 设置终止条件：补全到硬约束齐全就继续，最多补3次

节点 PRD（六要素）：
- 输入：用户消息 + 当前已提取槽位
- 输出：澄清问题（带选项）+ 缺失字段列表
- 权重规则：预算 > 尺寸/距离 > 用途 > 刷新率
- 异常处理：连续3轮仍无法补全时，给出通用推荐并提示可补充信息
- 枚举值：clarify_field ∈ {budget, size_or_distance, use_case, min_refresh}
"""

from __future__ import annotations

from typing import Any

from .base import BaseAgent, AgentResult, NodePRD


class ClarifyAgent(BaseAgent):
    """需求澄清 Agent：多轮追问补全硬约束槽位。"""

    name = "clarify_agent"
    description = "多轮追问补全预算/尺寸/用途等硬约束，每次只问一个问题"

    prd = NodePRD(
        name="需求澄清 Agent / Clarify Agent",
        description="多轮追问补全硬约束，每次只问一个最关键的缺失项，给选项减少输入成本",
        input_fields=[
            {"name": "message", "type": "string", "required": "是", "source": "用户输入"},
            {"name": "slots", "type": "object", "required": "是", "source": "短期记忆中的已提取槽位"},
            {"name": "clarify_count", "type": "int", "required": "是", "source": "编排引擎计数（最多3次）"},
        ],
        output_format='{"question": str, "options": [...], "missing_field": str}',
        weight_rules="预算 > 尺寸/距离 > 用途 > 刷新率（游戏场景）",
        exception_handling="连续3轮未补全时，给出基于常见场景的通用推荐，不再追问",
        enum_values={
            "missing_field": ["budget", "size_or_distance", "use_case", "min_refresh"],
        },
    )

    # 澄清问题模板（带选项）
    QUESTIONS = {
        "budget": {
            "question": "请问你的预算大概是多少？",
            "options": ["2000以内", "2000-4000", "4000-6000", "6000-8000", "8000以上"],
        },
        "size_or_distance": {
            "question": "观看距离大概多远？或者想要多大尺寸？",
            "options": ["2米以内（43寸）", "2-2.8米（55寸）", "2.8-3.5米（65寸）", "3.5米以上（75寸）"],
        },
        "use_case": {
            "question": "主要用来看什么？",
            "options": ["追剧看电影", "玩游戏（PS5/Xbox）", "看球赛体育", "给老人用", "租房过渡", "客厅多人看"],
        },
        "min_refresh": {
            "question": "玩游戏的话，对刷新率有要求吗？",
            "options": ["120Hz以上", "60Hz就行", "不太清楚"],
        },
    }

    # 优先级顺序
    PRIORITY = ["budget", "size_or_distance", "use_case", "min_refresh"]

    def run(self, message: str, slots: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        trace: list[dict[str, str]] = []

        # 1. 找出最关键的缺失项
        missing = self._find_missing(slots)
        trace.append(self._trace("analyze", "missing_slots", "ok" if missing else "complete", f"缺失：{missing or '无'}"))

        # 2. 检查澄清次数上限（终止条件：防重复）
        clarify_count = context.get("clarify_count", 0)
        if clarify_count >= 3:
            trace.append(self._trace("limit", "max_clarify_reached", "warning", "已达3次澄清上限"))
            return AgentResult(
                agent_name=self.name,
                success=True,
                content="我先按常见场景（4000预算、55寸、追剧看电影）给你推荐，你可以随时补充更精确的需求。",
                data={"question": "", "options": [], "missing_field": "", "force_recommend": True},
                trace=trace,
                needs_clarification=False,
            )

        if not missing:
            return AgentResult(
                agent_name=self.name,
                success=True,
                content="需求已齐全，可以开始推荐。",
                data={"question": "", "options": [], "missing_field": ""},
                trace=trace,
                needs_clarification=False,
            )

        # 3. 生成澄清问题
        q = self.QUESTIONS[missing]
        trace.append(self._trace("ask", f"clarify_{missing}", "ok", q["question"]))

        return AgentResult(
            agent_name=self.name,
            success=True,
            content=q["question"] + "\n" + " / ".join(q["options"]),
            data={
                "question": q["question"],
                "options": q["options"],
                "missing_field": missing,
            },
            trace=trace,
            needs_clarification=True,
            clarification_question=q["question"],
        )

    def _find_missing(self, slots: dict[str, Any]) -> str | None:
        """按优先级找出第一个缺失的硬约束。"""
        if not slots.get("budget"):
            return "budget"
        if not slots.get("size") and not slots.get("distance"):
            return "size_or_distance"
        if not slots.get("use_cases"):
            return "use_case"
        if "游戏" in slots.get("use_cases", []) and not slots.get("min_refresh"):
            return "min_refresh"
        return None
