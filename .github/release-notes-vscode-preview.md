TestScribe now has a chat sidebar in VS Code. Enter a website URL and plain-English test, run it, and inspect the checked PASS, FAIL, or BLOCKED verdict with browser actions, assertions, and report links. You can still save reusable JSON cases and run them from the editor.

Install the attached `.vsix` through **Extensions: Install from VSIX...**. This extension also needs the [TestScribe Python package and Playwright Chromium](https://github.com/Tchaikovsky29/TestScribe#setup), plus a BharatCode or compatible model API key. Run **TestScribe: Set API Key** after installation, or keep the key in your workspace `.env`.

Coding agents can use the same runner through its CLI, portable skill, and MCP tools. See the [repository README](https://github.com/Tchaikovsky29/TestScribe) for commands and limitations. Model calls can be slow; one live Qwen editor run took about 3.5 minutes.
