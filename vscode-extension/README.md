# TestScribe for VS Code

Describe a browser test in the TestScribe chat sidebar, run it, and inspect the checked verdict in the conversation. The extension calls the same Python runner as the CLI and MCP server.

## Prerequisites

Install [TestScribe](https://github.com/Tchaikovsky29/TestScribe#setup), install Playwright Chromium, and configure an API key for BharatCode, Gemini, or Groq. The extension does not bundle Python, Chromium, or model access.

## Use

1. Open the TestScribe activity bar icon, or run **TestScribe: Open Chat** from the Command Palette.
2. Choose `testscribe.provider` (**BharatCode**, **Gemini**, **Groq**, or **Custom**) in VS Code Settings. Back in Chat, choose a model from the list above the conversation. Enter the website URL and a plain-English test with an expected result, then press **Enter** or **Run**. The chat shows progress, the checked `PASS`, `FAIL`, or `BLOCKED` verdict, browser actions, assertions, and report links.
3. Use **Save** to put the current test in `.testscribe/<name>.json`. Saved cases also run through **TestScribe: Run Test Case** from a JSON editor or Explorer menu.

Put the matching key (`BHARATCODE_API_KEY`, `GEMINI_API_KEY`, or `GROQ_API_KEY`) in the workspace `.env`, or use **TestScribe: Set API Key**. The command stores the key for the selected provider in VS Code Secret Storage. The extension asks the provider for its current model list when a key is available; without a key or when the catalog cannot load, the provider's default model stays selectable. The gear button opens provider and browser settings. Turn on `testscribe.headed` to watch Chromium during a run.

The extension uses the workspace `.venv/bin/testscribe` (or `.venv/Scripts/testscribe.exe` on Windows) when present, then falls back to `testscribe` on `PATH`. Set `testscribe.cliPath` if installed elsewhere. `testscribe.provider` selects the endpoint, default model, and key name. Set `testscribe.baseUrl` or `testscribe.apiKeyEnv` only to override a preset; clear old overrides to use the preset values. For **Custom**, set a base URL in Settings and enter the model ID in Chat. Model choices are saved locally per provider. The chat conversation is kept in memory for the current VS Code session.

Run artifacts are stored in VS Code's extension storage, outside the workspace. Passing runs save a final-page screenshot by default; set `testscribe.passScreenshot` to `false` to turn it off. An optional `vars_file` in a case should point to an ignored local file. Prefix sensitive variable names with `_`; the Python runner redacts exact matches in model requests and reports and skips screenshots and traces for those runs by default. Unmarked values and explicitly enabled artifacts can expose typed values. See the root README.

## Build a VSIX

```bash
cd vscode-extension
npm ci
npm run compile
npm run package
```

Install the resulting `.vsix` with **Extensions: Install from VSIX...**. The extension is also runnable from the source folder with VS Code's Extension Development Host after compilation.

The [public verification workflow](https://github.com/Tchaikovsky29/TestScribe/actions/workflows/verify.yml) builds a downloadable VSIX artifact after its CLI/MCP tests pass. This provides an early way to try the extension before Marketplace publication.

The package uses a development publisher ID. Publishing to the Marketplace requires replacing it with a publisher ID you control and completing the Marketplace publisher setup.
