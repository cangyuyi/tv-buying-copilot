"""自动化评测脚本：运行25条评测集，按正常/边界/异常分层统计通过率。

用法：python eval.py
输出：终端报告 + data/eval_report.json
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from app import AgentOrchestrator


def load_eval_cases(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_route(result: dict, expected: str) -> bool:
    return result.get("route") == expected


def check_slots(result: dict, expected: dict) -> tuple[bool, list[str]]:
    actual = result.get("slots") or {}
    issues = []
    for key, value in expected.items():
        if key not in actual:
            issues.append(f"缺少槽位 {key}")
        elif isinstance(value, list):
            if not set(value).issubset(set(actual.get(key, []))):
                issues.append(f"槽位 {key} 不匹配：期望包含 {value}，实际 {actual.get(key)}")
        elif actual[key] != value:
            issues.append(f"槽位 {key} 不匹配：期望 {value}，实际 {actual[key]}")
    return len(issues) == 0, issues


def check_behavior(result: dict, check_points: list[str]) -> tuple[bool, list[str]]:
    answer = result.get("answer", "")
    route = result.get("route", "")
    slots = result.get("slots") or {}
    passed = []
    failed = []

    checks = {
        "route_correct": True,  # 单独检查
        "slots_extracted": bool(slots),
        "budget_respected": _check_budget_respected(result),
        "has_citation": "[" in answer and "doc" in answer,
        "lists_promotions": "促销" in answer or "优惠" in answer or "满减" in answer,
        "mentions_delivery": "配送" in answer or "发货" in answer or "时效" in answer,
        "mentions_installation": "安装" in answer or "挂装" in answer or "座装" in answer,
        "asks_budget_first": "预算" in answer,
        "asks_missing_slots": "请问" in answer or "预算" in answer or "距离" in answer or "用途" in answer,
        "asks_size": "尺寸" in answer or "距离" in answer or "多大" in answer,
        "chinese_number_parsed": slots.get("budget") == 3000,
        "distance_parsed": slots.get("distance") is not None,
        "refresh_filtered": slots.get("min_refresh") is not None,
        "gaming_use_case": "游戏" in slots.get("use_cases", []),
        "elderly_use_case": "老人" in slots.get("use_cases", []),
        "bright_room_detected": "明亮客厅" in slots.get("use_cases", []),
        "high_brightness_preferred": "亮度" in answer or "nits" in answer.lower(),
        "comparison_intent": "对比" in answer or "区别" in answer or "vs" in answer.lower(),
        "mentions_both_models": "TCL" in answer and "海信" in answer,
        "mentions_trade_in": "以旧换新" in answer,
        "mentions_subsidy": "补贴" in answer or "15%" in answer or "2000" in answer,
        "mentions_delivery_time": "小时" in answer or "天" in answer or "次日达" in answer,
        "mentions_wall_mount": "挂装" in answer or "壁挂" in answer,
        "size_specific_price": "65寸" in answer or "149" in answer,
        "large_size": slots.get("size", 0) >= 70 or "75" in answer,
        "rental_use_case": "租房" in slots.get("use_cases", []),
        "low_budget": slots.get("budget", 99999) <= 1500,
        "negation_handled": "游戏" not in slots.get("use_cases", []) and "追剧" in slots.get("use_cases", []),
        "no_game_in_use_cases": "游戏" not in slots.get("use_cases", []),
        "colloquial_distance_parsed": slots.get("distance") == 2.5,
        "k_abbreviation_parsed": slots.get("budget") == 3000,
        "high_budget": slots.get("budget", 0) >= 8000,
        "no_hallucination": "索尼" not in answer or slots.get("budget", 0) >= 5999,
        "low_budget_handled": "建议" in answer or "推荐" in answer,
        "suggestion_when_no_match": "建议" in answer or "放宽" in answer or "提高" in answer,
        "asks_clarification": "请问" in answer or "预算" in answer or "距离" in answer,
        "handoff_triggered": route == "handoff" or "人工" in answer or "转接" in answer,
        "no_self_processing": "退款" not in answer or "人工" in answer,
        "fallback_response": route == "fallback",
        "guides_to_tv": "电视" in answer or "导购" in answer or "推荐" in answer,
    }

    for point in check_points:
        if point == "route_correct":
            continue
        if checks.get(point, False):
            passed.append(point)
        else:
            failed.append(point)

    return len(failed) == 0, failed


def _check_budget_respected(result: dict) -> bool:
    """检查推荐商品价格是否都在预算内。"""
    slots = result.get("slots") or {}
    budget = slots.get("budget")
    if not budget:
        return True
    answer = result.get("answer", "")
    # 简单检查：回答中提到的价格不超过预算
    import re
    prices = re.findall(r"¥\s*(\d+)|(\d+)\s*元", answer)
    for match in prices:
        price = int(match[0] or match[1])
        if price > budget and price > 1000:
            return False
    return True


def run_evaluation():
    base = Path(__file__).parent
    eval_data = load_eval_cases(base / "data" / "eval_cases.json")
    cases = eval_data["cases"]
    thresholds = eval_data["pass_thresholds"]

    orchestrator = AgentOrchestrator()

    results = {"normal": [], "boundary": [], "abnormal": []}
    print("=" * 70)
    print("电视选购 Copilot Multi-Agent 导购系统 — 自动化评测")
    print(f"LLM 可用：{orchestrator.llm.available}（演示模式下使用确定性模板）")
    print("=" * 70)

    for case in cases:
        sid = str(uuid.uuid4())
        result = orchestrator.handle(case["input"], sid)

        route_ok = check_route(result, case["expected_route"])
        slots_ok, slot_issues = check_slots(result, case.get("expected_slots", {}))
        behavior_ok, failed_checks = check_behavior(result, case.get("check_points", []))

        # 综合判定：路由正确 + 槽位正确 + 行为检查全部通过
        overall = route_ok and slots_ok and behavior_ok

        case_result = {
            "id": case["id"],
            "category": case["category"],
            "input": case["input"],
            "expected_route": case["expected_route"],
            "actual_route": result.get("route"),
            "route_ok": route_ok,
            "slots_ok": slots_ok,
            "slot_issues": slot_issues,
            "behavior_ok": behavior_ok,
            "failed_checks": failed_checks,
            "overall_pass": overall,
            "answer": result.get("answer", "")[:200],
        }
        results[case["category"]].append(case_result)

        status = "PASS" if overall else "FAIL"
        print(f"\n[{case['id']}] {status} — {case['input'][:40]}")
        print(f"  路由: 期望={case['expected_route']}, 实际={result.get('route')} {'OK' if route_ok else 'FAIL'}")
        if not slots_ok:
            print(f"  槽位问题: {slot_issues}")
        if not behavior_ok:
            print(f"  行为检查失败: {failed_checks}")

    # 统计
    print("\n" + "=" * 70)
    print("评测结果汇总")
    print("=" * 70)

    summary = {}
    for category in ["normal", "boundary", "abnormal"]:
        category_cases = results[category]
        total = len(category_cases)
        passed = sum(1 for c in category_cases if c["overall_pass"])
        rate = passed / total if total else 0
        threshold = thresholds[category]
        threshold_pass = rate >= threshold
        summary[category] = {
            "total": total,
            "passed": passed,
            "rate": rate,
            "threshold": threshold,
            "threshold_pass": threshold_pass,
        }
        label = {"normal": "正常Case", "boundary": "边界Case", "abnormal": "异常Case"}[category]
        print(f"\n{label}（达标线 {threshold*100:.0f}%）：")
        print(f"  通过 {passed}/{total} = {rate*100:.1f}%  {'✓ 达标' if threshold_pass else '✗ 未达标'}")

    total_all = sum(s["total"] for s in summary.values())
    passed_all = sum(s["passed"] for s in summary.values())
    print(f"\n总体：{passed_all}/{total_all} = {passed_all/total_all*100:.1f}%")

    # 保存报告
    report = {
        "version": eval_data.get("version", "1.0"),
        "llm_available": orchestrator.llm.available,
        "summary": summary,
        "details": {cat: results[cat] for cat in results},
    }
    report_path = base / "data" / "eval_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n详细报告已保存：{report_path}")

    return summary


if __name__ == "__main__":
    run_evaluation()
