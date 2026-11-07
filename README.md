# TestScribe

TestScribe runs a plain-English test case in Chromium and reports `PASS`, `FAIL`, or `BLOCKED`. It uses an AI model to turn the case into browser actions, Playwright to find and operate page elements, and code to check the requested result. The same runner works across sites; no PHPTRAVELS selectors or flows are embedded in it.

## Setup

Requires Python 3.10+, cURL, and an API key for an OpenAI-compatible chat endpoint.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
cp .env.example .env
```

Set `BHARATCODE_API_KEY` in `.env`. The default model is BharatCode `qwen-3.8-27b`.

**No paid subscription option:** Create a free Gemini API key in [Google AI Studio](https://aistudio.google.com/app/apikey), put it in `.env` as `GEMINI_API_KEY`, and pass the Gemini settings shown below. Google's [pricing page](https://ai.google.dev/gemini-api/docs/pricing) lists `gemini-3.1-flash-lite` in its free tier, and its [compatibility guide](https://ai.google.dev/gemini-api/docs/openai) documents the OpenAI-compatible endpoint. This configuration passed four live positive cases across three sites and failed one deliberately false case on 2026-11-07. These were single runs, so results may vary with model output and live-site changes. Free-tier availability and rate limits vary by account and region.

## Run

```bash
testscribe run \
  --url https://www.selenium.dev/selenium/web/web-form.html \
  --test 'Enter TestScribe into the Text input field, submit the form, and verify that Received! appears.'
```

Or use `python -m src run` with the same arguments. The command prints a verdict and writes `artifacts/<timestamp>/report.json`. `--output-dir` accepts a directory, for example `artifacts/custom`; the report is written inside it as `report.json`. Exit code is `0` for PASS and `1` for FAIL or BLOCKED. Nonpassing runs also save a screenshot and Playwright trace when a browser page exists. Traces can contain typed values, so `artifacts/` is ignored by Git.

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

Gemini free-tier example:

```bash
testscribe run \
  --url https://www.selenium.dev/selenium/web/web-form.html \
  --test 'Enter TestScribe into the Text input field, submit the form, and verify that Received! appears.' \
  --base-url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --model gemini-3.1-flash-lite \
  --api-key-env GEMINI_API_KEY
```

For credentials or other variables, create an ignored file such as `demo.secrets.json` containing a JSON object: `{"CUSTOMER_EMAIL":"...","CUSTOMER_PASSWORD":"..."}`. Refer to them in the test as `{{CUSTOMER_EMAIL}}` and `{{CUSTOMER_PASSWORD}}`, and pass `--vars-file demo.secrets.json`. Run `testscribe --vars-file --help` for a complete example and file format guide.

To watch a run, use `--headed --slow-mo 1000 --hold-seconds 10`. This delays browser actions by one second and leaves the final page open for ten seconds. In headed mode the page follows the browser window size; maximize the window manually if your desktop does not honor Chromium's maximize request. The flags are optional and do not change the assertion.

Add `--record-video` to save page video files under the chosen output directory. This captures the browser page for a walkthrough; it does not capture terminal output or narration.

## Approach and limitations

The model first creates a short action plan and explicit checks. Before each action, the runner sends a fresh ARIA snapshot of the current page. Large pages retain header navigation while narrowing main content to named regions. The runner clicks observed controls to move around a site. It accepts a direct navigation URL only when that exact URL appears in the test case and cURL confirms it responds successfully; the starting `--url` gets the same preflight check. Playwright resolves the model's role and accessible name against the live DOM; ambiguous or absent targets block the run. A model sentence saying something worked never counts as proof: the runner evaluates the planned check in the browser. A run uses at most 12 model calls. The JSON report includes the plan, actions, checks, final URL, time, token usage, and failure artifacts.

This is a small screening project, not a general autonomous QA system. It handles ordinary visible controls and text/role/URL assertions; visual-only UI, iframes, downloads, CAPTCHA, complex widgets, and multi-page workflows may need more work. The model may misunderstand an instruction or choose a check weaker than the intended outcome. Live demo sites can change or block automation. A false expectation should fail, while missing credentials, ambiguous targets, and provider errors should return BLOCKED. See the short [approach and limitations note](approach-and-limitations.md).
