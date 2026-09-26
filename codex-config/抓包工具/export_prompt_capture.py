"""
从 claude-tap 提取真实请求 Prompt 数据的脚本 (export_prompt_capture.py)

功能：
1. 以只读模式 (mode=ro) 连接本地 claude-tap 抓包数据库 (~/.local/share/claude-tap/traces.sqlite3)。
2. 根据指定的会话 ID 和记录编号，解包请求 Payload。
3. 将请求里的工具列表、基础指令、技能清单、桌面上下文等拆分为独立的 Markdown/JSON 文件，并生成 manifest.json。
"""

import hashlib
import json
import sqlite3
import sys
import argparse
from pathlib import Path

try:
    from claude_tap.compact_trace import decode_compact_record_payload
except ImportError:
    decode_compact_record_payload = None

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DIR = SCRIPT_DIR / "output" / "exported-capture"
OUT_DIR.mkdir(parents=True, exist_ok=True)

parser = argparse.ArgumentParser()
parser.add_argument('--session', help='Captured session UUID')
parser.add_argument('--record', type=int, help='Record index within that session')
parser.add_argument('--list', action='store_true', help='List recent sessions or records of --session')
parser.add_argument('--db', type=Path, default=Path.home()/'.local/share/claude-tap/traces.sqlite3')
parser.add_argument('--output-dir', type=Path, default=OUT_DIR)
args=parser.parse_args()
DEFAULT_SESSION_ID=args.session
DEFAULT_RECORD_INDEX=args.record
OUT_DIR=args.output_dir.resolve()
OUT_DIR.mkdir(parents=True,exist_ok=True)

db_path = args.db.resolve()

def main():
    if not db_path.exists():
        print(f"未找到 claude-tap 数据库: {db_path}，请先使用 claude-tap 进行抓包。")
        raise SystemExit(1)

    if decode_compact_record_payload is None:
        print("未检测到 claude_tap 模块，请先确保在已安装 claude-tap 的 Python 环境中运行。")
        raise SystemExit(1)

    # 以严格的只读模式连接原数据库，防止产生写锁或修改原库
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    if args.list:
        query = 'SELECT record_index,timestamp FROM records WHERE session_id=? ORDER BY record_index' if args.session else 'SELECT id,started_at,record_count FROM sessions ORDER BY started_at DESC LIMIT 20'
        print(json.dumps(conn.execute(query, (args.session,) if args.session else ()).fetchall(),ensure_ascii=False,indent=2))
        conn.close()
        return
    if not args.session or args.record is None:
        parser.error('Pass --session and --record; use --list first.')
    row = conn.execute(
        "SELECT record_index, payload_json FROM records WHERE session_id=? AND record_index=?",
        (DEFAULT_SESSION_ID, DEFAULT_RECORD_INDEX)
    ).fetchone()

    if not row:
        print(f"未在数据库中找到会话 {DEFAULT_SESSION_ID} 的记录 {DEFAULT_RECORD_INDEX}")
        conn.close()
        raise SystemExit(1)

    index, payload_raw = row

    def get_blob(ref):
        val = conn.execute(
            "SELECT payload_json FROM record_blobs WHERE session_id=? AND hash=? AND kind=?",
            (DEFAULT_SESSION_ID, ref["hash"], ref.get("kind") or "json")
        ).fetchone()
        assert val, f"缺少 Blob 引用: {ref}"
        return json.loads(val[0])

    record = decode_compact_record_payload(json.loads(payload_raw), get_blob)
    body = record.get("request", {}).get("body", {})

    manifest = {
        "session": DEFAULT_SESSION_ID,
        "record_index": index,
        "model": body.get("model"),
        "instructions_present": "instructions" in body,
        "system_message_count": sum(x.get("role") == "system" for x in body.get("input", []) if isinstance(x, dict)),
        "parts": []
    }

    def save_item(filename, content_str, pointer, role, tag):
        data = content_str.encode("utf-8")
        target = OUT_DIR / filename
        target.write_bytes(data)
        manifest["parts"].append({
            "file": filename,
            "pointer": pointer,
            "role": role,
            "tag": tag,
            "chars": len(content_str),
            "sha256": hashlib.sha256(data).hexdigest()
        })

    if isinstance(body.get("instructions"), str):
        save_item("request-instructions.raw.md", body["instructions"], "request.body.instructions", "instructions", "instructions")

    names = {
        "<app-context>": "app-context",
        "<skills_instructions>": "skills-catalog",
        "<permissions instructions>": "permissions",
        "<collaboration_mode>": "collaboration-mode",
        "<multi_agent_role>": "multi-agent-role",
        "<multi_agent_mode>": "multi-agent-mode"
    }

    for i, item in enumerate(body.get("input", [])):
        role = item.get("role")
        if role not in ("system", "developer"):
            continue
        
        if item.get("type") == "additional_tools":
            save_item(f"{role}-{i:03d}-tools.json", json.dumps(item, ensure_ascii=False, indent=2),
                      f"request.body.input[{i}]", role, "tools-json")
            
        content = item.get("content", [])
        if isinstance(content, str):
            content = [{"text": content}]
        for j, part in enumerate(content):
            text = part.get("text") if isinstance(part, dict) else None
            if not isinstance(text, str):
                continue
            tag = next((n for prefix, n in names.items() if text.startswith(prefix)),
                       "base" if text.startswith("You are Codex,") else "text")
            save_item(f"{role}-{i:03d}-{j:02d}-{tag}.raw.md", text,
                      f"request.body.input[{i}].content[{j}].text", role, tag)

    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.close()
    print(f"提取完成！文件已保存至: {OUT_DIR}")
    print(f"共提取 {len(manifest['parts'])} 个指令/数据片段。")

if __name__ == "__main__":
    main()
