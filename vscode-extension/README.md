# TestScribe for VS Code

Describe a browser test in the TestScribe chat sidebar, run it, and inspect the checked verdict in the conversation. The extension calls the same Python runner as the CLI and MCP server.

## Prerequisites

Install [TestScribe](https://github.com/Tchaikovsky29/TestScribe#setup), install Playwright Chromium, and configure a BharatCode API key (or another OpenAI-compatible provider). The extension does not bundle Python, Chromium, or model access.

## Use

1. Open the TestScribe activity bar icon, or run **TestScribe: Open Chat** from the Command Palette.
2. Enter the website URL and a plain-English test with an expected result. Press **Enter** or **Run**. The chat shows progress, the checked `PASS`, `FAIL`, or `BLOCKED` verdict, browser actions, assertions, and report links.
3. Use **Save** to put the current test in `.testscribe/<name>.json`. Saved cases also run through **TestScribe: Run Test Case** from a JSON editor or Explorer menu.

If there is no workspace `.env` or configured environment variable, use **TestScribe: Set API Key**. The key is stored in VS Code Secret Storage. The gear button opens provider and browser settings. Turn on `testscribe.headed` to watch Chromium during a run.

The extension uses the workspace `.venv/bin/testscribe` (or `.venv/Scripts/testscribe.exe` on Windows) when present, then falls back to `testscribe` on `PATH`. Set `testscribe.cliPath` if installed elsewhere. Configure `testscribe.model`, `testscribe.baseUrl`, and `testscribe.apiKeyEnv` to use another provider. For Gemini, use `gemini-3.1-flash-lite`, `https://generativelanguage.googleapis.com/v1beta/openai/`, and `GEMINI_API_KEY` respectively. The chat conversation is kept in memory for the current VS Code session.

Run artifacts are stored in VS Code's extension storage, outside the workspace. They can contain typed values or page contents. An optional `vars_file` in a case should point to an ignored local file; see the root README.

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
