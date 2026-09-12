"""端到端冒烟测试：每个用例独立 session。"""
import os, sys, uuid
os.environ["AI_API_KEY"] = ""
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from app import AgentOrchestrator

o = AgentOrchestrator()

test_cases = [
    ("商品推荐-完整约束", "预算4000，客厅2.5米，追剧看电影，推荐个电视", "product"),
    ("需求澄清-信息不足", "推荐个电视", "clarify"),
    ("优惠查询", "现在有什么优惠活动？", "promotion"),
    ("履约查询", "配送和安装怎么收费？", "fulfillment"),
    ("售后转人工", "我要退货", "handoff"),
    ("游戏电视-中文数字", "三千预算，玩PS5，要120Hz以上", "product"),
    ("兜底-闲聊", "今天天气怎么样", "fallback"),
    ("否定句处理", "不玩游戏，只追剧，55寸，3000以内", "product"),
]

print("=" * 70)
passed = 0
for name, msg, expected_route in test_cases:
    sid = str(uuid.uuid4())
    result = o.handle(msg, sid)
    route = result.get("route")
    answer = result.get("answer", "")[:120]
    print(f"\n【{name}】")
    print(f"  路由: {route}")
    print(f"  槽位: {result.get('slots')}")
    print(f"  回答: {answer}...")
    print(f"  轨迹: {len(result.get('trace', []))}步")
    assert route == expected_route, f"{name}: expected {expected_route}, got {route}"
    assert result.get("trace"), f"{name}: missing execution trace"
    if expected_route == "handoff":
        assert "人工" in result.get("answer", "") or "转接" in result.get("answer", "")
    passed += 1

print(f"\n{'='*70}")
print(f"全部 {passed} 个用例通过：路由、执行轨迹和人工兜底均符合预期")
