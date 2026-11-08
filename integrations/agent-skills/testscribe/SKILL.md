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

For a saved case, use `testscribe run --case-file path/to/case.json --json`. A case file has `url` and `test` strings, with optional `vars_file` relative to the case file. Keep credentials in an ignored vars file and refer to them as `{{NAME}}` in the test.

The JSON result includes `status`, `reason`, `checks`, `steps`, `report_path`, and artifact paths. PASS means all checks matched the browser state. FAIL means a browser action or explicit check failed. BLOCKED means planning, target resolution, credentials, or the model prevented a reliable verdict. Treat BLOCKED as unknown application behavior.

If an MCP connection is available, use `start_test`, poll `get_test_status`, then call `get_test_result`. These tools call the same Python runner as the CLI. An installed skill alone does not register the MCP server.

## Use the result

- For FAIL, inspect the failed check and action history; open the screenshot or Playwright trace only when the compact result is insufficient. Decide whether the app or the test expectation needs correction, then rerun the same case.
- For BLOCKED, inspect the reason, fix setup or ambiguity, and rerun. Do not change an explicit expected outcome merely to make the case pass.
- For PASS, report the exact case and URL that passed. Do not generalize one run into whole-site correctness.

Model calls may take time. Prefer a saved case for repeated checks and avoid rerunning unchanged tests without a reason. Reports, traces, and videos may contain typed values; keep them out of commits and user-facing logs.
