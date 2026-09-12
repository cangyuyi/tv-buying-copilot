"""Master Router：确定性意图分类，6 类路由。

用关键词+规则做确定性分类，不依赖 LLM，避免分类幻觉。

路由分类：
- product: 商品咨询（参数/推荐/对比）
- promotion: 价格优惠（促销/优惠券/以旧换新/国补）
- fulfillment: 履约安装（配送/安装/入户/挂装）
- aftersales: 售后退换（退货/换货/保修/投诉）→ 强制转人工
- clarify: 需求模糊（信息不足，需要追问）
- fallback: 其他闲聊（兜底）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .base import BaseAgent, AgentResult, NodePRD


@dataclass
class RouteResult:
    """路由结果。"""

    route: str
    target_agents: list[str]
    reason: str
    confidence: float = 1.0  # 确定性分类，置信度恒为 1.0


class MasterRouter(BaseAgent):
    """Master Agent：意图识别 + 槽位管理 + 路由分发。

    节点 PRD（六要素）：
    - 输入：用户原始消息 + 已提取槽位
    - 输出：route（6类之一）+ target_agents + reason
    - 权重规则：售后关键词优先级最高，其次优惠/履约，最后商品
    - 异常处理：无法分类时走 fallback，不强行匹配
    - 枚举值：route ∈ {product, promotion, fulfillment, aftersales, clarify, fallback}
    """

    name = "master_router"
    description = "确定性意图分类，将用户消息路由到对应 Worker Agent"

    prd = NodePRD(
        name="Master Router / 意图分类总控",
        description="确定性规则分类，不依赖 LLM，避免分类幻觉",
        input_fields=[
            {"name": "message", "type": "string", "required": "是", "source": "用户输入"},
            {"name": "slots", "type": "object", "required": "是", "source": "NeedParser 提取"},
        ],
        output_format='{"route": str, "target_agents": [str], "reason": str}',
        weight_rules="售后关键词优先级最高（强制转人工）> 优惠/履约 > 商品咨询 > 兜底",
        exception_handling="无法分类时走 fallback，不强行匹配；信息不足时标记 clarify",
        enum_values={
            "route": ["product", "promotion", "fulfillment", "aftersales", "clarify", "fallback"],
        },
    )

    # 关键词分类表（按优先级从高到低匹配）
    AFTERSALES_KEYWORDS = [
        "退货", "退款", "换货", "退换", "保修", "维修", "投诉", "维权", "纠纷",
        "修改订单", "取消订单", "申请发票", "发票", "售后", "质量问题", "坏了",
        "开不了机", "黑屏", "花屏",
    ]
    PROMOTION_KEYWORDS = [
        "优惠", "促销", "折扣", "满减", "优惠券", "券", "以旧换新", "国补", "政府补贴",
        "价格", "多少钱", "便宜", "降价", "价保", "保价", "到手价", "活动", "618", "双11",
    ]
    FULFILLMENT_KEYWORDS = [
        "配送", "送货", "安装", "挂装", "壁挂", "入户", "电梯", "楼梯", "上门",
        "时效", "几天到", "什么时候到", "几天能", "送到", "到货", "运费", "包邮", "送装", "安装费",
    ]
    PRODUCT_KEYWORDS = [
        "推荐", "选", "买", "哪款", "哪个", "对比", "区别", "参数", "配置",
        "尺寸", "寸", "画质", "刷新率", "面板", "亮度", "音响", "系统",
        "电视", "海信", "tcl", "小米", "创维", "索尼", "三星", "lg",
        "游戏", "ps5", "xbox", "主机", "hz", "追剧", "电影", "观影",
        "哪个好", "租房", "过渡", "性价比",
    ]

    # 已处理完的表述（排除历史词误触发）
    DONE_PATTERNS = [
        r"(?:已经|已)?(?:处理完|解决|搞定|弄好)(?:了|过)?",
    ]

    def classify(self, message: str, slots: dict[str, Any]) -> RouteResult:
        """确定性分类，返回路由结果。"""
        lower = message.lower()

        # 预处理：移除"已处理完"等表述，避免售后历史词误触发
        active = lower
        for pattern in self.DONE_PATTERNS:
            active = re.sub(pattern, "", active)

        # 优先级 1：售后（强制转人工）
        if any(kw in active for kw in self.AFTERSALES_KEYWORDS):
            return RouteResult(
                route="aftersales",
                target_agents=["aftersales"],
                reason="检测到售后/交易关键词，超出导购权限，转人工。",
            )

        # 优先级 2：价格优惠
        if any(kw in active for kw in self.PROMOTION_KEYWORDS):
            return RouteResult(
                route="promotion",
                target_agents=["promotion"],
                reason="检测到价格/优惠关键词，路由到比价优惠 Agent。",
            )

        # 优先级 3：履约安装
        if any(kw in active for kw in self.FULFILLMENT_KEYWORDS):
            return RouteResult(
                route="fulfillment",
                target_agents=["fulfillment"],
                reason="检测到配送/安装关键词，路由到履约服务 Agent。",
            )

        # 优先级 4：商品咨询
        if any(kw in active for kw in self.PRODUCT_KEYWORDS):
            # 对比意图（哪个好/对比/区别）直接走product，不强制硬约束齐全
            is_comparison = any(kw in active for kw in ["哪个好", "对比", "区别", "哪个更好", "怎么选"])
            if is_comparison:
                return RouteResult(
                    route="product",
                    target_agents=["product"],
                    reason="检测到对比意图，路由到商品参数 Agent。",
                )
            # 商品咨询需要硬约束齐全，否则先澄清
            # 例外1：对比意图直接走product
            # 例外2：有预算的疑问句（能买到吗/有没有）直接走product
            # 例外3：明确高端意向（最好的/最高端）有预算时直接推荐
            is_feasibility = slots.get("budget") and any(kw in active for kw in ["能买到", "有没有", "可以买", "能买"])
            is_high_end = slots.get("budget") and any(kw in active for kw in ["最好", "最高端", "最贵", "旗舰"])
            need_clarify = not is_feasibility and not is_high_end and (
                not slots.get("budget")
                or (not slots.get("size") and not slots.get("distance"))
                or not slots.get("use_cases")
            )
            if need_clarify:
                return RouteResult(
                    route="clarify",
                    target_agents=["clarify"],
                    reason="商品咨询意图，但硬约束不足，先澄清需求。",
                )
            return RouteResult(
                route="product",
                target_agents=["product"],
                reason="检测到商品咨询关键词，硬约束齐全，路由到商品参数 Agent。",
            )

        # 优先级 5：非相关内容检测（防止历史槽位导致误路由）
        tv_related = any(kw in lower for kw in [
            "电视", "推荐", "买", "选", "哪款", "哪个好", "尺寸", "画质", "参数", "配置",
            "优惠", "价格", "多少钱", "配送", "安装", "售后", "退货", "换货",
            "ps5", "xbox", "游戏", "hz", "刷新率", "mini led", "oled", "面板",
            "寸", "英寸", "预算", "观影", "追剧", "看电影", "租房", "过渡",
            "送到", "到货", "几天能", "什么时候到",
        ])
        if not tv_related:
            return RouteResult(
                route="fallback",
                target_agents=[],
                reason="用户消息与电视导购无关，走兜底回复。",
            )

        # 优先级 6：有槽位但无明确关键词 → 按已有槽位推荐
        if slots.get("budget") and (slots.get("size") or slots.get("distance")) and slots.get("use_cases"):
            return RouteResult(
                route="product",
                target_agents=["product"],
                reason="用户已提供完整约束，默认进入商品推荐。",
            )

        # 优先级 6：信息不足 → 澄清
        if any(kw in lower for kw in ["买电视", "选电视", "推荐电视", "想买个"]):
            return RouteResult(
                route="clarify",
                target_agents=["clarify"],
                reason="有购买意向但信息不足，进入澄清流程。",
            )

        # 兜底
        return RouteResult(
            route="fallback",
            target_agents=[],
            reason="无法识别意图，走兜底回复。",
        )

    def run(self, message: str, slots: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        route = self.classify(message, slots)
        trace = [self._trace("router", "intent_classification", "ok", route.reason)]
        return AgentResult(
            agent_name=self.name,
            success=True,
            content=route.reason,
            data={"route": route.route, "target_agents": route.target_agents},
            trace=trace,
        )
