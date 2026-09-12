"""履约服务 Agent：检索配送/安装/售后政策，回答履约相关问题。

节点 PRD（六要素）：
- 输入：用户消息 + 地区信息（可选）
- 输出：履约政策说明 + 时效预估 + 费用说明
- 权重规则：配送时效 > 安装方式 > 费用 > 售后政策
- 异常处理：地区信息缺失时给出通用政策，提示提供地址获取精确时效
- 枚举值：install_type ∈ {座装,挂装,移动支架,免费安装,收费安装}
"""

from __future__ import annotations

from typing import Any

from .base import BaseAgent, AgentResult, NodePRD


class FulfillmentAgent(BaseAgent):
    """履约服务 Agent：配送、安装、入户政策查询。"""

    name = "fulfillment_agent"
    description = "检索履约服务库，回答配送/安装/入户/费用问题"

    prd = NodePRD(
        name="履约服务 Agent / Fulfillment Agent",
        description="检索配送/安装/售后政策，回答履约相关问题",
        input_fields=[
            {"name": "message", "type": "string", "required": "是", "source": "用户输入"},
            {"name": "region", "type": "string", "required": "否", "source": "用户提供或默认全国"},
            {"name": "product_size", "type": "int", "required": "否", "source": "Product Agent 传入（影响安装费）"},
        ],
        output_format='{"policies": [...], "eta": str, "cost": str, "explanation": str}',
        weight_rules="配送时效 > 安装方式 > 费用说明 > 售后政策",
        exception_handling="地区缺失时给出通用政策；特殊地区（偏远/无电梯）提示可能加收费用",
        enum_values={
            "install_type": ["座装", "挂装", "移动支架", "免费安装", "收费安装"],
            "delivery_type": ["送货上门", "送货入户", "快递配送", "自提"],
        },
    )

    def run(self, message: str, slots: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        trace: list[dict[str, str]] = []

        # 检索履约政策
        policies = self.kb.retrieve_fulfillment(message, limit=4)
        trace.append(self._trace("rag", "fulfillment_retrieval", "ok", f"检索到 {len(policies)} 条履约政策"))

        if not policies:
            # 兜底：返回通用配送安装政策
            general = [
                {"name": "配送时效", "description": "全国大部分地区48小时内发货，江浙沪皖次日达，偏远地区3-5天。大件商品送货上门。"},
                {"name": "安装服务", "description": "55寸及以上含免费基础座装，挂装需额外支付支架费（55寸99元，65寸149元，75寸199元）。"},
            ]
            trace.append(self._trace("rag", "fulfillment_fallback", "warning", "未检索到精确匹配，返回通用政策"))
            explanation = self._build_explanation(general, message)
            return AgentResult(
                agent_name=self.name,
                success=True,
                content=explanation,
                data={"policies": general, "fallback": True},
                trace=trace,
            )

        explanation = self._build_explanation(policies, message)
        return AgentResult(
            agent_name=self.name,
            success=True,
            content=explanation,
            data={"policies": policies},
            trace=trace,
        )

    def _build_explanation(self, policies: list[dict], message: str) -> str:
        lines = ["关于配送安装："]
        for p in policies:
            lines.append(f"• {p.get('name','')}：{p.get('description','')}")
        # 检测是否需要提示地址
        if any(kw in message for kw in ["几天", "时效", "什么时候到", "多久"]):
            lines.append("\n提示：提供收货地址可查询更精确的配送时效，偏远地区可能延长1-2天。")
        if any(kw in message for kw in ["安装费", "多少钱", "收费"]):
            lines.append("\n注：55寸及以上部分型号含免费基础安装，挂装支架可能另行收费，以安装师傅报价为准。")
        return "\n".join(lines)
