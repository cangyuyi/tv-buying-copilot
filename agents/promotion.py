"""比价优惠 Agent：检索促销规则库，计算优惠叠加，输出到手价。

节点 PRD（六要素）：
- 输入：用户消息 + 商品信息（可选）
- 输出：可用促销列表 + 叠加计算 + 到手价估算
- 权重规则：按优惠力度从大到小排序，国补>以旧换新>满减>优惠券
- 异常处理：无匹配促销时返回基础价，提示关注活动
- 枚举值：promotion_type ∈ {国补,以旧换新,满减,优惠券,限时折扣}
"""

from __future__ import annotations

from typing import Any

from .base import BaseAgent, AgentResult, NodePRD


class PromotionAgent(BaseAgent):
    """比价优惠 Agent：检索促销规则，计算叠加优惠。"""

    name = "promotion_agent"
    description = "检索促销规则库，计算优惠叠加和到手价"

    prd = NodePRD(
        name="比价优惠 Agent / Promotion Agent",
        description="检索促销规则库，计算可叠加优惠和到手价",
        input_fields=[
            {"name": "message", "type": "string", "required": "是", "source": "用户输入"},
            {"name": "product_price", "type": "int", "required": "否", "source": "Product Agent 传入"},
            {"name": "product_name", "type": "string", "required": "否", "source": "Product Agent 传入"},
        ],
        output_format='{"promotions": [...], "final_price": int, "savings": int, "explanation": str}',
        weight_rules="按优惠力度排序：国补 > 以旧换新 > 满减 > 优惠券 > 限时折扣",
        exception_handling="无匹配促销时返回基础价，提示关注近期活动；价格信息缺失时只列促销规则",
        enum_values={
            "promotion_type": ["国补", "以旧换新", "满减", "优惠券", "限时折扣", "价保"],
        },
    )

    # 优惠叠加规则：国补和以旧换新可叠加，满减和优惠券可叠加，国补不与满减叠加
    STACK_RULES = {
        "国补": ["以旧换新", "优惠券"],
        "以旧换新": ["国补", "满减", "优惠券"],
        "满减": ["以旧换新", "优惠券", "限时折扣"],
        "优惠券": ["国补", "以旧换新", "满减", "限时折扣"],
        "限时折扣": ["满减", "优惠券"],
        "价保": [],
    }

    def run(self, message: str, slots: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        trace: list[dict[str, str]] = []

        # 1. 检索促销规则
        promotions = self.kb.retrieve_promotions(message, limit=5)
        trace.append(self._trace("rag", "promotion_retrieval", "ok", f"检索到 {len(promotions)} 条促销规则"))

        if not promotions:
            return AgentResult(
                agent_name=self.name,
                success=True,
                content="当前未检索到匹配的促销活动，建议关注页面活动信息或咨询客服。",
                data={"promotions": [], "final_price": None},
                trace=trace,
            )

        # 2. 计算优惠叠加（如果有商品价格）
        base_price = context.get("product_price") or slots.get("budget")
        final_price = None
        savings = 0
        if base_price:
            final_price, savings, applied = self._calculate_stack(promotions, base_price)
            trace.append(self._trace("calc", "discount_stack", "ok", f"叠加 {len(applied)} 项优惠，省¥{savings}"))
        else:
            applied = []

        # 3. 生成说明
        explanation = self._build_explanation(promotions, applied, base_price, final_price, savings)

        return AgentResult(
            agent_name=self.name,
            success=True,
            content=explanation,
            data={
                "promotions": promotions,
                "applied": applied,
                "final_price": final_price,
                "savings": savings,
            },
            trace=trace,
        )

    def _calculate_stack(self, promotions: list[dict], base_price: int) -> tuple[int, int, list[dict]]:
        """按叠加规则计算最优优惠组合。贪心算法：按优惠力度从大到小尝试叠加。"""
        sorted_promos = sorted(promotions, key=lambda p: p.get("discount_value", 0), reverse=True)
        applied: list[dict] = []
        current_price = base_price

        for promo in sorted_promos:
            ptype = promo.get("type", "")
            # 检查是否与已应用的促销可叠加
            can_stack = all(
                ptype in self.STACK_RULES.get(a.get("type", ""), [])
                for a in applied
            )
            if not can_stack:
                continue
            # 计算优惠
            discount = promo.get("discount_value", 0)
            if promo.get("discount_type") == "percent":
                saved = int(current_price * discount / 100)
            else:
                saved = discount
            # 满减门槛检查
            threshold = promo.get("threshold", 0)
            if threshold and current_price < threshold:
                continue
            current_price -= saved
            applied.append(promo)

        savings = base_price - current_price
        return max(current_price, 0), savings, applied

    def _build_explanation(self, promotions, applied, base_price, final_price, savings) -> str:
        lines = ["当前可用促销活动："]
        for p in promotions:
            lines.append(f"• {p.get('name','')}：{p.get('description','')}")
        if applied and base_price:
            lines.append(f"\n按 ¥{base_price} 计算，可叠加 {len(applied)} 项优惠：")
            for a in applied:
                lines.append(f"  - {a.get('name','')}")
            lines.append(f"预估到手价：¥{final_price}（省 ¥{savings}）")
            lines.append("\n注：实际优惠以结算页为准，部分活动需领券或满足条件。")
        return "\n".join(lines)
