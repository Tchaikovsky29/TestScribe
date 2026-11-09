"""Local MCP tools for long-running TestScribe browser tests."""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.cases import CaseFileError, load_case_file
from src.reporting import compact_report


@dataclass
class Job:
    process: subprocess.Popen[str]
    output_dir: Path
    failure_reason: str | None = None


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    def start(
        self,
        *,
        url: str | None = None,
        test: str | None = None,
        case_file: str | None = None,
        vars_file: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        no_pass_screenshot: bool = False,
    ) -> dict[str, str]:
        if case_file:
            if url or test:
                return {"status": "ERROR", "reason": "Use case_file or url and test, not both"}
            try:
                load_case_file(Path(case_file))
            except CaseFileError as exc:
                return {"status": "ERROR", "reason": str(exc)}
        elif not url or not test:
            return {"status": "ERROR", "reason": "Supply case_file or both url and test"}
        scripts = Path(sysconfig.get_path("scripts"))
        command = scripts / ("testscribe.exe" if os.name == "nt" else "testscribe")
        if not command.is_file():
            return {"status": "ERROR", "reason": "TestScribe CLI is missing from this Python environment; install the package first"}
        run_id = uuid.uuid4().hex
        output_root = Path(os.getenv("TESTSCRIBE_ARTIFACTS_DIR") or tempfile.gettempdir()).resolve()
        output_dir = output_root / "testscribe-runs" / run_id
        output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
        args = [str(command), "run", "--json", "--output-dir", str(output_dir)]
        if case_file:
            args += ["--case-file", str(Path(case_file).resolve())]
        else:
            args += ["--url", url or "", "--test", test or ""]
        if vars_file:
            args += ["--vars-file", str(Path(vars_file).resolve())]
        for flag, value in (("--model", model), ("--base-url", base_url), ("--api-key-env", api_key_env)):
            if value:
                args += [flag, value]
        if no_pass_screenshot:
            args.append("--no-pass-screenshot")
        environment = os.environ.copy()
        environment["TESTSCRIBE_RUN_ID"] = run_id
        try:
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)
        except OSError as exc:
            return {"status": "ERROR", "reason": f"Could not start TestScribe: {exc}"}
        self.jobs[run_id] = Job(process=process, output_dir=output_dir)
        return {"run_id": run_id, "status": "RUNNING"}

    def status(self, run_id: str) -> dict[str, Any]:
        job = self.jobs.get(run_id)
        if job is None:
            return {"run_id": run_id, "status": "ERROR", "reason": "Unknown run ID in this MCP session"}
        if job.process.poll() is None:
            return {"run_id": run_id, "status": "RUNNING"}
        report_path = job.output_dir / "report.json"
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                return {"run_id": run_id, "status": report["status"], "reason": report["reason"]}
            except (OSError, ValueError, KeyError):
                pass
        if job.failure_reason is None:
            _, stderr = job.process.communicate()
            job.failure_reason = stderr.strip()[-1000:] or "TestScribe exited before writing a valid report"
        return {"run_id": run_id, "status": "ERROR", "reason": job.failure_reason}

    def result(self, run_id: str) -> dict[str, Any]:
        state = self.status(run_id)
        if state["status"] in {"RUNNING", "ERROR"}:
            return state
        job = self.jobs[run_id]
        report_path = job.output_dir / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return compact_report(report, report_path)

    def shutdown(self) -> None:
        for job in self.jobs.values():
            if job.process.poll() is None:
                job.process.terminate()


jobs = JobManager()
atexit.register(jobs.shutdown)


def main() -> None:
    try:
        from mcp.server import MCPServer
    except ImportError:
        print("Install the MCP extra with: pip install 'testscribe[agent]'", file=sys.stderr)
        raise SystemExit(2)

    server = MCPServer(
        "TestScribe",
        instructions="Run explicit plain-English browser tests. PASS, FAIL, and BLOCKED are distinct outcomes. Use start_test, poll get_test_status, then read get_test_result; never treat BLOCKED as app failure.",
    )

    @server.tool()
    def start_test(
        url: str | None = None,
        test: str | None = None,
        case_file: str | None = None,
        vars_file: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        no_pass_screenshot: bool = False,
    ) -> dict[str, str]:
        """Start a browser test and return a run ID promptly; provide a case file or URL and test."""
        return jobs.start(url=url, test=test, case_file=case_file, vars_file=vars_file,
                          model=model, base_url=base_url, api_key_env=api_key_env,
                          no_pass_screenshot=no_pass_screenshot)

    @server.tool()
    def get_test_status(run_id: str) -> dict[str, Any]:
        """Poll a test run; RUNNING is intermediate, PASS/FAIL/BLOCKED are final."""
        return jobs.status(run_id)

    @server.tool()
    def get_test_result(run_id: str) -> dict[str, Any]:
        """Return the checked verdict, concise steps and checks, and local evidence paths."""
        return jobs.result(run_id)

    server.run(transport="stdio")


if __name__ == "__main__":
    main()
