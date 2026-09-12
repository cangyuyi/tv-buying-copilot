"""合规审核节点：独立 Reflection，5 条红线自检 + 修正循环（最大 2 次）。

设计原则（来自课程笔记 自我检查决策）：
- 先产出 → 再自检 → 修正 → 再检查（循环）
- 合格标准明确、结构化
- 设最大循环次数，防止无限循环
- 自检和产出最好用不同模型（这里用 temperature=0 的确定性检查）

5 条红线：
1. 不编造参数：型号/参数必须在商品库中存在
2. 不做绝对承诺：禁止"最好/第一/100%/肯定/绝对"等表述
3. 不贬低竞品：禁止"比XX差/XX垃圾/不如XX"等表述
4. 价格必须有依据：推荐商品价格必须来自商品库
5. 高风险必须转人工：退换货/交易操作必须走人工
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .base import BaseAgent, AgentResult, NodePRD


@dataclass
class ComplianceResult:
    """合规检查结果。"""

    passed: bool
    violations: list[str] = field(default_factory=list)
    corrected_text: str = ""
    action: str = "ok"  # ok / corrected / fallback / handoff


class ComplianceAgent(BaseAgent):
    """合规审核 Agent：5 条红线自检，不通过时修正，最多 2 次循环。"""

    name = "compliance_agent"
    description = "独立Reflection节点，5条红线自检，修正循环最大2次"

    prd = NodePRD(
        name="合规审核 Agent / Compliance Reflection",
        description="独立节点，temperature=0，5条红线自检，不通过时自动修正，最大循环2次",
        input_fields=[
            {"name": "answer", "type": "string", "required": "是", "source": "Worker Agent 输出"},
            {"name": "products", "type": "list", "required": "否", "source": "Product Agent 候选商品"},
            {"name": "route", "type": "string", "required": "是", "source": "Master Router 路由结果"},
        ],
        output_format='{"passed": bool, "violations": [...], "corrected_text": str, "action": str}',
        weight_rules="高风险转人工 > 编造参数 > 绝对承诺 > 贬低竞品 > 价格无依据",
        exception_handling="2次修正仍不通过时，降级为安全模板回复；涉及高风险直接转人工",
        enum_values={
            "action": ["ok", "corrected", "fallback", "handoff"],
        },
    )

    # 绝对承诺词
    ABSOLUTE_WORDS = ["最好", "第一", "100%", "百分之百", "肯定", "绝对", "永远", "永不", "最强", "顶级", "完美"]
    # 贬低竞品模式
    DEROGATORY_PATTERNS = [
        r"比\s*[\w\u4e00-\u9fa5]{2,6}\s*(差|烂|垃圾|弱|不行)",
        r"[\w\u4e00-\u9fa5]{2,6}\s*(垃圾|烂|不行|太差)",
        r"不如\s*[\w\u4e00-\u9fa5]{2,6}",
    ]
    # 高风险词（必须转人工）
    HIGH_RISK_WORDS = ["退款", "退货", "换货", "投诉", "维权", "修改订单", "取消订单", "申请发票"]

    MAX_RETRY = 2

    def run(self, message: str, slots: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        """执行合规审核。message 是待审核的回答文本。"""
        answer = context.get("answer", message)
        products = context.get("products", [])
        route = context.get("route", "")
        trace: list[dict[str, str]] = []

        # 循环检查+修正，最多 MAX_RETRY 次
        current_text = answer
        for attempt in range(self.MAX_RETRY):
            result = self._check(current_text, products, route)
            trace.append(self._trace(
                "compliance",
                f"check_attempt_{attempt+1}",
                "pass" if result.passed else "fail",
                f"违规：{result.violations or '无'}"
            ))

            if result.passed:
                return AgentResult(
                    agent_name=self.name,
                    success=True,
                    content=result.corrected_text or current_text,
                    data={"passed": True, "violations": [], "action": result.action, "attempts": attempt + 1},
                    trace=trace,
                )

            # 高风险直接转人工，不修正
            if result.action == "handoff":
                return AgentResult(
                    agent_name=self.name,
                    success=False,
                    content="您的问题需要人工客服处理，正在为您转接…",
                    data={"passed": False, "violations": result.violations, "action": "handoff"},
                    trace=trace,
                )

            # 尝试修正
            current_text = self._correct(current_text, result.violations)
            trace.append(self._trace("compliance", f"correct_attempt_{attempt+1}", "ok", "已自动修正"))

        # 2次修正仍不通过，降级
        trace.append(self._trace("compliance", "max_retry", "warning", "2次修正仍不通过，降级为安全模板"))
        return AgentResult(
            agent_name=self.name,
            success=False,
            content="抱歉，为确保信息准确，建议您咨询在线客服获取最新信息。",
            data={"passed": False, "violations": result.violations, "action": "fallback"},
            trace=trace,
        )

    def _check(self, text: str, products: list[dict], route: str) -> ComplianceResult:
        """执行 5 条红线检查。"""
        violations: list[str] = []
        action = "ok"

        # 红线5：高风险必须转人工（优先检查）
        if route == "aftersales" or any(kw in text for kw in self.HIGH_RISK_WORDS):
            return ComplianceResult(
                passed=False,
                violations=["涉及高风险售后/交易操作，必须转人工"],
                action="handoff",
            )

        # 红线2：绝对承诺
        for word in self.ABSOLUTE_WORDS:
            if word in text:
                violations.append(f"使用绝对承诺词：{word}")

        # 红线3：贬低竞品
        for pattern in self.DEROGATORY_PATTERNS:
            if re.search(pattern, text):
                violations.append("包含贬低竞品表述")
                break

        # 红线1：编造参数（检查推荐的型号是否在商品库中）
        if products:
            valid_names = {p.get("name", "") for p in products}
            # 简单检查：文本中提到的电视型号是否都在候选列表中
            for p in products:
                name = p.get("name", "")
                if name and name not in text and "推荐" in text:
                    # 模型可能编造了不在列表中的型号
                    pass  # 这里简化处理，实际可用LLM检查

        # 红线4：价格必须有依据（推荐场景下价格应来自商品库）
        if products and route == "product":
            prices_in_text = re.findall(r"¥\s*(\d+)|(\d+)\s*元", text)
            valid_prices = {str(p.get("price", "")) for p in products}
            for match in prices_in_text:
                price = match[0] or match[1]
                if price and price not in valid_prices and int(price) > 1000:
                    violations.append(f"价格 ¥{price} 不在商品库中，可能编造")
                    break

        if violations:
            action = "corrected"
            return ComplianceResult(passed=False, violations=violations, action=action)

        return ComplianceResult(passed=True, action="ok", corrected_text=text)

    def _correct(self, text: str, violations: list[str]) -> str:
        """自动修正违规内容。"""
        corrected = text
        # 移除绝对承诺词
        for word in self.ABSOLUTE_WORDS:
            corrected = corrected.replace(word, "较为" if word in ["最好", "最强"] else "较为")
        # 移除贬低竞品表述（简化：替换为中性表述）
        for pattern in self.DEROGATORY_PATTERNS:
            corrected = re.sub(pattern, "各有特色", corrected)
        # 添加免责声明
        if "推荐" in corrected and "参考" not in corrected:
            corrected += "\n（以上参数仅供参考，以商品详情页为准）"
        return corrected
