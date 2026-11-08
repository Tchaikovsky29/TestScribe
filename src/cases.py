"""Load reusable plain-English test cases from small JSON files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class CaseFileError(ValueError):
    """A saved case cannot be run as written."""


@dataclass(frozen=True)
class CaseSpec:
    url: str
    test: str
    vars_file: Path | None = None


def load_case_file(path: Path) -> CaseSpec:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CaseFileError(f"Cannot read case file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CaseFileError("Case file must contain one JSON object")
    unknown = set(data) - {"url", "test", "vars_file"}
    if unknown:
        raise CaseFileError(f"Unknown case field(s): {', '.join(sorted(unknown))}")
    url = data.get("url")
    if not isinstance(url, str) or not url.strip():
        raise CaseFileError("Case file needs a nonempty 'url'")
    url = url.strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CaseFileError("Case 'url' must be an HTTP(S) URL")
    test = data.get("test")
    if not isinstance(test, str) or not test.strip():
        raise CaseFileError("Case file needs a nonempty 'test'")
    vars_path = data.get("vars_file")
    if vars_path is not None:
        if not isinstance(vars_path, str) or not vars_path.strip():
            raise CaseFileError("Case 'vars_file' must be a nonempty relative path")
        relative = Path(vars_path)
        if relative.is_absolute():
            raise CaseFileError("Case 'vars_file' must be relative to the case file")
        vars_file = (path.parent / relative).resolve()
    else:
        vars_file = None
    return CaseSpec(url=url, test=test.strip(), vars_file=vars_file)
