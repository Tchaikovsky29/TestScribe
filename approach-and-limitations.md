# Approach and limitations

## Approach

TestScribe takes a starting URL and a plain-English test case through `testscribe run`. The CLI loads the selected model provider and any optional values from `--vars-file`, then creates a report directory. Before opening the browser, the runner checks that the starting URL responds and asks the model to turn the case into an ordered list of action intents and explicit checks. It rejects plans without usable checks and limits the run to 12 actions and 12 model calls.

Next, Playwright opens Chromium in a fresh browser context and visits the starting page. For **each** planned action, the runner takes a new accessibility snapshot of the current page. On large pages it keeps navigation controls and selects relevant named sections so the model receives a smaller observation. An unambiguous observed click can be selected directly; otherwise the model chooses one action and identifies its target by role and accessible name. Python resolves that target against the live page and requires exactly one match before acting. It can click, fill, select a native dropdown, or press a supported key. If a target is rejected, it takes a fresh observation and gives the model one chance to correct the action. Direct URL navigation is allowed only for a URL written in the test case and checked with cURL; ordinary site navigation uses page controls.

After the actions, Python evaluates the planned checks against the browser, waiting briefly for dynamic content. A model statement that something succeeded is never the verdict. The command reports `PASS` when every check matches, `FAIL` when an expected browser condition does not match or a browser action fails, and `BLOCKED` when planning, target resolution, or the model provider prevents a reliable run. It writes `report.json` with the plan, attempted steps, checks, final URL, timing, and model usage. Nonpassing runs also save a screenshot and Playwright trace when a page is available.

The same runner has passed four-action cases on PHPTRAVELS, Selenium's web form, and The Internet using both BharatCode Qwen and the optional Gemini configuration. These are individual demonstrations, not a reliability benchmark.

## Limitations

- The model can misunderstand a case, omit an explicit step, or plan a check weaker than the intended outcome. The runner does not mechanically prove that every requested action appears in the plan. Review the plan and executed steps in the report for important flows. For example, seeing “Stripe” after selecting a Payments filter does not prove the filter worked if Stripe was already visible beforehand.
- The runner relies on accessible controls and a unique role/name match. Ambiguous or missing targets block the run. Visual-only controls, iframes, downloads, CAPTCHA, complex widgets, and automatic dismissal of unexpected popups are outside this version's tested scope.
- Live sites can change, load slowly, or reject automation. Model APIs can be slow or temporarily unavailable. The Qwen and Gemini runs above were single trials, so their pass rates and speed should not be treated as a provider comparison.
- Reports, screenshots, traces, and videos are local artifacts. Traces and URLs may contain typed values, so treat them as sensitive and keep them out of Git.
