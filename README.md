# TestScribe

TestScribe runs a plain-English test case in Chromium and reports `PASS`, `FAIL`, or `BLOCKED`. Web developers can run saved cases from the CLI or [VS Code extension](vscode-extension/README.md); coding agents can use the [agent skill](integrations/agent-skills/testscribe/SKILL.md) and MCP tools. It uses an AI model to turn the case into browser actions, Playwright to find and operate page elements, and code to check the requested result. The same runner works across sites; no PHPTRAVELS selectors or flows are embedded in it.

## Setup

Requires Python 3.10+, cURL, and an API key for an OpenAI-compatible chat endpoint.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
cp .env.example .env
```

Set a key for your chosen provider in `.env`. BharatCode `qwen-3.8-27b` is the default. `--provider gemini` and `--provider groq` select their endpoints, default models, and key names automatically. You can override those values with `--base-url`, `--model`, and `--api-key-env`. For an arbitrary OpenAI-compatible endpoint, use `--provider custom` with `--base-url` and `--model` (`OPENAI_API_KEY` is the default key name).

**No paid subscription option:** Create a free Gemini API key in [Google AI Studio](https://aistudio.google.com/app/apikey), put it in `.env` as `GEMINI_API_KEY`, and run with `--provider gemini`. Google's [pricing page](https://ai.google.dev/gemini-api/docs/pricing) lists `gemini-3.1-flash-lite` in its free tier, and its [compatibility guide](https://ai.google.dev/gemini-api/docs/openai) documents the OpenAI-compatible endpoint. This configuration passed four live positive cases across three sites and failed one deliberately false case on 2026-11-07. These were single runs, so results may vary with model output and live-site changes. Free-tier availability and rate limits vary by account and region.

For the agent MCP server, use Python 3.11+ and install the optional extra: `pip install -e '.[agent]'`. The CLI alone still supports Python 3.10+.

## Run

```bash
testscribe run \
  --url https://www.selenium.dev/selenium/web/web-form.html \
  --test 'Enter TestScribe into the Text input field, submit the form, and verify that Received! appears.'
```

Reusable cases are JSON files with a starting `url`, a `test` instruction, and optional `vars_file`. Try the included positive and deliberately false cases:

```bash
testscribe run --case-file examples/web-form-pass.json --json
testscribe run --case-file examples/web-form-fail.json --json
```

`--json` prints a compact result with `status`, `reason`, checks, steps, and evidence paths. It is meant for coding agents and editor integrations; the complete `report.json` remains on disk. A saved case can be kept in a web app's `.testscribe/` folder and rerun after changes.

Or use `python -m src run` with the same arguments. The command prints a verdict and writes `artifacts/<timestamp>/report.json`. `--output-dir` accepts a directory, for example `artifacts/custom`; the report is written inside it as `report.json`. Exit code is `0` for PASS and `1` for FAIL or BLOCKED. A passing run saves a final-page `pass.png` by default; add `--no-pass-screenshot` to skip it. Nonpassing runs save `failure.png` and a Playwright trace when a browser page exists. Marked sensitive variables disable these artifacts unless explicitly allowed. Traces can contain typed values, so `artifacts/` is ignored by Git.

False expectation example:

```bash
testscribe run \
  --url https://www.selenium.dev/selenium/web/web-form.html \
  --test 'Submit the form and verify that Payment complete appears.'
```

PHPTRAVELS example:

```bash
testscribe run \
  --url https://phptravels.com/demo \
  --test 'Open the storefront from the demo page and verify a flight search option is shown.'
```

Three four-action cases across PHPTRAVELS, Selenium's web form, and The Internet are listed in [`smoke-cases.json`](smoke-cases.json). Run any case by passing its `url` and `test` values to `testscribe run`. Results depend on the live sites and model responses.

Gemini example (with `GEMINI_API_KEY` in `.env`):

```bash
testscribe run \
  --url https://www.selenium.dev/selenium/web/web-form.html \
  --test 'Enter TestScribe into the Text input field, submit the form, and verify that Received! appears.' \
  --provider gemini
