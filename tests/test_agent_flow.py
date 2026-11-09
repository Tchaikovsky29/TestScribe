"""Exercise saved cases, JSON verdicts, and the MCP wrapper end to end."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.cases import CaseFileError, load_case_file
from src.providers import PRESETS, resolve_provider


class ProviderTests(unittest.TestCase):
    def test_presets_and_overrides(self) -> None:
        self.assertEqual(set(PRESETS), {"bharatcode", "gemini", "groq"})
        self.assertEqual(resolve_provider("gemini").api_key_env, "GEMINI_API_KEY")
        self.assertEqual(resolve_provider("groq").model, "openai/gpt-oss-120b")
        selected = resolve_provider("gemini", model="different-model", api_key_env="ANOTHER_KEY")
        self.assertEqual(selected.model, "different-model")
        self.assertEqual(selected.api_key_env, "ANOTHER_KEY")
        self.assertEqual(resolve_provider("custom", base_url="http://localhost:1234/v1", model="local").api_key_env,
                         "OPENAI_API_KEY")
        with self.assertRaisesRegex(ValueError, "requires --base-url and --model"):
            resolve_provider("custom", model="local")



class DemoHandler(BaseHTTPRequestHandler):
    def log_message(self, *_: object) -> None:
        pass

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.startswith("/submitted"):
            self.server.submitted_paths.append(self.path)
            body = b"<html><body><h1>Received!</h1></body></html>"
        elif self.path.startswith("/secret-form"):
            body = (b"<html><body><form action='/submitted'>"
                    b"<label>Username <input name='username'></label>"
                    b"<label>Password <input name='password' type='password'></label>"
                    b"<button type='submit'>Submit</button></form></body></html>")
        else:
            body = (b"<html><body><form action='/submitted'>"
                    b"<label>Text input <input name='text'></label>"
                    b"<button type='submit'>Submit</button></form></body></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        size = int(self.headers.get("Content-Length", "0"))
        data = json.loads(self.rfile.read(size))
        system = data["messages"][0]["content"]
        user = data["messages"][1]["content"]
        self.server.model_inputs.append(user)
        if "You convert a plain-English" in system:
            if "{{_PASSWORD}}" in user:
                answer = {"actions": ["Enter {{USERNAME}} into Username", "Enter {{_PASSWORD}} into Password", "Submit the form"],
                          "checks": [{"kind": "text_visible", "text": "Never" if "Never" in user else "Received!"}]}
            elif "absent" in user:
                answer = {"actions": ["Submit the form"],
                          "checks": [{"kind": "text_absent", "text": "Received!"}]}
            else:
                answer = {"actions": ["Enter Demo into Text input", "Submit the form"],
                          "checks": [{"kind": "text_visible", "text": "Received!"}]}
        elif "CURRENT INTENT: Enter {{USERNAME}}" in user:
            answer = {"action": "fill", "role": "textbox", "name": "Username", "value": "{{USERNAME}}"}
        elif "CURRENT INTENT: Enter {{_PASSWORD}}" in user:
            answer = {"action": "fill", "role": "textbox", "name": "Password", "value": "{{_PASSWORD}}"}
        elif "CURRENT INTENT: Enter Demo" in user:
            answer = {"action": "fill", "role": "textbox", "name": "Text input", "value": "Demo"}
        else:
            answer = {"action": "click", "role": "button", "name": "Submit"}
        payload = json.dumps({
            "id": "stub", "object": "chat.completion", "created": 0, "model": "stub",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(answer)},
                         "finish_reason": "stop"}],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class AgentFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DemoHandler)
        cls.server.model_inputs = []
        cls.server.submitted_paths = []
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = os.environ.copy()
        self.environment["TEST_STUB_KEY"] = "local-test-key"
        self.server.model_inputs.clear()
        self.server.submitted_paths.clear()

    def case(self, test: str) -> Path:
        path = self.root / "case.json"
        path.write_text(json.dumps({"url": self.base + "/form", "test": test}), encoding="utf-8")
        return path

    def run_cli(self, path: Path, name: str, *extra_args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            [sys.executable, "-m", "src", "run", "--case-file", str(path), "--json",
             "--base-url", self.base + "/v1", "--model", "stub", "--api-key-env", "TEST_STUB_KEY",
             "--output-dir", str(self.root / name), *extra_args],
            env=self.environment, capture_output=True, text=True, timeout=30,
        )
        return result, json.loads(result.stdout)

    def test_saved_case_pass_and_false_expectation_fail(self) -> None:
        case = self.case("Enter Demo into Text input, submit the form, and verify Received! appears.")
        result, summary = self.run_cli(case, "pass")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(len(summary["steps"]), 2)
        self.assertTrue(Path(summary["report_path"]).is_file())
        self.assertEqual(json.loads(Path(summary["report_path"]).read_text())["run_id"], summary["run_id"])
        self.assertTrue(Path(summary["artifacts"]["screenshot"]).is_file())
        self.assertEqual(Path(summary["artifacts"]["screenshot"]).name, "pass.png")

        result, without_screenshot = self.run_cli(case, "pass-no-screenshot", "--no-pass-screenshot")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(without_screenshot["status"], "PASS")
        self.assertNotIn("screenshot", without_screenshot["artifacts"])

        case = self.case("Submit the form and verify Received! is absent.")
        result, summary = self.run_cli(case, "fail")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(summary["status"], "FAIL")
        self.assertFalse(summary["checks"][0]["passed"])
        self.assertTrue(Path(summary["artifacts"]["screenshot"]).is_file())

    def test_gemini_preset_selects_its_key_with_endpoint_override(self) -> None:
        case = self.case("Enter Demo into Text input, submit the form, and verify Received! appears.")
        environment = self.environment.copy()
        environment.pop("TEST_STUB_KEY")
        environment["GEMINI_API_KEY"] = "local-test-key"
        result = subprocess.run(
            [sys.executable, "-m", "src", "run", "--case-file", str(case), "--json",
             "--provider", "gemini", "--base-url", self.base + "/v1", "--model", "stub",
             "--output-dir", str(self.root / "gemini-preset")],
            env=environment, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "PASS")

    def test_bad_case_fails_before_model_or_browser(self) -> None:
        path = self.root / "bad.json"
        path.write_text('{"url":"/relative","test":"verify something"}', encoding="utf-8")
        with self.assertRaisesRegex(CaseFileError, "HTTP"):
            load_case_file(path)
        result = subprocess.run(
            [sys.executable, "-m", "src", "run", "--case-file", str(path), "--json"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("HTTP", result.stderr)

    def test_sensitive_variable_stays_out_of_model_and_report(self) -> None:
        password = "admin123"
        username = "public-user"
        vars_path = self.root / "login.secrets.json"
        vars_path.write_text(json.dumps({"USERNAME": username, "_PASSWORD": password}), encoding="utf-8")
        case_path = self.root / "login.json"
        case_path.write_text(json.dumps({
            "url": self.base + "/secret-form",
            "test": "Enter {{USERNAME}} into Username, enter {{_PASSWORD}} into Password, submit the form, and verify Received! appears.",
            "vars_file": vars_path.name,
        }), encoding="utf-8")
        result, summary = self.run_cli(case_path, "sensitive-pass")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(summary["status"], "PASS")
        self.assertNotIn("screenshot", summary["artifacts"])
        self.assertIn("password=admin123", self.server.submitted_paths[-1])
        self.assertNotIn(password, json.dumps(self.server.model_inputs))
        self.assertIn("[REDACTED]", json.dumps(self.server.model_inputs))
        self.assertIn(username, json.dumps(self.server.model_inputs))
        self.assertNotIn(password, result.stdout)
        self.assertNotIn(password, Path(summary["report_path"]).read_text())
        self.assertIn("[REDACTED]", summary["final_url"])

        result, allowed = self.run_cli(case_path, "sensitive-allowed", "--allow-sensitive-artifacts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(Path(allowed["artifacts"]["screenshot"]).is_file())

        case_path.write_text(json.dumps({
            "url": self.base + "/secret-form",
            "test": "Enter {{USERNAME}} into Username, enter {{_PASSWORD}} into Password, submit the form, and verify Never appears.",
            "vars_file": vars_path.name,
        }), encoding="utf-8")
        result, summary = self.run_cli(case_path, "sensitive-fail")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(summary["status"], "FAIL")
        self.assertEqual(summary["artifacts"], {})
        self.assertNotIn(password, Path(summary["report_path"]).read_text())

    def test_installed_cli_reads_dotenv_from_other_project(self) -> None:
        case = self.case("Enter Demo into Text input, submit the form, and verify Received! appears.")
        (self.root / ".env").write_text("TEST_STUB_KEY=local-test-key\n", encoding="utf-8")
        environment = self.environment.copy()
        environment.pop("TEST_STUB_KEY", None)
        command = Path(sys.executable).parent / ("testscribe.exe" if os.name == "nt" else "testscribe")
        result = subprocess.run(
            [str(command), "run", "--case-file", str(case), "--json",
             "--base-url", self.base + "/v1", "--model", "stub", "--api-key-env", "TEST_STUB_KEY",
             "--output-dir", str(self.root / "external")],
            cwd=self.root, env=environment, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "PASS")

    def test_mcp_tools_return_same_checked_result(self) -> None:
        try:
            from mcp import Client, StdioServerParameters
        except ImportError:
            self.skipTest("Install the optional agent extra to test MCP")

        case = self.case("Enter Demo into Text input, submit the form, and verify Received! appears.")
        command = str(Path(sys.executable).parent / ("testscribe-mcp.exe" if os.name == "nt" else "testscribe-mcp"))

        async def check() -> None:
            async with Client(StdioServerParameters(command=command, args=[], env={"GEMINI_API_KEY": "local-test-key"})) as client:
                listing = await client.list_tools()
                self.assertEqual({tool.name for tool in listing.tools},
                                 {"start_test", "get_test_status", "get_test_result"})
                started = await client.call_tool("start_test", {
                    "case_file": str(case), "provider": "gemini", "model": "stub", "base_url": self.base + "/v1",
                })
                start = started.structured_content
                self.assertIsNotNone(start)
                self.assertEqual(start["status"], "RUNNING")
                run_id = start["run_id"]
                for _ in range(100):
                    state = (await client.call_tool("get_test_status", {"run_id": run_id})).structured_content
                    if state["status"] != "RUNNING":
                        break
                    await asyncio.sleep(0.1)
                else:
                    self.fail("MCP test did not finish in 10 seconds")
                self.assertEqual(state["status"], "PASS", state)
                result = (await client.call_tool("get_test_result", {"run_id": run_id})).structured_content
                self.assertEqual(result["run_id"], run_id)
                self.assertEqual(result["status"], "PASS")
                self.assertTrue(Path(result["artifacts"]["screenshot"]).is_file())
                self.assertEqual(json.loads(Path(result["report_path"]).read_text())["status"], "PASS")

                started = await client.call_tool("start_test", {
                    "case_file": str(case), "provider": "gemini", "model": "stub", "base_url": self.base + "/v1",
                    "no_pass_screenshot": True,
                })
                no_image_run_id = started.structured_content["run_id"]
                for _ in range(100):
                    state = (await client.call_tool("get_test_status", {"run_id": no_image_run_id})).structured_content
                    if state["status"] != "RUNNING":
                        break
                    await asyncio.sleep(0.1)
                else:
                    self.fail("MCP no-screenshot test did not finish in 10 seconds")
                no_image_result = (await client.call_tool("get_test_result", {"run_id": no_image_run_id})).structured_content
                self.assertEqual(no_image_result["status"], "PASS")
                self.assertNotIn("screenshot", no_image_result["artifacts"])

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
