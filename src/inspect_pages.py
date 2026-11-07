"""Inspect public pages for TestScribe's browser-observation spike.

Usage:
    python -m src.inspect_pages --output-dir /tmp/testscribe-observations URL [URL ...]

This is a research tool. It does not execute a natural-language test case.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error, sync_playwright


CANDIDATE_SCRIPT = """elements => elements.map((element, index) => {
  const rect = element.getBoundingClientRect();
  const style = getComputedStyle(element);
  const labels = element.labels ? [...element.labels].map(label => label.innerText.trim()) : [];
  const visible = rect.width > 0 && rect.height > 0 &&
    style.display !== 'none' && style.visibility !== 'hidden';
  return {
    index,
    tag: element.tagName.toLowerCase(),
    role: element.getAttribute('role'),
    text: (element.innerText || '').trim().slice(0, 160),
    label: labels.join(' ').slice(0, 160),
    aria_label: element.getAttribute('aria-label'),
    placeholder: element.getAttribute('placeholder'),
    type: element.getAttribute('type'),
    href: element.getAttribute('href'),
    visible
  };
}).filter(item => item.visible)"""


def slug(url: str) -> str:
    parsed = urlparse(url)
    name = f"{parsed.netloc}-{parsed.path.strip('/')}".strip("-")
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", name)[:80] or "page"


def inspect(url: str, output_dir: Path, popup_link: str | None = None) -> dict:
    result: dict = {"requested_url": url}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            result["http_status"] = response.status if response else None
        except Error as exc:
            result["navigation_error"] = str(exc).splitlines()[0]

        page.wait_for_timeout(1000)

        result["final_url"] = page.url
        result["title"] = page.title()
        result["frames"] = [frame.url for frame in page.frames]
        snapshot = page.aria_snapshot()
        candidates = page.locator(
            "a, button, input, select, textarea, [role=button], [role=link], "
            "[role=textbox], [role=tab], [role=combobox], [role=checkbox], "
            "[role=radio], [role=menuitem], [role=option]"
        ).evaluate_all(CANDIDATE_SCRIPT)
        result["aria_snapshot"] = snapshot
        result["aria_snapshot_chars"] = len(snapshot)
        result["visible_candidate_count"] = len(candidates)
        result["visible_candidates"] = candidates

        if popup_link:
            link = page.get_by_role("link", name=popup_link)
            result["popup_link_matches"] = link.count()
            if link.count() == 1:
                try:
                    with page.expect_popup(timeout=10000) as popup_info:
                        link.click()
                    popup = popup_info.value
                    popup.wait_for_load_state("domcontentloaded", timeout=30000)
                    popup.wait_for_timeout(1000)
                    result["popup"] = {
                        "url": popup.url,
                        "title": popup.title(),
                        "aria_snapshot": popup.aria_snapshot(),
                    }
                except Error as exc:
                    result["popup_error"] = str(exc).splitlines()[0]
        context.close()
        browser.close()

    output_path = output_dir / f"{slug(url)}.json"
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return {key: result.get(key) for key in (
        "requested_url", "http_status", "navigation_error", "final_url", "title",
        "frames", "aria_snapshot_chars", "visible_candidate_count"
    )} | {"popup_link_matches": result.get("popup_link_matches"),
         "popup_error": result.get("popup_error"),
         "popup_url": result.get("popup", {}).get("url"),
         "popup_title": result.get("popup", {}).get("title"),
         "output_path": str(output_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+", help="Public pages to inspect")
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/testscribe-observations"))
    parser.add_argument("--popup-link", help="Follow one uniquely named link that opens a new tab")
    args = parser.parse_args()
    if args.popup_link and len(args.urls) != 1:
        parser.error("--popup-link requires exactly one URL")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for url in args.urls:
        try:
            print(json.dumps(inspect(url, args.output_dir, args.popup_link), ensure_ascii=False))
        except Error as exc:
            print(json.dumps({"requested_url": url, "error": str(exc).splitlines()[0]}))


if __name__ == "__main__":
    main()
