"""Offline public-contract tests. A local agy.exe double replaces the real CLI on PATH."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SKILL = Path(__file__).resolve().parents[1]
ENTRY = SKILL / "scripts" / "Invoke-Agy.ps1"
FAKE_CLI = r'''
using System;
using System.IO;
using System.Text;
using System.Collections.Generic;
using System.Web.Script.Serialization;
class FakeAgy {
    static int Main(string[] args) {
        string root = Environment.GetEnvironmentVariable("AGY_TEST_CASE");
        if (String.IsNullOrEmpty(root)) return 99;
        var json = new JavaScriptSerializer();
        var utf8 = new UTF8Encoding(false);
        File.WriteAllText(Path.Combine(root, "called.json"), json.Serialize(new {
            args = args, cwd = Directory.GetCurrentDirectory()
        }), utf8);
        string writes = Path.Combine(root, "writes.json");
        if (File.Exists(writes)) {
            var files = json.Deserialize<Dictionary<string, string>>(File.ReadAllText(writes, utf8));
            foreach (var file in files) {
                Directory.CreateDirectory(Path.GetDirectoryName(file.Key));
                File.WriteAllText(file.Key, file.Value, utf8);
            }
        }
        Console.OutputEncoding = utf8;
        Console.Out.Write(File.ReadAllText(Path.Combine(root, "stdout.json"), utf8));
        Console.Error.Write(File.ReadAllText(Path.Combine(root, "stderr.txt"), utf8));
        return Int32.Parse(File.ReadAllText(Path.Combine(root, "exit.txt")));
    }
}
'''


class AgyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="agy-contract-")
        cls.root = Path(cls.scratch.name).resolve()
        cls.bin = cls.root / "bin"
        cls.bin.mkdir()
        cls.pwsh = shutil.which("pwsh")
        compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        source = cls.root / "FakeAgy.cs"
        source.write_text(FAKE_CLI, encoding="utf-8")
        build = subprocess.run(
            [str(compiler), "/nologo", "/r:System.Web.Extensions.dll",
             f"/out:{cls.bin / 'agy.exe'}", str(source)],
            capture_output=True, text=True,
        )
        if build.returncode:
            raise RuntimeError(build.stdout + build.stderr)

    @classmethod
    def tearDownClass(cls):
        # Only remove the newly allocated test directory, never a caller's path.
        assert cls.root.parent == Path(tempfile.gettempdir()).resolve()
        assert cls.root.name.startswith("agy-contract-")
        cls.scratch.cleanup()

    def setUp(self):
        self.case = Path(tempfile.mkdtemp(prefix="case-", dir=self.root))
        self.cwd = self.case / "项目 空格"
        self.cwd.mkdir()
        self.prompt_text = '用户原话："看这个"\r\n保留 `符号`、$变量、中文。\n'
        self.prompt = self.case / "prompt.md"
        self.prompt.write_bytes(self.prompt_text.encode("utf-8"))

    def invoke(self, response="原样答复。", *, envelope=None, stderr="", exit_code=0,
               schema=None, artifacts=(), writes=None, extra=()):
        if envelope is None:
            envelope = {"conversation_id": "conversation-1", "status": "SUCCESS", "response": response}
        (self.case / "stdout.json").write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        (self.case / "stderr.txt").write_text(stderr, encoding="utf-8")
        (self.case / "exit.txt").write_text(str(exit_code), encoding="ascii")
        (self.case / "writes.json").write_text(json.dumps(writes or {}, ensure_ascii=False), encoding="utf-8")
        called = self.case / "called.json"
        if called.exists():
            called.unlink()
        args = [self.pwsh, "-NoProfile", "-File", str(ENTRY), "-PromptPath", str(self.prompt),
                "-WorkingDirectory", str(self.cwd), *extra]
        if schema is not None:
            schema_file = self.case / "schema.json"
            schema_file.write_text(json.dumps(schema), encoding="utf-8")
            args.extend(["-JsonSchemaPath", str(schema_file)])
        if artifacts:
            args.extend(["-ArtifactPaths", *map(str, artifacts)])
        env = dict(os.environ)
        env["PATH"] = str(self.bin) + os.pathsep + env["PATH"]
        env["AGY_TEST_CASE"] = str(self.case)
        run = subprocess.run(args, env=env, capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(run.stderr, "", run.stderr)
        result = json.loads(run.stdout)  # Also proves stdout is exactly one JSON value.
        self.assertEqual(run.returncode, 0 if result["ok"] else 1)
        if result["log_dir"]:
            receipt = json.loads((Path(result["log_dir"]) / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result, receipt)
        return result

    def test_text_round_trip_and_real_process_arguments(self):
        text = 'Gemini 原文："a"\r\n\n第二行 `code`。\n'
        result = self.invoke(text, extra=("-ConversationId", "conversation-1", "-Model", "test-model"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["output"]["value"], text)
        self.assertEqual(Path(result["output"]["path"]).read_bytes(), text.encode("utf-8"))
        self.assertEqual(result["output"]["format"], "text")
        self.assertTrue(result["output"]["inline"])
        call = json.loads((self.case / "called.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(call["cwd"]), self.cwd)
        args = call["args"]
        self.assertEqual(args[args.index("--model") + 1], "test-model")
        self.assertEqual(args[args.index("--conversation") + 1], "conversation-1")
        self.assertTrue(args[args.index("--print") + 1].endswith(self.prompt_text))

    def test_json_uses_current_body_not_historical_provider_field(self):
        schema = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}, "additionalProperties": False}
        result = self.invoke(envelope={
            "conversation_id": "conversation-1", "status": "SUCCESS",
            "response": '{"answer":"本轮","toolAction":"Submitting result","toolSummary":"Submit result"}',
            "structured_output": {"answer": "上轮"},
        }, schema=schema)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["output"]["format"], "json")
        self.assertEqual(result["output"]["value"], {"answer": "本轮"})
        self.assertEqual(json.loads(Path(result["output"]["path"]).read_text(encoding="utf-8")), result["output"]["value"])

    def test_schema_owned_fields_are_preserved(self):
        schema = {"type": "object", "properties": {"toolAction": {"type": "string"}}, "additionalProperties": False}
        result = self.invoke('{"toolAction":"用户定义的数据"}', schema=schema)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["output"]["value"], {"toolAction": "用户定义的数据"})

    def test_json_values_preserve_array_and_null_shapes(self):
        for data, schema in [([1], {"type": "array"}), ([], {"type": "array"}), (None, {"type": "null"})]:
            with self.subTest(data=data):
                result = self.invoke(json.dumps(data), schema=schema)
                self.assertTrue(result["ok"], result)
                self.assertTrue(result["output"]["inline"])
                self.assertEqual(result["output"]["value"], data)

    def test_recorded_denial_and_empty_success_are_structured_failures(self):
        fixtures = Path(__file__).with_name("fixtures")
        denied = json.loads((fixtures / "denied-success.json").read_text(encoding="utf-8"))
        result = self.invoke(envelope=denied, stderr=(fixtures / "denied-stderr.txt").read_text(encoding="utf-8"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "tool_denied")
        self.assertEqual(result["conversation_id"], denied["conversation_id"])
        self.assertIsNone(result["output"])
        result = self.invoke("")
        self.assertEqual(result["error"]["code"], "empty_response")
        result = self.invoke(exit_code=3)
        self.assertEqual(result["error"]["code"], "cli_failed")

    def test_invalid_current_json_never_falls_back_to_valid_history(self):
        schema = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "integer"}}}
        for current, code in [("本轮未提供 JSON", "invalid_json"), ('{"answer":"wrong type"}', "schema_mismatch")]:
            with self.subTest(code=code):
                result = self.invoke(envelope={
                    "conversation_id": "conversation-1", "status": "SUCCESS", "response": current,
                    "structured_output": {"answer": 1},
                }, schema=schema)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], code)

    def test_declared_artifact_write_is_checked(self):
        path = self.cwd / "overview.html"
        result = self.invoke(artifacts=(path,), writes={str(path): "<html>本轮产物</html>"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["artifacts"], [str(path)])
        result = self.invoke(artifacts=(path,))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "artifact_not_updated")
        result = self.invoke(artifacts=(path,), writes={str(path): "<html>更新后的产物</html>"})
        self.assertTrue(result["ok"], result)

    def test_large_reply_is_complete_in_file_not_truncated(self):
        text = "完整原文。\n" * 3000
        result = self.invoke(text)
        self.assertTrue(result["ok"])
        self.assertFalse(result["output"]["inline"])
        self.assertIsNone(result["output"]["value"])
        self.assertEqual(Path(result["output"]["path"]).read_bytes(), text.encode("utf-8"))

    def test_invalid_prompt_is_reported_before_invocation(self):
        self.prompt.write_text("", encoding="utf-8")
        result = self.invoke()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_request")
        self.assertFalse((self.case / "called.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
