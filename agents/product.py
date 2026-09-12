"""商品参数 Agent：RAG 检索商品库，结构化筛选 + 加权打分 + 推荐对比。

节点 PRD（六要素）：
- 输入：用户消息 + 已提取槽位（预算/尺寸/距离/刷新率/用途）
- 输出：推荐商品列表（JSON）+ 引用文档 + 推荐话术
- 权重规则：用途匹配×3 + 尺寸匹配×2 + 价格贴近预算 + 亮度（明亮客厅）
- 异常处理：无候选时返回空列表，由编排引擎降级
- 枚举值：use_cases ∈ {电影,游戏,体育,追剧,老人,租房,卧室,客厅,明亮客厅,多人观看}
"""

from __future__ import annotations

from typing import Any

from .base import BaseAgent, AgentResult, NodePRD


class ProductAgent(BaseAgent):
    """商品参数 Agent：基于硬约束筛选 + 加权打分推荐商品。"""

    name = "product_agent"
    description = "RAG检索商品库，结构化筛选+加权打分，输出推荐商品和参数对比"

    prd = NodePRD(
        name="商品参数 Agent / Product Agent",
        description="基于用户槽位做结构化商品筛选和加权打分，输出推荐列表",
        input_fields=[
            {"name": "message", "type": "string", "required": "是", "source": "用户输入"},
            {"name": "slots.budget", "type": "int", "required": "是", "source": "NeedParser"},
            {"name": "slots.size_or_distance", "type": "int/float", "required": "是", "source": "NeedParser"},
            {"name": "slots.use_cases", "type": "list", "required": "是", "source": "NeedParser"},
            {"name": "slots.min_refresh", "type": "int", "required": "否", "source": "NeedParser（游戏场景默认120）"},
        ],
        output_format='{"products": [...], "citations": [...], "recommendation": str}',
        weight_rules="用途匹配×3 + 尺寸匹配×2 + 价格贴近预算 + 亮度（明亮客厅场景）",
        exception_handling="无候选满足硬约束时返回空列表，由编排引擎降级为放宽约束建议",
        enum_values={
            "use_cases": ["电影", "游戏", "体育", "追剧", "老人", "租房", "卧室", "客厅", "明亮客厅", "多人观看"],
        },
    )

    def run(self, message: str, slots: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        trace: list[dict[str, str]] = []

        # 对比意图：直接从消息中提取型号并对比
        is_comparison = any(kw in message for kw in ["哪个好", "对比", "区别", "哪个更好", "怎么选"])
        if is_comparison:
            return self._handle_comparison(message, trace)

        # 1. RAG 检索相关知识文档
        docs = self.kb.retrieve(message, limit=3)
        trace.append(self._trace("rag", "knowledge_retrieval", "ok", f"检索到 {len(docs)} 篇文档"))

        # 2. 结构化商品筛选 + 加权打分
        products = self.kb.search_products(slots, limit=3)
        trace.append(self._trace("search", "product_filter", "ok", f"筛选出 {len(products)} 款候选"))

        if not products:
            return AgentResult(
                agent_name=self.name,
                success=False,
                content="无满足全部硬约束的候选商品。",
                data={"products": [], "citations": docs},
                trace=trace,
            )

        # 3. 生成推荐话术（LLM 或确定性模板）
        citations = [{"id": f"doc{i+1}", "title": d.get("title", ""), "content": d.get("content", "")} for i, d in enumerate(docs)]
        recommendation = self._build_recommendation(products, slots, citations)

        return AgentResult(
            agent_name=self.name,
            success=True,
            content=recommendation,
            data={"products": products, "citations": citations},
            trace=trace,
        )

    def _handle_comparison(self, message: str, trace: list) -> AgentResult:
        """处理对比意图：从消息中提取型号，返回参数对比。"""
        # 从商品库中匹配消息中提到的型号
        matched = []
        for product in self.kb.products:
            name = product["name"].lower()
            # 匹配品牌+型号关键词
            brand = product["brand"].lower()
            if brand in message.lower() and any(kw in message for kw in [product["name"].split()[1] if len(product["name"].split()) > 1 else ""]):
                matched.append(product)
            # 也匹配型号中的数字部分（如55Q10G, 55E8K）
            import re
            model_num = re.search(r"\d{2}[A-Z]\w+", product["name"])
            if model_num and model_num.group() in message.replace(" ", ""):
                if product not in matched:
                    matched.append(product)

        # 如果没匹配到，用品牌+尺寸模糊匹配
        if len(matched) < 2:
            for product in self.kb.products:
                if product["brand"].lower() in message.lower() and product not in matched:
                    matched.append(product)

        matched = matched[:2]
        trace.append(self._trace("search", "model_match", "ok", f"匹配到 {len(matched)} 款型号"))

        if len(matched) < 2:
            return AgentResult(
                agent_name=self.name,
                success=False,
                content="抱歉，未在商品库中找到您提到的两款型号，建议提供更完整的型号名称。",
                data={"products": matched},
                trace=trace,
            )

        # 生成对比表
        lines = ["两款电视参数对比："]
        for p in matched:
            lines.append(
                f"\n{p['name']}（¥{p['price']}）：\n"
                f"  面板：{p.get('panel_type','')} | 尺寸：{p['size']}寸\n"
                f"  刷新率：{p.get('refresh_rate',60)}Hz | 亮度：{p.get('brightness_nits','?')}nits\n"
                f"  色域：{p.get('color_gamut','')} | 亮点：{'、'.join(p.get('highlights',[]))}"
            )
        lines.append("\n选购建议：追求画质选Mini LED/ULED X，预算有限选LCD。以上参数仅供参考。")

        return AgentResult(
            agent_name=self.name,
            success=True,
            content="\n".join(lines),
            data={"products": matched, "comparison": True},
            trace=trace,
        )

    def _build_recommendation(self, products: list[dict], slots: dict, citations: list[dict]) -> str:
        """生成推荐话术。有 LLM 时用 LLM 润色，否则用确定性模板。"""
        if self.llm and self.llm.available:
            product_text = "\n".join(
                f"- {p['name']}：¥{p['price']}，{p['size']}寸，{p.get('panel_type','')}，"
                f"{p.get('refresh_rate',60)}Hz，亮度{p.get('brightness_nits','?')}nits，"
                f"适合{','.join(p.get('use_cases',[]))}"
                for p in products
            )
            citation_text = "\n".join(f"[{c['id']}] {c['title']}" for c in citations)
            system = (
                "你是专业电视导购。基于候选商品和知识库，给出简洁推荐。"
                "必须保留引用标注如[doc1]。每款商品突出1-2个核心卖点，最后给选购建议。"
                "不编造参数，不做绝对承诺。"
            )
            user = f"用户需求：预算¥{slots.get('budget')}，用途{','.join(slots.get('use_cases',[]))}\n候选商品：\n{product_text}\n知识库：\n{citation_text}"
            result = self.llm.complete(system, user, temperature=0.3)
            if result:
                return result

        # 确定性模板
        lines = [f"根据你的需求（预算¥{slots.get('budget')}，{','.join(slots.get('use_cases',[]))}），推荐："]
        for i, p in enumerate(products, 1):
            lines.append(
                f"{i}. {p['name']} — ¥{p['price']}，{p['size']}寸{p.get('panel_type','')}，"
                f"{p.get('refresh_rate',60)}Hz，亮度{p.get('brightness_nits','?')}nits"
            )
        if citations:
            ref_parts = [f"[{c['id']}] {c['title']}" for c in citations]
            lines.append(f"\n参考：{', '.join(ref_parts)}")
        return "\n".join(lines)
