# TestScribe for VS Code

Run a saved plain-English browser test from the editor and inspect its checked verdict in the TestScribe sidebar. The extension calls the same Python runner as the CLI and MCP server.

## Prerequisites

Install [TestScribe](https://github.com/Tchaikovsky29/TestScribe#setup), install Playwright Chromium, and configure a BharatCode API key (or another OpenAI-compatible provider). The extension does not bundle Python, Chromium, or model access.

## Use

1. Run **TestScribe: New Test Case** from the Command Palette. It creates `.testscribe/<name>.json` in the open workspace.
2. Replace the template URL and test with a reachable page and a plain-English action plus expected result.
3. Run **TestScribe: Set API Key**. The key is stored in VS Code Secret Storage.
4. Run **TestScribe: Run Test Case** from the JSON editor or file's Explorer menu. The sidebar shows `PASS`, `FAIL`, or `BLOCKED` with checked expectations and a link to the full report.

The extension uses the workspace `.venv/bin/testscribe` (or `.venv/Scripts/testscribe.exe` on Windows) when present, then falls back to `testscribe` on `PATH`. Set `testscribe.cliPath` if installed elsewhere. Configure `testscribe.model`, `testscribe.baseUrl`, and `testscribe.apiKeyEnv` to use another provider. For Gemini, use `gemini-3.1-flash-lite`, `https://generativelanguage.googleapis.com/v1beta/openai/`, and `GEMINI_API_KEY` respectively.

Run artifacts are stored in VS Code's extension storage, outside the workspace. They can contain typed values or page contents. An optional `vars_file` in a case should point to an ignored local file; see the root README.

## Build a VSIX

```bash
cd vscode-extension
npm ci
npm run compile
npm run package
```

Install the resulting `.vsix` with **Extensions: Install from VSIX...**. The extension is also runnable from the source folder with VS Code's Extension Development Host after compilation.

The package uses a development publisher ID. Publishing to the Marketplace requires replacing it with a publisher ID you control and completing the Marketplace publisher setup.