```

Groq example (with `GROQ_API_KEY` in `.env`): `testscribe run --provider groq --case-file examples/web-form-pass.json`. The preset uses Groq's [OpenAI-compatible endpoint](https://console.groq.com/docs/openai) and [GPT OSS 120B model](https://console.groq.com/docs/model/openai/gpt-oss-120b). Provider presets select connection settings; model behavior still varies, so check the saved report.

For credentials or other variables, create an ignored file such as `demo.secrets.json` containing a JSON object: `{"CUSTOMER_EMAIL":"customer@example.com","_PASSWORD":"admin123"}`. Refer to them in the test as `{{CUSTOMER_EMAIL}}` and `{{_PASSWORD}}`, and pass `--vars-file demo.secrets.json`. A key starting with `_` marks its value as sensitive: TestScribe substitutes it locally when filling the browser, replaces exact matches (including URL-encoded forms) before model requests and in reports, and does not save screenshots, traces, or video by default. Unmarked values, such as a username, can appear in model requests. Run `testscribe --vars-file --help` for the format guide.

The target website still receives filled values. Exact-match redaction cannot cover values that the site transforms into an unrecognized form. If you intentionally need sensitive screenshots (including the default pass screenshot), traces, or video, use `--allow-sensitive-artifacts`; these files can reveal the values and should be handled privately. `--record-video` with sensitive variables requires that flag.

To watch a run, use `--headed --slow-mo 1000 --hold-seconds 10`. This delays browser actions by one second and leaves the final page open for ten seconds. In headed mode the page follows the browser window size; maximize the window manually if your desktop does not honor Chromium's maximize request. The flags are optional and do not change the assertion.

Add `--record-video` to save page video files under the chosen output directory. This captures the browser page for a walkthrough; it does not capture terminal output or narration. Sensitive runs require `--allow-sensitive-artifacts` to record video.

See [Approach and limitations](approach-and-limitations.md) for the execution flow and known boundaries.

## Coding agents

The [portable TestScribe agent skill](integrations/agent-skills/testscribe/SKILL.md) tells a coding agent when to run a browser case, how to interpret `PASS`, `FAIL`, and `BLOCKED`, and when to inspect evidence. For an agent that reads skills from `~/.agents/skills`, install it with `mkdir -p ~/.agents/skills && cp -R integrations/agent-skills/testscribe ~/.agents/skills/`. Other agents may use another skills directory. Installing the skill does not register tools; agents can always call the CLI directly.

After starting a local web app, an agent can run `testscribe run --url http://localhost:3000 --test 'Open the contact form, submit it empty, and verify that an email error appears.' --json`, inspect the returned check and evidence, change the app if needed, and rerun the same case.

For an MCP-capable agent, register a local stdio server with command `testscribe-mcp` and the API key environment variable for your chosen provider. The server provides `start_test`, `get_test_status`, and `get_test_result`. Pass `provider: "gemini"` or `provider: "groq"` to `start_test` for those presets. A long test returns a run ID immediately, so the agent can poll and receive the same checked verdict as `report.json`. Pass `no_pass_screenshot: true` to skip pass screenshots. Its artifacts default to the system temporary directory under `testscribe-runs/`; set `TESTSCRIBE_ARTIFACTS_DIR` to choose another parent directory. Keep keys in the agent's private MCP configuration, not in the repository.

## VS Code

The [VS Code extension](vscode-extension/README.md) has a chat sidebar for entering a site URL and plain-English test, running it, and inspecting the checked result, actions, and evidence. It also saves reusable JSON cases and runs them from the editor. It stores API keys in VS Code Secret Storage and requires the Python package and Chromium to be installed separately. Build a local VSIX with `cd vscode-extension && npm ci && npm run package`, or download the VSIX from the [preview releases](https://github.com/Tchaikovsky29/TestScribe/releases).
