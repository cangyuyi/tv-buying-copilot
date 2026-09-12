"""需求解析器：从自然语言中提取结构化槽位。

支持：
- 预算：阿拉伯数字、中文数字"三千"、缩写"3k"
- 尺寸：寸/英寸
- 距离：小数"2.5米"、口语"2米5"
- 刷新率：Hz
- 用途：电影/游戏/体育/追剧/老人/租房/卧室/客厅/明亮客厅/多人观看
- 否定句处理："不玩游戏只追剧" → 只保留追剧

零依赖，纯正则实现。
"""

from __future__ import annotations

import re
from typing import Any


class NeedParser:
    """从用户自然语言中提取购物需求槽位。"""

    USE_CASES: dict[str, list[str]] = {
        "电影": ["电影", "观影"],
        "游戏": ["游戏", "ps5", "xbox", "主机"],
        "体育": ["球赛", "体育", "足球", "篮球"],
        "追剧": ["追剧", "电视剧"],
        "老人": ["老人", "长辈", "父母"],
        "租房": ["租房", "出租屋"],
        "卧室": ["卧室"],
        "客厅": ["客厅"],
        "明亮客厅": ["白天很亮", "采光好", "明亮客厅", "很亮", "白天看", "光线强", "客厅亮", "向阳"],
        "多人观看": ["多人", "侧面看", "一家人", "家庭"],
    }

    # 中文数字映射（预算用）
    _CHINESE_DIGITS = "一二三四五六七八九"

    @classmethod
    def extract(cls, text: str) -> dict[str, Any]:
        """提取所有可识别的槽位。"""
        lower = text.lower()
        slots: dict[str, Any] = {}

        # 预算：多种格式
        cls._extract_budget(lower, slots)

        # 尺寸：寸/英寸
        size = re.search(r"(\d{2,3})\s*(?:寸|英寸)", lower)
        if size:
            slots["size"] = int(size.group(1))

        # 模糊尺寸描述：小一点/大一点
        if "size" not in slots:
            if any(kw in lower for kw in ["小一点", "小的", "小点", "小户型", "房间小"]):
                slots["size"] = 43
            elif any(kw in lower for kw in ["大一点", "大的", "大点", "大屏", "大尺寸"]):
                slots["size"] = 65

        # 距离：口语"2米5"优先于小数"2.5米"
        colloquial = re.search(r"(\d)\s*米\s*(\d)", lower)
        distance = re.search(r"(\d(?:\.\d+)?)\s*米", lower)
        if colloquial:
            slots["distance"] = float(f"{colloquial.group(1)}.{colloquial.group(2)}")
        elif distance:
            slots["distance"] = float(distance.group(1))

        # 刷新率
        refresh = re.search(r"(\d{2,3})\s*hz", lower)
        if refresh:
            slots["min_refresh"] = int(refresh.group(1))

        # 用途：带否定处理
        use_cases = cls._extract_use_cases(lower)
        if use_cases:
            slots["use_cases"] = use_cases

        return slots

    @classmethod
    def _extract_budget(cls, lower: str, slots: dict[str, Any]) -> None:
        # 格式1：预算3000 / 不超过5000 / 3000以内
        patterns = [
            r"(?:预算|不超过|最多|控制在|大概)\s*(\d{3,5})",
            r"(\d{3,5})\s*(?:元|块|以内|左右|以下|上下)",
        ]
        for pattern in patterns:
            match = re.search(pattern, lower)
            if match:
                slots["budget"] = int(match.group(1))
                return

        # 格式2：3k / 5K（注意：排除4K/8K等分辨率术语，除非前面有"预算"）
        if "budget" not in slots:
            compact = re.search(r"(\d+(?:\.\d+)?)\s*k(?![a-zA-Z0-9])", lower)
            if compact:
                value = int(float(compact.group(1)) * 1000)
                # 4K/8K 通常是分辨率，不是预算；除非前面有"预算"等词
                is_resolution = value in (4000, 8000) and "预算" not in lower and "价格" not in lower
                if not is_resolution:
                    slots["budget"] = value
                    return

        # 格式3：中文数字"三千"
        if "budget" not in slots:
            chinese = re.search(r"([一二三四五六七八九])千", lower)
            if chinese:
                idx = cls._CHINESE_DIGITS.index(chinese.group(1))
                slots["budget"] = (idx + 1) * 1000
                return

        # 格式4："X万"（如1万=10000）
        if "budget" not in slots:
            wan = re.search(r"(\d+(?:\.\d+)?)\s*万", lower)
            if wan:
                slots["budget"] = int(float(wan.group(1)) * 10000)

    @classmethod
    def _extract_use_cases(cls, lower: str) -> list[str]:
        use_cases: list[str] = []
        for canonical, keywords in cls.USE_CASES.items():
            matched = [kw for kw in keywords if kw in lower]
            if not matched:
                continue
            # 否定处理：检查匹配词前是否有否定词
            negated = any(
                re.search(rf"(?:不玩|不看|不要|无需|别玩|别看)\s*{re.escape(kw)}", lower)
                for kw in matched
            )
            if not negated:
                use_cases.append(canonical)
        return use_cases
