"""
Codex 本地 Prompt 渲染验证脚本 (verify_prompt_config.py)

功能：
1. 本地调用 Codex CLI 的 `debug prompt-input` 命令，验证配置项能否被正确组装。
2. 不请求模型生成；运行时仍可能刷新目录或写入缓存。
3. 严格安全：使用命令行 `-c` 覆盖参数进行测试，并在测试前后校验 live config.toml 的哈希，确保不改动真实配置。
"""

import argparse
import os
import shutil
import sys
import hashlib
import json
import subprocess
import tomllib
from pathlib import Path

# 路径设置
SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DIR = SCRIPT_DIR / "output" / "config-verification"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 动态定位本机 Codex 二进制程序
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
assert CONFIG.exists(), f"未找到用户配置文件: {CONFIG}"
before_bytes = CONFIG.read_bytes()

# 准备测试标记文件
fixture = OUT_DIR / "base-marker.md"
fixture.write_text("PROMPT_CONFIG_BASE_MARKER_TEST", encoding="utf-8")

results = {
    "binary": str(EXE),
    "config_sha256_before": hashlib.sha256(before_bytes).hexdigest(),
    "cases": []
}

try:
    test_cases = [
        ("默认无覆盖 (default)", []),
        ("追加开发指令 (developer_instructions)", ['developer_instructions="PROMPT_CONFIG_DEVELOPER_MARKER_TEST"']),
        ("替换基础指令 (model_instructions_file)", ['model_instructions_file=' + json.dumps(fixture.as_posix())]),
    ]

    for name, overrides in test_cases:
        cmd = [str(EXE), "debug", "prompt-input"]
        for override in overrides:
            cmd.extend(["-c", override])
        cmd.append("PROMPT_CONFIG_USER_MARKER_TEST")

        run = subprocess.run(cmd, cwd=SCRIPT_DIR, capture_output=True, timeout=50, encoding="utf-8", errors="replace")
        assert run.returncode == 0, f"用例 [{name}] 执行失败:\n{run.stderr[-1500:]}"
        
        if "developer_instructions" in name:
            assert "PROMPT_CONFIG_DEVELOPER_MARKER_TEST" in run.stdout, "Developer marker missing"
        value = json.loads(run.stdout)
        safe_name = name.split()[0]
        (OUT_DIR / f"{safe_name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        
        results["cases"].append({
            "case": name,
            "exit_code": run.returncode,
            "base_marker_present": "PROMPT_CONFIG_BASE_MARKER_TEST" in run.stdout,
            "developer_marker_present": "PROMPT_CONFIG_DEVELOPER_MARKER_TEST" in run.stdout
        })

    # 安全断言：验证过程中原配置文件未被修改
    assert CONFIG.read_bytes() == before_bytes, "警告：配置文件在验证过程中发生变化！"
    results["live_config_unchanged"] = True
    results["scope"] = "Config mechanism only; debug prompt-input does not render the base instructions. Use wire verification for that."

    # 读取当前配置中的相关字段状态
    doc = tomllib.loads(before_bytes.decode("utf-8"))
    results["current_prompt_config"] = {
        key: doc.get(key) for key in ["model_instructions_file", "developer_instructions", "instructions"]
    }

    report_path = OUT_DIR / "verification_results.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== 本地 Prompt 渲染验证完成 ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))

except Exception as e:
    print(f"验证过程出错: {e}", file=sys.stderr)
    raise SystemExit(1)
