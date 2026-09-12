import json
import urllib.request
import time

API_KEY = ""
BASE_URL = "https://api.dify.ai/v1"

test_cases = [
    (1, "推荐个75寸电视，预算6000，放客厅", "product"),
    (2, "Mini LED和OLED有什么区别？", "product"),
    (3, "TCL 75Q10G Pro和海信75E8K哪个好？", "product"),
    (4, "75寸电视观看距离2.8米合适吗？", "product"),
    (5, "2000nits亮度是什么概念？", "product"),
    (6, "打PS5买什么电视好？", "product"),
    (7, "量子点和OLED哪个色彩好？", "product"),
    (8, "索尼75X90L分区数才96，是不是不如TCL？", "product"),
    (9, "75Q10G Pro现在多少钱？", "pricing"),
    (10, "国补能减多少？", "pricing"),
    (11, "以旧换新怎么估价？", "pricing"),
    (12, "PLUS会员买电视有什么优惠？", "pricing"),
    (13, "挂装多少钱？", "fulfillment"),
    (14, "75寸电梯能进吗？包装多大？", "fulfillment"),
    (15, "下单后多久能送到？", "fulfillment"),
    (16, "送装一体是什么意思？", "fulfillment"),
    (17, "电视保修多久？", "aftersales"),
    (18, "我要退货", "aftersales"),
    (19, "你们这什么垃圾服务！", "aftersales"),
    (20, "推荐个电视", "unclear"),
    (21, "今天天气怎么样？", "other"),
    (22, "你真笨", "other"),
]

multi_turn = [
    (23, "TCL 75Q10G Pro怎么样？", "product"),
    (24, "这款挂装多少钱？", "fulfillment"),
    (25, "那下单吧", "other"),
]

def send_query(query, conversation_id="", user="eval-v11"):
    body = json.dumps({
        "inputs": {},
        "query": query,
        "response_mode": "blocking",
        "conversation_id": conversation_id,
        "user": user
    }).encode("utf-8")
    
    req = urllib.request.Request(
        f"{BASE_URL}/chat-messages",
        data=body,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        },
        method="POST"
    )
    
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))

results = []
total_tokens = 0

print("=" * 60)
print("Running V1.1 evaluation (25 cases)")
print("=" * 60)

for tid, query, expected in test_cases:
    print(f"\n[{tid}/25] {query}")
    try:
        r = send_query(query)
        answer = r.get("answer", "")
        tokens = r.get("metadata", {}).get("usage", {}).get("total_tokens", 0)
        total_tokens += tokens
        results.append({
            "id": tid, "query": query, "expectedIntent": expected,
            "answer": answer, "tokens": tokens, "error": ""
        })
        preview = answer.replace("\n", " ")[:150]
        print(f"  OK ({tokens} tok): {preview}")
    except Exception as e:
        results.append({
            "id": tid, "query": query, "expectedIntent": expected,
            "answer": "", "tokens": 0, "error": str(e)
        })
        print(f"  ERROR: {e}")
    time.sleep(1)

print("\n" + "=" * 60)
print("Running multi-turn tests (23-25)")
print("=" * 60)

mt_conv_id = ""
for tid, query, expected in multi_turn:
    print(f"\n[{tid}/25] {query}")
    try:
        r = send_query(query, conversation_id=mt_conv_id, user="eval-v11-mt")
        mt_conv_id = r.get("conversation_id", "")
        answer = r.get("answer", "")
        tokens = r.get("metadata", {}).get("usage", {}).get("total_tokens", 0)
        total_tokens += tokens
        results.append({
            "id": tid, "query": query, "expectedIntent": expected,
            "answer": answer, "tokens": tokens, "error": ""
        })
        preview = answer.replace("\n", " ")[:150]
        print(f"  OK ({tokens} tok): {preview}")
    except Exception as e:
        results.append({
            "id": tid, "query": query, "expectedIntent": expected,
            "answer": "", "tokens": 0, "error": str(e)
        })
        print(f"  ERROR: {e}")
    time.sleep(1)

# Save JSON
with open(r"D:\豆包内容生成\京东项目\eval-results-v1.1.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# Save Markdown
md = f"# 评测结果 V1.1\n\n总测试数: {len(results)}\n总Token: {total_tokens}\n平均Token/条: {round(total_tokens/len(results))}\n\n---\n\n"
for r in results:
    md += f"## Test {r['id']}: {r['query']}\n"
    md += f"- 期望意图: {r['expectedIntent']}\n"
    if r['error']:
        md += f"- **ERROR**: {r['error']}\n\n---\n\n"
    else:
        md += f"- Tokens: {r['tokens']}\n\n{r['answer']}\n\n---\n\n"

with open(r"D:\豆包内容生成\京东项目\eval-results-v1.1.md", "w", encoding="utf-8") as f:
    f.write(md)

print("\n" + "=" * 60)
print(f"DONE! Total: {len(results)}, Tokens: {total_tokens}")
print("Results saved to eval-results-v1.1.json and .md")
