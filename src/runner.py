"""Plan a test, execute browser actions, and verify the requested outcome."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

from src.browser import TargetError, check_url_exists, execute_action, explicit_urls, observe
from src.model import ModelClient, ModelError


PLAN_SYSTEM = """You convert a plain-English browser test into action intents and explicit checks.
Return only one JSON object with:
  "actions": a list of short action intents in execution order;
  "checks": a list of checks, each one of:
    {"kind":"text_visible","text":"exact words to find"}
    {"kind":"text_absent","text":"exact words that must not appear"}
    {"kind":"control_visible","text":"words describing a visible interactive option"}
    {"kind":"role_visible","role":"heading|button|link|textbox|tab","name":"accessible name"}
    {"kind":"url_contains","text":"URL substring"}
Preserve explicit expected words from the test. Include ONLY checks explicitly requested
by the test. A URL check is allowed only when the test states the expected URL/path.
The browser starts at START URL already; do not add a navigation action for it.
Keep every explicit user interaction as a separate action in the stated order, even
when a later control is already visible. For example, "Open Menu, choose Services"
requires both "Open Menu" and "Choose Services"; do not skip the menu step.
For a test that only says verify, produce no actions. Do not add scrolling or searching
as actions; Playwright checks find elements throughout the page.
Make a separate check for each distinct expected outcome joined by "and".
For an expected control or option whose exact label is unknown, use control_visible
with descriptive words copied from the case, such as "flight search". The browser
will match those words against actual interactive controls after navigation.
When using role_visible, its name must use words from the test case; never invent an
exact label on a page that has not been observed yet.
Do not turn an expected result into an action.
Do not invent credentials, URLs, or a weaker check. Use placeholders such as
{{CUSTOMER_PASSWORD}} when the case names a variable. A test with no check is invalid.
Example: "Enter Alex into Name, submit, verify Thanks appears" becomes
{"actions":["Enter Alex into Name","Submit the form"],"checks":[{"kind":"text_visible","text":"Thanks"}]}"""


ACTION_SYSTEM = """You choose ONE browser action for the current intent using only the current-page observation.
Return only a JSON object. For an element action use:
{"action":"click|fill|select|press","role":"button|link|textbox|combobox|checkbox|radio|tab|menuitem|option",
 "name":"words from the observed accessible name","section":"optional exact named region or navigation",
 "value":"text for fill/select","key":"Enter for press"}
