---
name: testscribe
description: Run an existing web app through a plain-English browser test and inspect an evidence-backed PASS, FAIL, or BLOCKED result. Use after changing a web UI or when asked to verify a user flow; skip for unit-only code or when no runnable web page is available.
compatibility: Requires local TestScribe, Playwright Chromium, and a configured model API key.
---

# TestScribe for coding agents

Use TestScribe to check a specific browser outcome after an app change. Give it a reachable HTTP(S) URL and a test that names both the user actions and the expected result. A local development URL is fine when the app is running.

## Run a case

For an ad hoc case:

```bash
testscribe run --url http://localhost:3000 \
  --test 'Open the contact page, submit the form with a missing email, and verify that an email error is shown.' \
  --json
```

For a saved case, use `testscribe run --case-file path/to/case.json --json`. A case file has `url` and `test` strings, with optional `vars_file` relative to the case file. Keep credentials in an ignored vars file and prefix sensitive keys with `_`, for example `"_PASSWORD": "..."` and `{{_PASSWORD}}` in the test. Marked values are substituted locally and exact matches are redacted before model calls and in reports. Sensitive runs skip screenshots, traces, and video unless `--allow-sensitive-artifacts` is supplied.

The JSON result includes `status`, `reason`, `checks`, `steps`, `report_path`, and artifact paths. PASS means all checks matched the browser state. FAIL means a browser action or explicit check failed. BLOCKED means planning, target resolution, credentials, or the model prevented a reliable verdict. Treat BLOCKED as unknown application behavior.

Passing runs save a final-page screenshot by default unless a marked sensitive variable is present. Add `--no-pass-screenshot` to the CLI (or `no_pass_screenshot: true` to MCP `start_test`) to skip it. Sensitive screenshots require `--allow-sensitive-artifacts` in the CLI.

If an MCP connection is available, use `start_test`, poll `get_test_status`, then call `get_test_result`. These tools call the same Python runner as the CLI. An installed skill alone does not register the MCP server.

## Use the result

- For FAIL, inspect the failed check and action history; open the screenshot or Playwright trace only when the compact result is insufficient. Decide whether the app or the test expectation needs correction, then rerun the same case.
- For BLOCKED, inspect the reason, fix setup or ambiguity, and rerun. Do not change an explicit expected outcome merely to make the case pass.
- For PASS, report the exact case and URL that passed. Do not generalize one run into whole-site correctness.

Model calls may take time. Prefer a saved case for repeated checks and avoid rerunning unchanged tests without a reason. Exact-match redaction does not cover values transformed by the site; unmarked values and artifacts allowed with `--allow-sensitive-artifacts` may contain typed values. Keep these out of commits and user-facing logs.
