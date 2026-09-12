"""Replanner：输出前的硬约束二次检查，防止幻觉和越权。

对应课程笔记中的"自我检查决策"：先产出 → 再自检 → 修正 → 再检查。
检查不通过时返回修正建议，由编排引擎决定重试或降级。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckResult:
    """约束检查结果。"""

    passed: bool
    reason: str = ""
    corrected_products: list[dict[str, Any]] = field(default_factory=list)
    action: str = "ok"  # ok / retry / fallback / handoff


class Replanner:
    """输出前二次检查：预算、刷新率、库存、引用、越权。"""

    # 高风险关键词：涉及交易操作或复杂售后，必须转人工
    OUT_OF_SCOPE_KEYWORDS = ("退款", "投诉", "维权", "纠纷", "修改订单", "申请发票", "退货", "换货")

    def check_handoff(self, message: str) -> CheckResult:
        """检查是否涉及越权请求。注意排除"已经处理完"等已结束上下文。"""
        # 先移除"已处理完/已解决"等表述，避免历史词误触发
        active = message
        for done in ("已经处理完", "已处理完", "已经解决", "已解决", "处理完了", "解决完了"):
            active = active.replace(done, "")
        if any(kw in active for kw in self.OUT_OF_SCOPE_KEYWORDS):
            return CheckResult(
                passed=False,
                reason="请求涉及交易操作或高风险售后，超出导购 Agent 权限。",
                action="handoff",
            )
        return CheckResult(passed=True, action="ok")

    def check_missing_slots(self, slots: dict[str, Any]) -> CheckResult:
        """检查推荐所需的硬约束是否齐全。"""
        missing: list[str] = []
        if not slots.get("budget"):
            missing.append("budget")
        if not slots.get("size") and not slots.get("distance"):
            missing.append("size_or_distance")
        if not slots.get("use_cases"):
            missing.append("use_case")
        if missing:
            return CheckResult(
                passed=False,
                reason=f"硬约束不足，缺少：{', '.join(missing)}",
                action="clarify",
            )
        return CheckResult(passed=True, action="ok")

    def check_products(self, products: list[dict[str, Any]], slots: dict[str, Any]) -> CheckResult:
        """检查候选商品是否满足硬约束，移除违规项。"""
        if not products:
            return CheckResult(
                passed=False,
                reason="无候选满足全部硬约束，拒绝编造推荐。",
                action="fallback",
            )

        budget = slots.get("budget")
        min_refresh = slots.get("min_refresh", 120 if "游戏" in slots.get("use_cases", []) else 0)
        target = None

        corrected: list[dict[str, Any]] = []
        violations: list[str] = []
        for p in products:
            if budget and p["price"] > budget:
                violations.append(f"{p['name']} 超预算 ¥{p['price']} > ¥{budget}")
                continue
            if min_refresh and p.get("refresh_rate", 0) < min_refresh:
                violations.append(f"{p['name']} 刷新率 {p.get('refresh_rate')}Hz < {min_refresh}Hz")
                continue
            if not p.get("stock", True):
                violations.append(f"{p['name']} 无库存")
                continue
            corrected.append(p)

        if not corrected:
            return CheckResult(
                passed=False,
                reason=f"所有候选均不满足硬约束：{'; '.join(violations)}",
                action="fallback",
            )

        if violations:
            return CheckResult(
                passed=True,
                reason=f"已移除违规候选：{'; '.join(violations)}",
                corrected_products=corrected,
                action="corrected",
            )

        return CheckResult(passed=True, reason="候选满足全部硬约束。", corrected_products=products, action="ok")

    def check_answer_citations(self, answer: str, citations: list[dict[str, str]]) -> CheckResult:
        """检查推荐回答是否包含引用标注，防止模型脱离证据自由发挥。"""
        if not citations:
            return CheckResult(passed=False, reason="无引用来源，回答可能脱离知识库。", action="retry")
        has_citation = any(f"[{c['id']}]" in answer for c in citations)
        if not has_citation:
            return CheckResult(passed=False, reason="回答未保留引用标注。", action="retry")
        return CheckResult(passed=True, reason="引用完整。")
