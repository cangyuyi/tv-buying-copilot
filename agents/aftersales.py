"""售后客服 Agent：识别退换货/投诉/维修等请求，强制转人工。

设计原则（来自课程笔记 Human in the Loop）：
- 高风险场景（退换货/投诉/交易操作）必须人工介入
- Agent 只做信息收集和安抚，不做承诺和决策
- 转人工时给出明确的转接话术和等待提示

节点 PRD（六要素）：
- 输入：用户消息（含售后关键词）
- 输出：转人工话术 + 问题分类 + 需补充信息
- 权重规则：投诉/维权 > 退换货 > 维修咨询 > 发票
- 异常处理：始终转人工，不自行处理售后问题
- 枚举值：issue_type ∈ {退货,换货,退款,维修,投诉,发票,质量问题}
"""

from __future__ import annotations

from typing import Any

from .base import BaseAgent, AgentResult, NodePRD


class AftersalesAgent(BaseAgent):
    """售后客服 Agent：识别售后问题，强制转人工。"""

    name = "aftersales_agent"
    description = "识别退换货/投诉/维修请求，收集信息后强制转人工"

    prd = NodePRD(
        name="售后客服 Agent / Aftersales Agent",
        description="识别售后问题，收集关键信息后强制转人工，不做决策和承诺",
        input_fields=[
            {"name": "message", "type": "string", "required": "是", "source": "用户输入"},
            {"name": "order_id", "type": "string", "required": "否", "source": "用户提供"},
        ],
        output_format='{"issue_type": str, "handoff": true, "handoff_message": str, "missing_info": [...]}',
        weight_rules="投诉/维权 > 退换货 > 维修咨询 > 发票查询",
        exception_handling="始终转人工，不自行处理；缺少订单号时提示用户准备好订单号",
        enum_values={
            "issue_type": ["退货", "换货", "退款", "维修", "投诉", "发票", "质量问题", "其他"],
        },
    )

    ISSUE_KEYWORDS = {
        "退货": ["退货", "退了", "不要了"],
        "换货": ["换货", "换一台", "换个"],
        "退款": ["退款", "退钱", "赔钱"],
        "维修": ["维修", "修一下", "坏了", "开不了机", "黑屏", "花屏", "没声音"],
        "投诉": ["投诉", "维权", "纠纷", "差评", "12315"],
        "发票": ["发票", "开票", "补开发票"],
    }

    def run(self, message: str, slots: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        trace: list[dict[str, str]] = []

        # 1. 分类问题类型
        issue_type = self._classify_issue(message)
        trace.append(self._trace("classify", "issue_classification", "ok", f"问题类型：{issue_type}"))

        # 2. 检查是否有订单号
        import re
        order_match = re.search(r"(?:订单号|订单|单号)[：: ]?([A-Za-z0-9]{6,})", message)
        has_order = bool(order_match)
        missing = [] if has_order else ["订单号"]
        trace.append(self._trace("check", "order_id_check", "ok" if has_order else "missing", f"订单号：{'有' if has_order else '缺失'}"))

        # 3. 生成转人工话术
        handoff_message = self._build_handoff(issue_type, has_order)

        return AgentResult(
            agent_name=self.name,
            success=True,
            content=handoff_message,
            data={
                "issue_type": issue_type,
                "handoff": True,
                "missing_info": missing,
            },
            trace=trace,
        )

    def _classify_issue(self, message: str) -> str:
        for issue_type, keywords in self.ISSUE_KEYWORDS.items():
            if any(kw in message for kw in keywords):
                return issue_type
        return "其他"

    def _build_handoff(self, issue_type: str, has_order: bool) -> str:
        prefix = f"您的问题属于【{issue_type}】，需要人工客服为您处理。"
        order_hint = "" if has_order else "\n请准备好订单号，以便客服快速查询。"
        suffix = "\n正在为您转接人工客服，请稍候…（演示环境：实际部署时此处调用客服转接接口）"
        return prefix + order_hint + suffix
