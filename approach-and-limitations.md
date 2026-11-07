# Approach and limitations

## Approach

1. **Read the test.** `testscribe run` accepts a starting URL and a plain-English test case. The CLI loads the selected model provider, optional `--vars-file` values, and the report directory.
2. **Check and plan.** Before opening a browser, the runner checks that the starting URL responds. It asks the model for an ordered list of action intents and explicit checks, rejects plans without usable checks, and limits a run to 12 actions and 12 model calls.
3. **Open the page.** Playwright starts Chromium in a fresh browser context and visits the starting URL.
4. **Observe each step.** Before every planned action, the runner takes a new accessibility snapshot of the current page. For large pages, it keeps navigation controls and relevant named sections to reduce the observation sent to the model.
5. **Choose and execute the action.** An unambiguous observed click can be selected directly; otherwise the model chooses an action using a role and accessible name. Python requires exactly one live target, then clicks, fills, selects a native dropdown, or presses a supported key. If target resolution fails, it observes the page again and allows one correction. Direct navigation is allowed only to a URL written in the test case and checked with cURL; other navigation uses page controls.
6. **Verify the outcome.** After all actions, Python checks the requested conditions in the browser, waiting briefly for dynamic content. The model's claim of success is never used as the verdict.
7. **Write the result.** The command returns `PASS` when every check matches, `FAIL` when a check or browser action fails, and `BLOCKED` when planning, target resolution, or the model provider prevents a reliable run. `report.json` records the plan, attempted steps, checks, final URL, timing, and model usage. Nonpassing runs also save a screenshot and Playwright trace when a page is available.

The same runner has passed four-action cases on PHPTRAVELS, Selenium's web form, and The Internet using both BharatCode Qwen and the optional Gemini configuration. These are individual demonstrations, not a reliability benchmark.

## Limitations

- The model can misunderstand a case, omit an explicit step, or plan a check weaker than the intended outcome. The runner does not mechanically prove that every requested action appears in the plan. Review the plan and executed steps in the report for important flows. For example, seeing “Stripe” after selecting a Payments filter does not prove the filter worked if Stripe was already visible beforehand.
- The runner relies on accessible controls and a unique role/name match. Ambiguous or missing targets block the run. Visual-only controls, iframes, downloads, CAPTCHA, complex widgets, and automatic dismissal of unexpected popups are outside this version's tested scope.
- Live sites can change, load slowly, or reject automation. Model APIs can be slow or temporarily unavailable. The Qwen and Gemini runs above were single trials, so their pass rates and speed should not be treated as a provider comparison.
- Reports, screenshots, traces, and videos are local artifacts. Traces and URLs may contain typed values, so treat them as sensitive and keep them out of Git.
