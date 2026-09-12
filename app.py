"""电视选购 Copilot：Multi-Agent 电视导购系统。

编排引擎：Master Router → Worker Agent(s) → Replanner → Compliance → Answer
四层终止条件：完成 / 失败 / 中断 / 防重复

零第三方依赖，仅 Python 标准库。
启动：python app.py；在线演示请使用 README 中的 GitHub Pages 地址
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

# 核心模块
from core.llm_client import LLMClient, Settings
from core.memory import ShortTermMemory, LongTermMemory
from core.parser import NeedParser
from core.rag import KnowledgeBase
from core.replanner import Replanner

# Agent 模块
from agents.base import AgentResult
from agents.master import MasterRouter
from agents.product import ProductAgent
from agents.promotion import PromotionAgent
from agents.fulfillment import FulfillmentAgent
from agents.aftersales import AftersalesAgent
from agents.clarify import ClarifyAgent
from agents.compliance import ComplianceAgent

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
TEMPLATE_DIR = BASE_DIR / "templates"
MEMORY_DIR = BASE_DIR / "memory"


class ResultCache:
    """简单结果缓存：带过期时间的字典缓存。

    成本优化手段三：结果缓存。高频查询（优惠活动、配送政策）缓存24小时，
    减少重复 RAG 检索和 LLM 调用。
    """

    def __init__(self, ttl_seconds: int = 86400):
        self._cache: dict[str, tuple[float, dict]] = {}
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> dict | None:
        import time
        with self._lock:
            if key not in self._cache:
                self.misses += 1
                return None
            expire_at, value = self._cache[key]
            if time.time() > expire_at:
                del self._cache[key]
                self.misses += 1
                return None
            self.hits += 1
            return value

    def set(self, key: str, value: dict) -> None:
        import time
        with self._lock:
            self._cache[key] = (time.time() + self._ttl, value)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class AgentOrchestrator:
    """Multi-Agent 编排引擎。

    流程：
    1. NeedParser 提取槽位 → 更新短期记忆
    2. Master Router 确定性分类
    3. 路由到对应 Worker Agent（商品/促销/履约可并行）
    4. Replanner 硬约束二次检查
    5. Compliance 合规审核（修正循环，最大2次）
    6. 返回回答 + 完整执行轨迹

    四层终止条件：
    - 完成：Worker成功 + 合规通过
    - 失败：Worker失败且无降级 / 合规2次修正失败
    - 中断：用户要求人工 / 高风险售后
    - 防重复：澄清最多3次 / 合规修正最多2次 / 循环最多8轮
    """

    MAX_LOOPS = 8
    MAX_CLARIFY = 3

    def __init__(self):
        self.settings = Settings.from_env()
        self.llm = LLMClient(self.settings)
        self.kb = KnowledgeBase(DATA_DIR / "knowledge.json")
        self.replanner = Replanner()
        self.long_term = LongTermMemory(MEMORY_DIR / "user_profiles.json")

        # 初始化所有 Agent
        self.master = MasterRouter(kb=self.kb, llm=self.llm)
        self.product_agent = ProductAgent(kb=self.kb, llm=self.llm)
        self.promotion_agent = PromotionAgent(kb=self.kb, llm=self.llm)
        self.fulfillment_agent = FulfillmentAgent(kb=self.kb, llm=self.llm)
        self.aftersales_agent = AftersalesAgent(kb=self.kb, llm=self.llm)
        self.clarify_agent = ClarifyAgent(kb=self.kb, llm=self.llm)
        self.compliance_agent = ComplianceAgent(kb=self.kb, llm=self.llm)

        # 会话存储
        self.sessions: dict[str, ShortTermMemory] = {}
        self.sessions_lock = threading.Lock()

        # 结果缓存（成本优化：高频查询缓存24小时）
        self.cache = ResultCache(ttl_seconds=86400)

    def _get_session(self, session_id: str) -> ShortTermMemory:
        with self.sessions_lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = ShortTermMemory()
            return self.sessions[session_id]

    def handle(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        """处理用户消息，返回回答和执行轨迹。"""
        if not session_id:
            session_id = str(uuid.uuid4())
        memory = self._get_session(session_id)
        memory.turn += 1
        memory.add_message("user", message)

        trace: list[dict[str, str]] = []
        clarify_count = sum(1 for h in memory.history if h["role"] == "assistant" and "请问" in h["content"])

        # 1. 越权检查（中断条件：高风险直接转人工）
        handoff_check = self.replanner.check_handoff(message)
        if handoff_check.action == "handoff":
            trace.append({"kind": "guard", "name": "handoff_check", "status": "triggered", "detail": handoff_check.reason})
            answer = "您的问题涉及交易操作或高风险售后，已为您转接人工客服。"
            memory.add_message("assistant", answer)
            return {"answer": answer, "trace": trace, "session_id": session_id, "route": "handoff"}

        # 2. 需求解析
        new_slots = NeedParser.extract(message)
        memory.update_slots(new_slots)
        trace.append({"kind": "parse", "name": "need_parser", "status": "ok", "detail": f"提取槽位：{json.dumps(new_slots, ensure_ascii=False)}"})

        # 3. Master Router 分类
        route_result = self.master.run(message, memory.slots, {})
        trace.extend(route_result.trace)
        route = route_result.data["route"]
        trace.append({"kind": "router", "name": "master", "status": "ok", "detail": f"路由：{route}"})

        # 结果缓存：promotion/fulfillment 高频查询缓存24小时
        cache_key = f"{route}:{message}"
        if route in ("promotion", "fulfillment"):
            cached = self.cache.get(cache_key)
            if cached:
                trace.append({"kind": "cache", "name": "result_cache", "status": "hit", "detail": f"缓存命中（命中率 {self.cache.hit_rate*100:.0f}%）"})
                cached["trace"] = trace + cached.get("trace_extra", [])
                cached["session_id"] = session_id
                return cached

        # 4. 主循环（ReAct 风格，四层终止条件）
        answer = ""
        products: list[dict] = []
        citations: list[dict] = []

        for loop in range(self.MAX_LOOPS):
            # 防重复：循环上限
            if loop >= self.MAX_LOOPS - 1:
                trace.append({"kind": "terminate", "name": "max_loops", "status": "warning", "detail": "达到最大循环次数"})
                answer = "抱歉，信息仍不够明确，建议您直接咨询在线客服。"
                break

            # 对比/可行性/高端意向：即使缺槽位也直接走product，不澄清
            is_special_product = route == "product" and any(
                kw in message for kw in ["哪个好", "对比", "区别", "哪个更好", "能买到", "有没有", "可以买", "能买", "最好", "最高端", "旗舰"]
            )
            if route == "clarify" or (route == "product" and not is_special_product and self.replanner.check_missing_slots(memory.slots).action == "clarify"):
                # 澄清分支
                if clarify_count >= self.MAX_CLARIFY:
                    # 防重复：澄清上限，强制推荐
                    trace.append({"kind": "terminate", "name": "max_clarify", "status": "warning", "detail": "澄清达3次上限，按默认场景推荐"})
                    memory.slots.setdefault("budget", 4000)
                    memory.slots.setdefault("distance", 2.5)
                    memory.slots.setdefault("use_cases", ["追剧", "电影"])
                    route = "product"
                    continue

                clarify_result = self.clarify_agent.run(message, memory.slots, {"clarify_count": clarify_count})
                trace.extend(clarify_result.trace)
                if clarify_result.needs_clarification:
                    answer = clarify_result.content
                    break
                else:
                    # 澄清完成，继续推荐
                    route = "product"
                    continue

            if route == "aftersales":
                # 售后分支（中断条件：强制转人工）
                result = self.aftersales_agent.run(message, memory.slots, {})
                trace.extend(result.trace)
                answer = result.content
                break

            if route == "promotion":
                result = self.promotion_agent.run(message, memory.slots, {})
                trace.extend(result.trace)
                answer = result.content
                break

            if route == "fulfillment":
                result = self.fulfillment_agent.run(message, memory.slots, {})
                trace.extend(result.trace)
                answer = result.content
                break

            if route == "product":
                # 商品推荐：ProductAgent + 可选并行PromotionAgent
                product_result = self.product_agent.run(message, memory.slots, {})
                trace.extend(product_result.trace)
                products = product_result.data.get("products", [])
                citations = product_result.data.get("citations", [])

                # Replanner 硬约束检查（失败条件：无候选）
                check = self.replanner.check_products(products, memory.slots)
                trace.append({"kind": "replanner", "name": "constraint_check", "status": check.action, "detail": check.reason})

                if check.action == "fallback":
                    # 失败条件：无候选，降级建议
                    answer = (
                        f"抱歉，在 ¥{memory.slots.get('budget')} 预算内未找到完全匹配的电视。\n"
                        "建议：1) 适当提高预算；2) 放宽刷新率要求；3) 考虑55寸/65寸主流尺寸。"
                    )
                    break

                if check.action == "corrected":
                    products = check.corrected_products

                answer = product_result.content
                break

            # fallback
            answer = "我是电视导购助手，可以帮你推荐电视、查询优惠和配送安装政策。请问有什么可以帮您？"
            break

        # 5. 合规审核（修正循环，最大2次）
        if answer and route != "handoff":
            compliance_result = self.compliance_agent.run(
                answer, memory.slots,
                {"answer": answer, "products": products, "route": route}
            )
            trace.extend(compliance_result.trace)
            if compliance_result.success:
                answer = compliance_result.content
            elif compliance_result.data.get("action") == "handoff":
                answer = compliance_result.content

        memory.add_message("assistant", answer)
        result = {
            "answer": answer,
            "trace": trace,
            "session_id": session_id,
            "route": route,
            "slots": memory.slots,
            "llm_available": self.llm.available,
        }

        # 写入缓存：promotion/fulfillment 结果缓存
        if route in ("promotion", "fulfillment"):
            cache_entry = dict(result)
            cache_entry["trace_extra"] = [{"kind": "cache", "name": "result_cache", "status": "stored", "detail": "结果已缓存（24小时）"}]
            self.cache.set(cache_key, cache_entry)

        return result


# ── HTTP 服务 ──────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    orchestrator: AgentOrchestrator | None = None

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            html_path = TEMPLATE_DIR / "index.html"
            if html_path.exists():
                body = html_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._send_json({"error": "index.html not found"}, 404)
            return
        if parsed.path == "/health":
            self._send_json({"status": "ok", "llm_available": self.orchestrator.llm.available if self.orchestrator else False})
            return
        self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/chat":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                self._send_json({"error": "invalid JSON"}, 400)
                return
            message = data.get("message", "").strip()
            session_id = data.get("session_id")
            if not message:
                self._send_json({"error": "message is required"}, 400)
                return
            result = self.orchestrator.handle(message, session_id)
            self._send_json(result)
            return
        self._send_json({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass  # 静默日志


def main():
    port = int(os.getenv("PORT", "8765"))
    Handler.orchestrator = AgentOrchestrator()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"电视选购 Copilot Multi-Agent 导购系统已启动")
    print(f"服务已启动，监听端口 {port}")
    print(f"LLM 可用：{Handler.orchestrator.llm.available}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()


if __name__ == "__main__":
    main()
