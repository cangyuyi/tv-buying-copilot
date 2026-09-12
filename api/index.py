import sys
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))


class handler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            try:
                from app import AgentOrchestrator
                orch = AgentOrchestrator()
                self._send_json({"status": "ok", "llm_available": orch.llm.available})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)})
        else:
            self._send_json({"error": "not found", "path": self.path}, 404)

    def do_POST(self):
        if self.path == "/chat":
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
            try:
                from app import AgentOrchestrator
                orch = AgentOrchestrator()
                result = orch.handle(message, session_id)
                self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
        else:
            self._send_json({"error": "not found", "path": self.path}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass
