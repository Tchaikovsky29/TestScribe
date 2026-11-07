"""Current-page observation, target resolution, and browser actions."""

from __future__ import annotations
import re
from typing import Any
from playwright.sync_api import BrowserContext, Locator, Page

class TargetError(Exception):
    """A proposed browser target could not be resolved uniquely."""

STOP_WORDS = {"a", "an", "as", "at", "by", "for", "in", "is", "of", "on", "the", "to", "with"}
ROLES = {"button", "link", "textbox", "combobox", "checkbox", "radio", "tab", "menuitem", "option"}
ACTIONS = {"click", "fill", "select", "press", "navigate"}


def _terms(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", value.lower()) if word not in STOP_WORDS}


def observe(page: Page, intent: str, budget: int = 8000) -> str:
    """Return a full small-page snapshot or selected sections of a large page."""
    snapshot = page.aria_snapshot()
    header = f"URL: {page.url}\nTITLE: {page.title()}\n"
    if len(snapshot) <= budget:
        return header + "PAGE SNAPSHOT:\n" + snapshot

    intent_terms = _terms(intent)
    regions: list[tuple[int, str, str]] = []
    for region in page.get_by_role("region").all():
        region_snapshot = region.aria_snapshot()
        first_line = region_snapshot.splitlines()[0] if region_snapshot else ""
        match = re.search(r'region "([^"]+)"', first_line)
        if not match:
            continue
        name = match.group(1)
        score = len(intent_terms & _terms(region_snapshot))
        if intent.lower() in region_snapshot.lower():
            score += 3
        regions.append((score, name, region_snapshot))

    if not regions:
        return header + "PAGE SNAPSHOT (bounded):\n" + snapshot[:budget]

    regions.sort(key=lambda item: item[0], reverse=True)
    outline = "\n".join(f"- {name}" for _, name, _ in regions)
    material = header + "PAGE SECTIONS:\n" + outline + "\nRELEVANT SECTIONS:\n"
    used = len(material)
    added = 0
    for score, name, region_snapshot in regions:
        if added >= 2 or (added > 0 and score == 0):
            break
        section = f"\nSECTION {name}:\n{region_snapshot}\n"
        if used + len(section) > budget:
            section = section[:max(0, budget - used)]
        if section:
            material += section
            used += len(section)
            added += 1
        if used >= budget:
            break
    return material


def resolve_target(page: Page, role: str, name: str, section: str | None = None) -> Locator:
    if role not in ROLES:
        raise TargetError(f"Unsupported target role: {role}")
    if not name:
        raise TargetError("Target has no name")
    scope: Page | Locator = page
    if section:
        region = page.get_by_role("region", name=section, exact=True)
        if region.count() != 1:
            raise TargetError(f"Section {section!r} matched {region.count()} regions")
        scope = region
    pattern = re.compile(re.escape(name), re.IGNORECASE)
    locator = scope.get_by_role(role, name=pattern)
    count = locator.count()
    if count == 0 and role in {"textbox", "combobox"}:
        locator = scope.get_by_label(pattern)
        count = locator.count()
    if count != 1:
        raise TargetError(f"{role} {name!r} matched {count} elements")
    return locator


def execute_action(
    page: Page,
    context: BrowserContext,
    action: dict[str, Any],
    variables: dict[str, str],
) -> tuple[Page, str]:
    kind = action.get("action")
    if kind not in ACTIONS:
        raise TargetError(f"Unsupported action: {kind!r}")
    if kind == "navigate":
        url = action.get("url")
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            raise TargetError("Navigate action requires an HTTP(S) URL")
        if url.rstrip("/") == page.url.rstrip("/"):
            raise TargetError("Navigation would leave the browser on the same page")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return page, f"Navigated to {page.url}"

    role = action.get("role")
    name = action.get("name")
    section = action.get("section")
    if not isinstance(role, str) or not isinstance(name, str):
        raise TargetError("Action requires a role and name")
    if section is not None and not isinstance(section, str):
        raise TargetError("Section must be a string")
    locator = resolve_target(page, role, name, section)
    before_pages = len(context.pages)
    if kind == "click":
        if locator.get_attribute("target") == "_blank":
            with context.expect_page(timeout=15000) as popup_info:
                locator.click(timeout=10000)
            page = popup_info.value
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        else:
            locator.click(timeout=10000)
    elif kind == "fill":
        value = action.get("value")
        if not isinstance(value, str):
            raise TargetError("Fill action requires text")
        for key, replacement in variables.items():
            value = value.replace("{{" + key + "}}", replacement)
        if "{{" in value:
            raise TargetError("Fill value contains an unresolved variable")
        locator.fill(value, timeout=10000)
    elif kind == "select":
        value = action.get("value")
        if not isinstance(value, str):
            raise TargetError("Select action requires a value")
        locator.select_option(label=value, timeout=10000)
    elif kind == "press":
        key = action.get("key")
        if not isinstance(key, str) or key not in {"Enter", "Tab", "Escape", "ArrowDown", "ArrowUp"}:
            raise TargetError("Unsupported keyboard key")
        locator.press(key, timeout=10000)
    if len(context.pages) > before_pages and page != context.pages[-1]:
        page = context.pages[-1]
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    return page, f"{kind} {role} {name!r}; now at {page.url}"
