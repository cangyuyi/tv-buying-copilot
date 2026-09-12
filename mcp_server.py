"""MCP 工具服务：以 Model Context Protocol 暴露商品知识库和促销/履约/售后工具。

零第三方依赖，仅使用 Python 标准库实现 JSON-RPC 2.0 over stdio。
可被任意 MCP 兼容客户端（Claude Desktop、Cline、Dify 等）接入。

工具列表：
  - search_products   结构化商品筛选（预算/尺寸/距离/用途）
  - search_knowledge  RAG 文档检索（token overlap 评分）
  - get_promotions    促销规则检索与优惠叠加说明
  - get_fulfillment   配送/安装/入户服务查询
  - get_aftersales    售后政策查询（高风险强制转人工）

用法：
  python mcp_server.py                  # stdio 模式（MCP 客户端接入）
  python mcp_server.py --list-tools     # 命令行查看工具列表
  python mcp_server.py --call search_products '{"budget": 5000, "distance": 2.5}'
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# 复用核心知识库，不重复实现检索逻辑
sys.path.insert(0, str(Path(__file__).parent))
from core.rag import KnowledgeBase  # noqa: E402

KB_PATH = Path(__file__).parent / "data" / "knowledge.json"


def get_kb() -> KnowledgeBase:
    return KnowledgeBase(KB_PATH)


# ── 工具实现 ─────────────────────────────────────────────

def tool_search_products(args: dict[str, Any]) -> dict[str, Any]:
    """结构化商品筛选：硬约束过滤 + 加权打分。"""
    kb = get_kb()
    slots = {
        "budget": args.get("budget"),
        "size": args.get("size"),
        "distance": args.get("distance"),
        "use_cases": args.get("use_cases", []),
        "min_refresh": args.get("min_refresh", 0),
    }
    products = kb.search_products(slots, limit=args.get("limit", 3))
    return {
        "count": len(products),
        "products": [
            {
                "brand": p.get("brand"),
                "model": p.get("model"),
                "size": p.get("size"),
                "price": p.get("price"),
                "refresh_rate": p.get("refresh_rate"),
                "brightness_nits": p.get("brightness_nits"),
                "use_cases": p.get("use_cases", []),
                "stock": p.get("stock", True),
            }
            for p in products
        ],
        "note": "价格和库存为知识库静态数据，以商品详情页为准。",
    }


def tool_search_knowledge(args: dict[str, Any]) -> dict[str, Any]:
    """RAG 文档检索：中文二元 gram + 拉丁词元 token overlap 评分。"""
    kb = get_kb()
    query = args.get("query", "")
    limit = args.get("limit", 3)
    docs = kb.retrieve(query, limit=limit)
    return {
        "query": query,
        "results": [
            {"title": d.get("title", ""), "content": d.get("content", "")}
            for d in docs
        ],
    }


def tool_get_promotions(args: dict[str, Any]) -> dict[str, Any]:
    """检索促销规则（满减/会员券/以旧换新/国补）。"""
    kb = get_kb()
    query = args.get("query", "")
    promos = kb.retrieve_promotions(query, limit=args.get("limit", 5))
    return {"promotions": promos}


def tool_get_fulfillment(args: dict[str, Any]) -> dict[str, Any]:
    """检索配送/安装/入户等履约服务信息。"""
    kb = get_kb()
    query = args.get("query", "")
    items = kb.retrieve_fulfillment(query, limit=args.get("limit", 5))
    return {"fulfillment": items}


def tool_get_aftersales(args: dict[str, Any]) -> dict[str, Any]:
    """售后政策查询。退货/投诉/情绪激动等场景强制转人工。"""
    kb = get_kb()
    query = args.get("query", "")
    items = kb.retrieve_aftersales(query, limit=args.get("limit", 5))
    return {
        "aftersales": items,
        "escalation_required": True,
        "escalation_reason": "售后场景涉及退货、投诉等高风险操作，必须转接人工客服，Agent 不做自主处理。",
    }


TOOLS: dict[str, dict[str, Any]] = {
    "search_products": {
        "description": "按预算、尺寸、观看距离和用途筛选电视商品，返回加权打分排序的候选列表。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "budget": {"type": "number", "description": "预算上限（元）"},
                "size": {"type": "integer", "description": "目标尺寸（英寸），与 distance 二选一"},
                "distance": {"type": "number", "description": "观看距离（米），自动推荐尺寸"},
                "use_cases": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "用途列表，如 游戏、明亮客厅、观影",
                },
                "min_refresh": {"type": "integer", "description": "最低刷新率要求，游戏场景默认120"},
                "limit": {"type": "integer", "default": 3, "description": "返回数量上限"},
            },
        },
        "handler": tool_search_products,
    },
    "search_knowledge": {
        "description": "检索电视选购知识库文档（参数解释、技术对比等），带标题和内容。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题或关键词"},
                "limit": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
        "handler": tool_search_knowledge,
    },
    "get_promotions": {
        "description": "检索促销规则（满减、会员券、以旧换新、国补），用于优惠叠加计算。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "促销相关问题"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        "handler": tool_get_promotions,
    },
    "get_fulfillment": {
        "description": "查询配送、安装、入户等履约服务信息。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "履约相关问题"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        "handler": tool_get_fulfillment,
    },
    "get_aftersales": {
        "description": "查询售后政策。退货、投诉等高风险场景会返回强制转人工标记。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "售后相关问题"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        "handler": tool_get_aftersales,
    },
}


# ── MCP JSON-RPC 2.0 over stdio ─────────────────────────

def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """处理单个 JSON-RPC 请求，返回 response dict 或 None（通知）。"""
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "tv-buying-copilot-mcp", "version": "1.0.0"},
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": name,
                        "description": spec["description"],
                        "inputSchema": spec["inputSchema"],
                    }
                    for name, spec in TOOLS.items()
                ]
            },
        }

    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})
        if tool_name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }
        try:
            result = TOOLS[tool_name]["handler"](args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}
                    ]
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Tool error: {exc}"}],
                    "isError": True,
                },
            }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def run_stdio() -> None:
    """MCP stdio 服务主循环：按行读取 JSON-RPC，写回 response。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def run_cli() -> None:
    """命令行模式：--list-tools 或 --call <tool> '<json>'。"""
    args = sys.argv[1:]
    if not args or args[0] == "--list-tools":
        for name, spec in TOOLS.items():
            print(f"  {name}: {spec['description']}")
        return

    if args[0] == "--call" and len(args) >= 2:
        tool_name = args[1]
        tool_args = json.loads(args[2]) if len(args) >= 3 else {}
        if tool_name not in TOOLS:
            print(f"Unknown tool: {tool_name}")
            sys.exit(1)
        result = TOOLS[tool_name]["handler"](tool_args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(__doc__)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_cli()
    else:
        run_stdio()
