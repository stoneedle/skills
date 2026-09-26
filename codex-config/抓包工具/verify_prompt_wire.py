"""
Codex 真实发包网络层 Mock 验证脚本 (verify_prompt_wire.py)

功能：
1. 在本地启动一个极简 HTTP 服务（监听随机端口）。
2. 让 Codex CLI 发起请求到本地该端口。
3. 本地服务一旦捕获到请求报文（完整 JSON Body），立即返回 HTTP 400 掐断连接！
4. 保证 0 Token 消耗，绝不发送到远端大模型产生费用。
5. 解析收到的请求体，精准验证基础提示词（model_instructions_file）和额外指令（developer_instructions）是否真实进入了网络层 Payload。
"""

import argparse
import os
import shutil
import sys
import gzip
import hashlib
import json
import subprocess
import threading
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:
    from backports import zstd
except ImportError:
    raise SystemExit("Install backports.zstd in this Python environment before running wire verification.")

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DIR = SCRIPT_DIR / "output" / "wire-verification"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 定位二进制与配置文件
parser = argparse.ArgumentParser()
parser.add_argument('--codex-exe', help='Exact Codex CLI executable; otherwise search PATH then current user desktop installation')
parser.add_argument('--output-dir', type=Path)
args = parser.parse_args()
if args.output_dir:
    OUT_DIR = args.output_dir.resolve()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
candidate = args.codex_exe or shutil.which('codex.exe') or shutil.which('codex')
if not candidate and os.name == 'nt':
    candidates = list((Path(os.environ.get('LOCALAPPDATA', ''))/'OpenAI/Codex/bin').glob('*/codex.exe'))
    if candidates:
        candidate = str(max(candidates, key=lambda p: p.stat().st_mtime).resolve())
if not candidate:
    raise SystemExit('Codex executable not found; pass --codex-exe.')
EXE = str(candidate)

CONFIG = Path(os.environ.get("CODEX_HOME", str(Path.home()/".codex"))) / "config.toml"
before_bytes = CONFIG.read_bytes() if CONFIG.exists() else b""

captures = []

class LocalMockReceiver(BaseHTTPRequestHandler):
    """本地 Mock 接收端：捕获请求后立即返回 400 终止远端推理"""
    def log_message(self, *args):
        pass  # 静默日志

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        encoding = self.headers.get("Content-Encoding", "")
        
        if encoding == "zstd" and zstd:
            raw = zstd.decompress(raw)
        elif encoding == "gzip":
            raw = gzip.decompress(raw)
            
        try:
            captures.append(json.loads(raw))
        except Exception as e:
            captures.append({"raw_error": str(e), "raw_text": raw.decode("utf-8", errors="replace")})

        # 主动返回 400 错误，直接掐断，保证不产生实际推理
        payload = b'{"error":{"message":"LOCAL_MOCK_SUCCESS_NO_INFERENCE","type":"invalid_request_error"}}'
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

# 启动本地后台接收服务器
server = HTTPServer(("127.0.0.1", 0), LocalMockReceiver)
port = server.server_port
threading.Thread(target=server.serve_forever, daemon=True).start()

fixture_base = OUT_DIR / "base-marker.md"
fixture_base.write_text("PROMPT_CONFIG_BASE_MARKER_WIRE_TEST", encoding="utf-8")

results = []

try:
    cases = [
        ("base_override", ["model_instructions_file=" + json.dumps(fixture_base.as_posix())]),
        ("developer_append", ['developer_instructions="PROMPT_CONFIG_DEVELOPER_MARKER_WIRE_TEST"']),
    ]

    for name, extra in cases:
        captures.clear()
        overrides = [
            'model_provider="prompt_audit"',
            'model_providers.prompt_audit.name="Local prompt audit"',
            f'model_providers.prompt_audit.base_url="http://127.0.0.1:{port}/v1"',
            'model_providers.prompt_audit.wire_api="responses"',
            'model_providers.prompt_audit.requires_openai_auth=false',
            'model_providers.prompt_audit.request_max_retries=0',
            'model_providers.prompt_audit.stream_max_retries=0',
            'model_reasoning_effort="low"'
        ] + extra

        # 构造 CLI 命令：使用纯临时会话 (--ephemeral)，忽略用户既有配置 (--ignore-user-config)
        cmd = [EXE, "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check", "-m", "gpt-6-astra"]
        for opt in overrides:
            cmd.extend(["-c", opt])
        cmd.append("Test verification ping.")

        with tempfile.TemporaryDirectory(prefix="codex-prompt-wire-") as test_home:
            test_env = dict(os.environ, CODEX_HOME=test_home)
            run = subprocess.run(cmd, cwd=OUT_DIR, env=test_env, capture_output=True, encoding="utf-8", errors="replace", timeout=45)
        
        assert len(captures) > 0, f"未能截获发出的请求报文，CLI 报错:\n{run.stderr[-1000:]}"
        body = captures[0]
        assert "raw_error" not in body, body.get("raw_error")
        
        # 递归检查标记位置
        found_markers = []
        def scan(val, path="body"):
            if isinstance(val, str) and "PROMPT_CONFIG_" in val:
                found_markers.append({"path": path, "preview": val[:100]})
            elif isinstance(val, dict):
                for k, v in val.items():
                    scan(v, f"{path}.{k}")
            elif isinstance(val, list):
                for i, v in enumerate(val):
                    scan(v, f"{path}[{i}]")
                    
        scan(body)
        expected = "PROMPT_CONFIG_BASE_MARKER_WIRE_TEST" if name == "base_override" else "PROMPT_CONFIG_DEVELOPER_MARKER_WIRE_TEST"
        developer_texts = [part.get("text", "") for item in body.get("input", []) if isinstance(item, dict) and item.get("role") == "developer" for part in item.get("content", []) if isinstance(part, dict)]
        assert expected in developer_texts, f"Expected developer text missing: {expected}"
        if name == "base_override":
            assert not any(text.startswith("You are Codex,") for text in developer_texts), "Old base remains alongside replacement"
        else:
            assert any(text.startswith("You are Codex,") for text in developer_texts), "Default base unexpectedly missing"
        
        results.append({
            "case": name,
            "exit_code": run.returncode,
            "captured": True,
            "found_markers": found_markers
        })

        # 保存过滤后的指令载荷供审阅
        filtered = {
            "instructions": body.get("instructions"),
            "input": [
                {"index": i, "item": item}
                for i, item in enumerate(body.get("input", []))
                if isinstance(item, dict) and item.get("role") in ("system", "developer")
            ]
        }
        (OUT_DIR / f"{name}-captured-wire.json").write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")

finally:
    server.shutdown()
    server.server_close()

# 校验现场配置未被修改
if CONFIG.exists():
    assert CONFIG.read_bytes() == before_bytes, "警告：配置文件在验证过程中发生变化！"

report = {
    "live_config_unchanged": True,
    "inference_performed": False,
    "results": results
}
(OUT_DIR / "wire_results_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("=== 本地 Mock 发包拦截验证完成 ===")
print(json.dumps(report, ensure_ascii=False, indent=2))
