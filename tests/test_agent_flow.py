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


class DemoHandler(BaseHTTPRequestHandler):
    def log_message(self, *_: object) -> None:
        pass

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.startswith("/submitted"):
            body = b"<html><body><h1>Received!</h1></body></html>"
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
        if "You convert a plain-English" in system:
            if "absent" in user:
                answer = {"actions": ["Submit the form"],
                          "checks": [{"kind": "text_absent", "text": "Received!"}]}
            else:
                answer = {"actions": ["Enter Demo into Text input", "Submit the form"],
                          "checks": [{"kind": "text_visible", "text": "Received!"}]}
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

    def case(self, test: str) -> Path:
        path = self.root / "case.json"
        path.write_text(json.dumps({"url": self.base + "/form", "test": test}), encoding="utf-8")
        return path

    def run_cli(self, path: Path, name: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            [sys.executable, "-m", "src", "run", "--case-file", str(path), "--json",
             "--base-url", self.base + "/v1", "--model", "stub", "--api-key-env", "TEST_STUB_KEY",
             "--output-dir", str(self.root / name)],
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

        case = self.case("Submit the form and verify Received! is absent.")
        result, summary = self.run_cli(case, "fail")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(summary["status"], "FAIL")
        self.assertFalse(summary["checks"][0]["passed"])
        self.assertTrue(Path(summary["artifacts"]["screenshot"]).is_file())

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
            async with Client(StdioServerParameters(command=command, args=[], env={"TEST_STUB_KEY": "local-test-key"})) as client:
                listing = await client.list_tools()
                self.assertEqual({tool.name for tool in listing.tools},
                                 {"start_test", "get_test_status", "get_test_result"})
                started = await client.call_tool("start_test", {
                    "case_file": str(case), "model": "stub", "base_url": self.base + "/v1",
                    "api_key_env": "TEST_STUB_KEY",
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
                self.assertEqual(json.loads(Path(result["report_path"]).read_text())["status"], "PASS")

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
