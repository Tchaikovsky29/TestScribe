"""Current-page observation, target resolution, and browser actions."""

from __future__ import annotations
import re
import subprocess
from typing import Any
from playwright.sync_api import BrowserContext, Locator, Page

class TargetError(Exception):
    """A proposed browser target could not be resolved uniquely."""

STOP_WORDS = {"a", "an", "as", "at", "by", "for", "in", "is", "of", "on", "the", "to", "with"}
ROLES = {"button", "link", "textbox", "combobox", "checkbox", "radio", "tab", "menuitem", "option", "cell", "text"}
ACTIONS = {"click", "fill", "select", "press", "navigate"}
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")


def _terms(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", value.lower()) if word not in STOP_WORDS}


def explicit_urls(case: str) -> set[str]:
    """Extract literal HTTP URLs supplied in the test case."""
    return {match.rstrip(".,;!?)]}") for match in URL_PATTERN.findall(case)}


def check_url_exists(url: str) -> int:
    """Check a user-provided URL with cURL before opening it in Chromium."""
    if not url.startswith(("https://", "http://")):
        raise TargetError("Navigation requires an HTTP(S) URL")
    base = [
        "curl", "--location", "--silent", "--show-error",
        "--output", "/dev/null", "--write-out", "%{http_code}",
        "--max-time", "10", "--max-redirs", "5",
        "--proto", "=http,https", "--proto-redir", "=http,https",
    ]

    def request(options: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                base + options + ["--url", url],
                capture_output=True, text=True, timeout=12, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TargetError(f"cURL could not check {url}: {exc}") from exc

    result = request(["--head"])
    if result.stdout.strip() in {"403", "405", "501"}:
        # Some sites refuse HEAD even though a browser GET succeeds.
        result = request(["--range", "0-0", "--max-filesize", "1048576"])
    status = result.stdout.strip()
    if result.returncode not in {0, 63} or not status.isdigit() or not 200 <= int(status) < 400:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else f"HTTP {status or 'unknown'}"
        raise TargetError(f"URL preflight failed for {url}: {detail}")
    return int(status)


def observe(page: Page, intent: str, budget: int = 8000) -> str:
    """Return a full small-page snapshot or selected sections of a large page."""
    snapshot = page.aria_snapshot()
    header = f"URL: {page.url}\nTITLE: {page.title()}\n"
    if len(snapshot) <= budget:
        return header + "PAGE SNAPSHOT:\n" + snapshot

    # The main content can be huge, but navigation is essential for moving between pages.
    banners = [item for item in page.get_by_role("banner").all() if item.is_visible()]
    if banners:
        nav_snapshot = banners[0].aria_snapshot()
    else:
        navigation = page.get_by_role("navigation").all()
        nav_snapshot = "\n".join(item.aria_snapshot() for item in navigation if item.is_visible())
    navigation_context = "PAGE HEADER AND NAVIGATION:\n" + nav_snapshot[:min(3000, budget // 2)] + "\n"

    intent_terms = _terms(intent)
    matching_controls: list[tuple[int, str]] = []
    for line in snapshot.splitlines():
        if not re.search(r'\b(?:button|link|tab|menuitem|option|combobox|textbox) "', line):
            continue
        score = len(intent_terms & _terms(line))
        if score:
            matching_controls.append((score, line.strip()))
    matching_controls.sort(key=lambda item: item[0], reverse=True)
    matching_context = "MATCHING CONTROLS:\n" + "\n".join(
        dict.fromkeys(line for _, line in matching_controls[:15])
    )[:1200] + "\n"

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
        half = budget // 2
        return (header + "PAGE SNAPSHOT (bounded):\n" + snapshot[:half]
                + "\n... [middle omitted] ...\n" + snapshot[-half:])

    regions.sort(key=lambda item: item[0], reverse=True)
    outline = "\n".join(f"- {name}" for _, name, _ in regions)[:1200]
    material = header + navigation_context + matching_context + "PAGE SECTIONS:\n" + outline + "\nRELEVANT SECTIONS:\n"
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
        candidates = [page.get_by_role(kind, name=section, exact=True) for kind in ("region", "navigation", "dialog", "form")]
        counts = [candidate.count() for candidate in candidates]
        if sum(counts) != 1:
            raise TargetError(f"Section {section!r} matched {sum(counts)} named containers")
        scope = candidates[counts.index(1)]
    # Playwright serializes this regex into a /.../ selector; escape the delimiter too.
    pattern = re.compile(re.escape(name).replace("/", r"\/"), re.IGNORECASE)
    if role == "text":
        locator = scope.get_by_text(pattern).filter(visible=True)
        if locator.count() == 0:
            # A snapshot can flatten an option's city, airport, and code into
            # one line even though the page renders them in separate children.
            words = name.split()
            for length in range(len(words) - 1, 1, -1):
                prefix = " ".join(words[:length])
                candidate = scope.get_by_text(
                    re.compile(re.escape(prefix).replace("/", r"\/"), re.IGNORECASE)
                ).filter(visible=True)
                if candidate.count() == 1:
                    locator = candidate
                    break
    else:
        locator = scope.get_by_role(role, name=pattern)
    count = locator.count()
    if count == 0 and role in {"textbox", "combobox"}:
        locator = scope.get_by_label(pattern)
        count = locator.count()
    if count != 1:
        raise TargetError(f"{role} {name!r} matched {count} elements")
    return locator


def inspect_action_targets(page: Page, action: dict[str, Any], intent: str) -> str:
    """Give a retry concrete live controls and context after target resolution fails."""
    terms = _terms(intent)
    ranked: list[tuple[int, str]] = []
    for line in page.aria_snapshot().splitlines():
        if not re.search(r'\b(?:button|link|tab|menuitem|option|combobox|textbox|radio|checkbox) "', line):
            continue
        score = len(terms & _terms(line))
        if score:
            ranked.append((score, line.strip()[:220]))
    ranked.sort(key=lambda item: item[0], reverse=True)
    lines = ["LIVE TARGET INSPECTION (current page):"]
    lines.extend(dict.fromkeys(line for _, line in ranked[:12]))
    role, name = action.get("role"), action.get("name")
    if role in ROLES - {"text", "cell"} and isinstance(name, str) and name:
        try:
            matches = page.get_by_role(role, name=re.compile(re.escape(name).replace("/", r"\/"), re.I)).all()[:5]
            for index, match in enumerate(matches, 1):
                if not match.is_visible():
                    continue
                context = match.evaluate("""element => {
                    const parent = element.closest('[role="region"], [role="navigation"], [role="dialog"], form, nav') || element.parentElement;
                    return (parent?.getAttribute('aria-label') || parent?.innerText || '').replace(/\\s+/g, ' ').slice(0, 160);
                }""")
                lines.append(f"Candidate {index} context: {context}")
        except Exception:
            pass
    return "\n".join(lines)[:2500]


def execute_action(
    page: Page,
    context: BrowserContext,
    action: dict[str, Any],
    variables: dict[str, str],
    case: str,
) -> tuple[Page, str]:
    kind = action.get("action")
    if kind not in ACTIONS:
        raise TargetError(f"Unsupported action: {kind!r}")
    if kind == "navigate":
        url = action.get("url")
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            raise TargetError("Navigate action requires an HTTP(S) URL")
        if url not in explicit_urls(case):
            raise TargetError("Navigation URL was not explicitly supplied in the test case; use a page control")
        if url.rstrip("/") == page.url.rstrip("/"):
            raise TargetError("Navigation would leave the browser on the same page")
        http_status = check_url_exists(url)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return page, f"Navigated to {page.url} after cURL HTTP {http_status}"

    role = action.get("role")
    name = action.get("name")
    section = action.get("section")
    if not isinstance(role, str) or not isinstance(name, str):
        raise TargetError("Action requires a role and name")
    if role in {"text", "cell"} and kind != "click":
        raise TargetError(f"{role} targets can only be clicked")
    if section is not None and not isinstance(section, str):
        raise TargetError("Section must be a string")
    locator = resolve_target(page, role, name, section)
    before_pages = len(context.pages)
    before_url = page.url
    if kind == "click":
        if locator.get_attribute("target") == "_blank":
            with context.expect_page(timeout=15000) as popup_info:
                locator.click(timeout=10000)
            page = popup_info.value
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        else:
            locator.click(timeout=10000)
        if page.url != before_url:
            # Client-side routers can update the address before replacing page content.
            page.wait_for_timeout(600)
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
        tag = locator.evaluate("element => element.tagName.toLowerCase()")
        if tag != "select":
            raise TargetError(f"select requires a native <select>, but {role} {name!r} is <{tag}>; click the menu control and option instead")
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
