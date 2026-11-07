"""Command-line entrypoint for one plain-English browser test."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from src.model import ModelClient
from src.runner import run_case


def show_vars_file_help() -> None:
    help_parser = argparse.ArgumentParser(
        prog="testscribe --vars-file",
        usage="testscribe run --url URL --test CASE --vars-file PATH [other run options]",
        description="Use a local JSON file to supply values for placeholders in a browser test.",
        epilog=(
            "Create demo.secrets.json:\n"
            '  {"CUSTOMER_EMAIL": "customer@example.com", "CUSTOMER_PASSWORD": "your-password"}\n\n'
            "Run a test:\n"
            "  testscribe run --url https://example.com/login \\\n"
            "    --test 'Log in with {{CUSTOMER_EMAIL}} and {{CUSTOMER_PASSWORD}}, then verify the dashboard is shown' \\\n"
            "    --vars-file demo.secrets.json\n\n"
            "The file must contain one JSON object with string keys and string values.\n"
            "Placeholders are replaced when the runner fills browser fields.\n"
            "The file is optional. Use a *.secrets.json name to keep it Git ignored.\n"
            "Browser traces and reports may contain typed values."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    help_parser.print_help()


def main() -> None:
    if sys.argv[1:] in (["--vars-file", "--help"], ["--vars-file", "-h"],
                        ["run", "--vars-file", "--help"], ["run", "--vars-file", "-h"]):
        show_vars_file_help()
        return

    parser = argparse.ArgumentParser(
        prog="testscribe",
        description="Run plain-English browser tests with Playwright.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser(
        "run",
        help="Run one plain-English browser test",
    )
    run.add_argument("--url", required=True, help="Starting HTTP(S) URL")
    run.add_argument("--test", required=True, help="Plain-English test case")
    run.add_argument("--model", default="qwen-3.8-27b", help="Model ID (default: %(default)s)")
    run.add_argument("--base-url", default="https://bharatcode.ai/api/model/v1", help="OpenAI-compatible API base URL (default: %(default)s)")
    run.add_argument("--api-key-env", default="BHARATCODE_API_KEY", help="API key environment variable (default: %(default)s)")
    run.add_argument("--vars-file", type=Path, help="Ignored local JSON object of placeholder values")
    run.add_argument("--output-dir", type=Path, help="Directory for reports and artifacts (default: artifacts/<timestamp>)")
    run.add_argument("--headed", action="store_true", help="Show the browser window")
    run.add_argument("--slow-mo", type=int, default=0, metavar="MS", help="Delay each browser action by this many milliseconds")
    run.add_argument("--hold-seconds", type=float, default=0, metavar="SECONDS", help="Keep the final page open before closing")
    run.add_argument("--record-video", action="store_true", help="Save browser page video in the output directory")
    # Generate top-level help from the run parser so its flag list stays current.
    parser.epilog = "Vars file guide: testscribe --vars-file --help\n\nRun command help:\n\n" + run.format_help()
    args = parser.parse_args()

    if not args.url.startswith(("https://", "http://")):
        parser.error("--url must be an HTTP(S) URL")
    if args.slow_mo < 0 or args.hold_seconds < 0:
        parser.error("--slow-mo and --hold-seconds must be nonnegative")
    load_dotenv(override=False)
    api_key = os.getenv(args.api_key_env)
    if not api_key:
        parser.error(f"Set {args.api_key_env} in the environment or .env")
    variables: dict[str, str] = {}
    if args.vars_file:
        try:
            values = json.loads(args.vars_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"Cannot read --vars-file: {exc}")
        if not isinstance(values, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in values.items()
        ):
            parser.error("--vars-file must contain a JSON object of string keys and values")
        variables = values

    output_dir = args.output_dir or Path("artifacts") / datetime.now().strftime("%Y%m%d-%H%M%S")
    model = ModelClient(api_key=api_key, base_url=args.base_url, model=args.model)
    report = run_case(
        url=args.url,
        case=args.test,
        model=model,
        variables=variables,
        output_dir=output_dir,
        headed=args.headed,
        slow_mo=args.slow_mo,
        hold_seconds=args.hold_seconds,
        record_video=args.record_video,
    )
    print(f"{report['status']}: {report['reason']}")
    print(f"Report: {output_dir / 'report.json'}")
    sys.exit(0 if report["passed"] else 1)
