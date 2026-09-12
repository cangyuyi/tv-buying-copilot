"""自研 RAG 检索 + 结构化商品筛选。

检索算法：中文二元 gram + 拉丁词元的 token overlap 评分，零依赖。
商品筛选：预算/尺寸/刷新率/库存硬约束 + 用途匹配/尺寸/价格/亮度加权打分。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class KnowledgeBase:
    """知识库：文档检索 + 商品搜索 + 尺寸推荐。"""

    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.products: list[dict[str, Any]] = data.get("products", [])
        self.documents: list[dict[str, str]] = data.get("documents", [])
        self.promotions: list[dict[str, Any]] = data.get("promotions", [])
        self.fulfillment: list[dict[str, Any]] = data.get("fulfillment", [])
        self.aftersales: list[dict[str, Any]] = data.get("aftersales", [])
        self.disclaimer: str = data.get("disclaimer", "")

    # ── RAG 检索 ──────────────────────────────────────────

    @staticmethod
    def _tokens(text: str) -> set[str]:
        """中文二元 gram + 拉丁词元，构建检索 token 集合。"""
        normalized = re.sub(r"\s+", "", text.lower())
        chinese = {normalized[i : i + 2] for i in range(max(0, len(normalized) - 1))}
        latin = set(re.findall(r"[a-z0-9.]+", normalized))
        return chinese | latin

    def retrieve(self, query: str, limit: int = 3) -> list[dict[str, str]]:
        """按 token overlap 评分检索相关文档，无命中时返回兜底文档。"""
        query_tokens = self._tokens(query)
        scored: list[tuple[int, dict[str, str]]] = []
        for doc in self.documents:
            score = len(query_tokens & self._tokens(doc.get("title", "") + doc.get("content", "")))
            scored.append((score, doc))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        results = [doc for score, doc in scored[:limit] if score > 0]
        return results or ([self.documents[-1]] if self.documents else [])

    def retrieve_promotions(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """检索促销规则库。"""
        query_tokens = self._tokens(query)
        scored = []
        for promo in self.promotions:
            text = promo.get("name", "") + promo.get("description", "") + " ".join(promo.get("tags", []))
            score = len(query_tokens & self._tokens(text))
            scored.append((score, promo))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [p for s, p in scored[:limit] if s > 0]

    def retrieve_fulfillment(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """检索履约服务库。"""
        query_tokens = self._tokens(query)
        scored = []
        for item in self.fulfillment:
            text = item.get("name", "") + item.get("description", "")
            score = len(query_tokens & self._tokens(text))
            scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [f for s, f in scored[:limit] if s > 0]

    def retrieve_aftersales(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """检索售后规则库。"""
        query_tokens = self._tokens(query)
        scored = []
        for item in self.aftersales:
            text = item.get("name", "") + item.get("description", "")
            score = len(query_tokens & self._tokens(text))
            scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [a for s, a in scored[:limit] if s > 0]

    # ── 商品筛选 ──────────────────────────────────────────

    @staticmethod
    def target_size(slots: dict[str, Any]) -> int | None:
        """根据观看距离推荐目标尺寸。"""
        if slots.get("size"):
            return int(slots["size"])
        distance = slots.get("distance")
        if distance is None:
            return None
        if distance <= 2.0:
            return 43
        if distance <= 2.8:
            return 55
        if distance <= 3.5:
            return 65
        return 75

    def search_products(self, slots: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
        """结构化商品筛选：硬约束过滤 + 加权打分排序。

        硬约束：库存、预算、尺寸偏差≤10、刷新率（游戏场景≥120）
        打分：用途匹配×3 + 尺寸匹配×2 + 价格贴近预算 + 亮度（明亮客厅）
        """
        budget = slots.get("budget")
        target = self.target_size(slots)
        gaming = "游戏" in slots.get("use_cases", [])
        min_refresh = slots.get("min_refresh", 120 if gaming else 0)

        candidates: list[tuple[float, dict[str, Any]]] = []
        for product in self.products:
            # 硬约束
            if not product.get("stock", True):
                continue
            if budget and product["price"] > budget:
                continue
            if target and abs(product["size"] - target) > 10:
                continue
            if min_refresh and product.get("refresh_rate", 0) < min_refresh:
                continue

            # 加权打分
            use_overlap = len(set(slots.get("use_cases", [])) & set(product.get("use_cases", [])))
            size_score = 2 if target and product["size"] == target else 1 if target else 0
            budget_score = (product["price"] / budget) if budget else 0
            brightness_score = product.get("brightness_nits", 0) / 1000 if "明亮客厅" in slots.get("use_cases", []) else 0
            score = use_overlap * 3 + size_score * 2 + budget_score + brightness_score
            candidates.append((score, product))

        candidates.sort(key=lambda pair: (pair[0], pair[1]["price"]), reverse=True)
        return [dict(p) for _, p in candidates[:limit]]