Click the observed links and buttons to navigate around the site. Click a menu control,
then click its visible menu item. Use select ONLY for a native HTML <select> element.
When MATCHING CONTROLS contains a button or link with the requested words, click it.
Use {"action":"navigate","url":"https://..."} only when the ORIGINAL TEST contains
that exact URL. Never infer a path or URL from a page label.
Use the observed role/name and a section only when it helps make the target unique.
For icon-prefixed names, the meaningful words can be used (for example Login).
If the intent asks for a credential placeholder, return the placeholder as value; do not invent a secret.
Do not claim success, produce code, or choose a target absent from the observation."""

CHECK_KINDS = {"text_visible", "text_absent", "control_visible", "role_visible", "url_contains"}
CHECK_ROLES = {"heading", "button", "link", "textbox", "tab"}


def _grounded_words(phrase: str, case: str) -> bool:
    ignored = {"a", "an", "the", "to", "for", "of", "on", "in", "is", "shown", "visible"}
    def words(value: str) -> set[str]:
        return {word.rstrip("s") for word in re.findall(r"[a-z0-9]+", value.lower()) if word not in ignored}
    expected = words(phrase)
    return bool(expected) and expected <= words(case)


class PlanError(Exception):
    """A planned test did not contain executable checks."""


def make_plan(model: ModelClient, url: str, case: str) -> dict[str, Any]:
    prompt = f"START URL: {url}\nTEST CASE: {case}"
    data = model.json_response(PLAN_SYSTEM, prompt)
    initial_checks = data.get("checks")
    invented_role = isinstance(initial_checks, list) and any(
        isinstance(check, dict)
        and check.get("kind") == "role_visible"
        and isinstance(check.get("name"), str)
        and check["name"].lower() not in case.lower()
        for check in initial_checks
    )
    invented_url = isinstance(initial_checks, list) and any(
        isinstance(check, dict) and check.get("kind") == "url_contains"
        for check in initial_checks
    ) and not re.search(r"\b(url|path|address)\b", case, re.I)
    invented_control = isinstance(initial_checks, list) and any(
        isinstance(check, dict)
        and check.get("kind") == "control_visible"
        and isinstance(check.get("text"), str)
        and not _grounded_words(check["text"], case)
        for check in initial_checks
    )
    if invented_role or invented_url or invented_control:
        data = model.json_response(
            PLAN_SYSTEM,
            prompt + "\nCORRECTION: A previous plan invented an assertion absent from the test. Check only the stated visible outcome. Do not add a URL check unless the test explicitly asks for a URL or path, and do not invent an accessible name.",
        )
    actions, checks = data.get("actions"), data.get("checks")
    if not isinstance(actions, list) or not all(isinstance(item, str) and item.strip() for item in actions):
        raise PlanError("Model plan has invalid actions")
    if len(actions) > 12:
        raise PlanError("Model plan exceeds 12 actions")
    if not isinstance(checks, list) or not 1 <= len(checks) <= 5:
        raise PlanError("Model plan needs one to five assertions")
    for check in checks:
        if not isinstance(check, dict) or check.get("kind") not in CHECK_KINDS:
            raise PlanError("Model plan contains an unsupported assertion")
        if check["kind"] == "role_visible":
            if check.get("role") not in CHECK_ROLES or not isinstance(check.get("name"), str) or not check["name"].strip():
                raise PlanError("Role assertion needs a role and name")
            if check["name"].lower() not in case.lower():
                raise PlanError("Model invented a control name that was not requested")
        elif not isinstance(check.get("text"), str) or not check["text"].strip():
            raise PlanError("Text/URL assertion needs text")
        if check["kind"] == "url_contains" and not re.search(r"\b(url|path|address)\b", case, re.I):
            raise PlanError("Model invented a URL assertion that was not requested")
        if check["kind"] == "control_visible" and not _grounded_words(check["text"], case):
            raise PlanError("Model invented a control description that was not requested")
    actions = [
        action for action in actions
        if action.strip().lower() not in {
            f"navigate to {url}".lower(),
            f"open {url}".lower(),
        }
    ]
    if case.strip().lower().startswith(("verify ", "check ", "confirm ")):
        actions = []
    return {"actions": actions, "checks": checks}


def choose_action(
    model: ModelClient,
    case: str,
    intent: str,
    observation: str,
    history: list[dict[str, str]],
    feedback: str = "",
) -> dict[str, Any]:
    if re.match(r"(?i)^\s*(?:open|go to|navigate to|click)\b", intent):
        grounded_click = observed_click_for_intent(intent, observation)
        if grounded_click:
            return grounded_click
    prompt = (
        "ORIGINAL TEST: " + case + "\nCURRENT INTENT: " + intent
        + "\nRECENT ACTIONS: " + json.dumps(history[-3:])
        + "\nCURRENT PAGE:\n" + observation
    )
    if feedback:
        prompt += "\nPREVIOUS TARGET ERROR: " + feedback + "\nChoose a different, uniquely named target from the fresh page observation. Copy the full accessible name when needed."
    for attempt in range(2):
        data = model.json_response(ACTION_SYSTEM, prompt)
        if data.get("action") not in {"click", "fill", "select", "press", "navigate"}:
            raise ModelError(f"Model proposed an unsupported action: {data.get('action')!r}")
        if data["action"] == "navigate" and data.get("url") not in explicit_urls(case):
            fallback = observed_click_for_intent(intent, observation)
            if fallback:
                return fallback
            # The executor rejects this URL; the outer loop then waits and re-observes.
            return data
        if (
            data["action"] == "fill"
            and "shown on the page" in case.lower()
            and isinstance(data.get("value"), str)
            and data["value"] not in observation
        ):
            if attempt == 0:
                prompt += "\nCORRECTION: Copy the fill value exactly from the visible page text. The previous value was absent."
                continue
            raise ModelError("Model fill value was not found in the page observation")
        return data
    raise ModelError("Model could not choose a grounded action")


def observed_click_for_intent(intent: str, observation: str) -> dict[str, str] | None:
    """Find one observed control whose name covers the navigation intent."""
    if "MATCHING CONTROLS:\n" not in observation:
        return None
    controls = observation.split("MATCHING CONTROLS:\n", 1)[1].split("\nPAGE SECTIONS:", 1)[0]
    wanted = set(re.findall(r"[a-z0-9]+", intent.lower())) - {
        "a", "an", "and", "at", "bar", "choose", "click", "dropdown", "from", "go",
        "in", "menu", "navigate", "on", "open", "section", "select", "the", "to", "top",
    }
    if not wanted:
        return None
    ranked: list[tuple[int, str, str]] = []
    for role, name in re.findall(r'\b(button|link|tab|menuitem|option) "([^"]+)"', controls):
        score = len(wanted & set(re.findall(r"[a-z0-9]+", name.lower())))
        if score == len(wanted):
            ranked.append((score, role, name))
    if not ranked:
        return None
    ranked = list(dict.fromkeys(ranked))
    ranked.sort(reverse=True)
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    _, role, name = ranked[0]
    return {"action": "click", "role": role, "name": name}


def _any_visible(locator: Any) -> bool:
    return any(item.is_visible() for item in locator.all()[:30])


def _control_visible(page: Page, description: str) -> bool:
    words = {word.rstrip("s") for word in re.findall(r"[a-z0-9]+", description.lower())}
    words -= {"a", "an", "the", "option", "control", "button", "link", "way", "shown", "visible", "to", "for"}
    if not words:
        return False
    seen: set[str] = set()
    for role in ("button", "link", "tab", "combobox", "textbox"):
        for item in page.get_by_role(role).all()[:100]:
            if not item.is_visible():
                continue
            name = item.get_attribute("aria-label") or item.inner_text(timeout=1000)
            candidate = {word.rstrip("s") for word in re.findall(r"[a-z0-9]+", name.lower())}
            if words <= candidate:
                return True
            seen |= words & candidate
    return words <= seen


def check_once(page: Page, check: dict[str, str]) -> bool:
    kind = check["kind"]
    if kind == "url_contains":
        return check["text"].lower() in page.url.lower()
    if kind == "role_visible":
        locator = page.get_by_role(check["role"], name=re.compile(re.escape(check["name"]).replace("/", r"\/"), re.I))
        return _any_visible(locator)
    if kind == "control_visible":
        return _control_visible(page, check["text"])
    locator = page.get_by_text(check["text"], exact=False)
    visible = _any_visible(locator)
    return not visible if kind == "text_absent" else visible


def verify(page: Page, check: dict[str, str], timeout_seconds: float = 15) -> bool:
    deadline = time.monotonic() + timeout_seconds
    if check["kind"] == "text_absent":
        while time.monotonic() < deadline:
            if not check_once(page, check):
                return False
            page.wait_for_timeout(200)
        return True
    while True:
        if check_once(page, check):
            return True
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(200)


def save_failure_artifacts(page: Page, context: Any, output_dir: Path, report: dict[str, Any]) -> None:
    try:
        screenshot = output_dir / "failure.png"
        page.screenshot(path=str(screenshot), full_page=True, timeout=5000)
        report["artifacts"]["screenshot"] = str(screenshot)
    except PlaywrightError:
        pass
    try:
        trace = output_dir / "trace.zip"
        context.tracing.stop(path=str(trace))
        report["artifacts"]["trace"] = str(trace)
    except PlaywrightError:
        pass


def save_pass_screenshot(page: Page, output_dir: Path, report: dict[str, Any]) -> None:
    """Keep a final-page image without changing a verified PASS if capture fails."""
    try:
        screenshot = output_dir / "pass.png"
        page.screenshot(path=str(screenshot), full_page=True, timeout=5000)
        report["artifacts"]["screenshot"] = str(screenshot)
    except PlaywrightError:
        pass


def run_case(
    *,
    url: str,
    case: str,
    model: ModelClient,
    variables: dict[str, str],
    output_dir: Path,
    headed: bool = False,
    slow_mo: int = 0,
    hold_seconds: float = 0,
    record_video: bool = False,
    allow_sensitive_artifacts: bool = False,
    pass_screenshot: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": 1,
        "run_id": os.getenv("TESTSCRIBE_RUN_ID") or uuid.uuid4().hex,
        "status": "BLOCKED",
        "passed": False,
        "reason": "Run did not start",
        "start_url": url,
        "final_url": url,
        "test_case": case,
        "provider_url": model.base_url,
        "model": model.model,
        "steps": [],
        "checks": [],
        "model_calls": 0,
        "token_usage": [],
        "artifacts": {},
    }
    started = time.monotonic()
    page: Page | None = None
    context = None
    save_artifacts = not model.redactor.values or allow_sensitive_artifacts
    try:
        if record_video and not save_artifacts:
            raise PlanError("Video with sensitive variables requires --allow-sensitive-artifacts")
        if (
            re.search(r"\b(log\s*in|sign\s*in)\b", case, re.I)
            and not re.search(r"\b(password|credential|single sign.on|sso)\b|\{\{", case, re.I)
        ):
            raise PlanError("Login method or credentials are not specified in the test case")
        report["start_url_http_status"] = check_url_exists(url)
        plan = make_plan(model, url, case)
        report["plan"] = plan
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=not headed,
                slow_mo=slow_mo,
                args=["--start-maximized"] if headed else [],
            )
            context_options: dict[str, Any] = {"no_viewport": headed}
            if record_video:
                video_dir = output_dir / "video"
                context_options.update(
                    record_video_dir=str(video_dir),
                    record_video_size={"width": 1280, "height": 720},
                )
            context = browser.new_context(**context_options)
            if save_artifacts:
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
            try:
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                for intent in plan["actions"]:
                    feedback = ""
                    for attempt in range(2):
                        observation = observe(page, intent)
                        action = choose_action(model, case, intent, observation, report["steps"], feedback)
                        target = f"{action.get('role', '')} {action.get('name', '')}".strip()
                        step = {"instruction": intent, "action": action["action"], "target": target}
                        report["steps"].append(step)
                        try:
                            page, outcome = execute_action(page, context, action, variables, case)
                        except TargetError as exc:
                            step["outcome"] = f"Target rejected: {exc}"
                            if attempt == 0:
                                feedback = str(exc)
                                page.wait_for_timeout(600)
                                continue
                            raise
                        step["outcome"] = outcome
                        report["final_url"] = page.url
                        break
                for check in plan["checks"]:
                    passed = verify(page, check)
                    report["checks"].append({"check": check, "passed": passed})
                    if not passed:
                        report["status"] = "FAIL"
                        report["reason"] = f"Expected condition was not met: {check}"
                        break
                else:
                    report["status"] = "PASS"
                    report["passed"] = True
                    report["reason"] = "All requested checks matched the browser state"
                report["final_url"] = page.url
                if report["passed"] and save_artifacts:
                    if pass_screenshot:
                        save_pass_screenshot(page, output_dir, report)
                    context.tracing.stop()
                elif not report["passed"] and save_artifacts:
                    save_failure_artifacts(page, context, output_dir, report)
            except Exception:
                if page is not None:
                    report["final_url"] = page.url
                    if save_artifacts:
                        save_failure_artifacts(page, context, output_dir, report)
                raise
            finally:
                if headed and hold_seconds and page is not None and not page.is_closed():
                    page.wait_for_timeout(hold_seconds * 1000)
                context.close()
                if record_video:
                    report["artifacts"]["videos"] = [str(path) for path in sorted(video_dir.glob("*.webm"))]
                browser.close()
    except (ModelError, PlanError, TargetError) as exc:
        report["reason"] = str(exc)
    except PlaywrightError as exc:
        report["status"] = "FAIL"
        report["reason"] = f"Browser action failed: {str(exc).splitlines()[0]}"
    except Exception as exc:
        report["reason"] = f"Unexpected error: {type(exc).__name__}: {exc}"
    finally:
        report["model_calls"] = model.calls
        report["token_usage"] = model.usage
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report = model.redactor.redact_data(report)
        (output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
