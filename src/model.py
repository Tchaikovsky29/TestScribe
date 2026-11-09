"""Small OpenAI-compatible chat adapter with strict JSON parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from src.secrets import SecretRedactor


class ModelError(Exception):
    """The model did not return a usable decision."""


@dataclass
class ModelClient:
    api_key: str
    base_url: str
    model: str
    max_calls: int = 12
    redactor: SecretRedactor = SecretRedactor()

    def __post_init__(self) -> None:
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url.rstrip("/"),
            timeout=60,
            max_retries=1,
        )
        self.calls = 0
        self.usage: list[dict[str, int | None]] = []

    def json_response(self, system: str, user: str) -> dict[str, Any]:
        if self.calls >= self.max_calls:
            raise ModelError(f"Model call limit ({self.max_calls}) reached")
        self.calls += 1
        options: dict[str, Any] = {}
        if "bharatcode.ai" in self.base_url:
            options["extra_body"] = {"reasoning_effort": "none"}
        system = self.redactor.redact(system)
        user = self.redactor.redact(user)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=2048,
                **options,
            )
        except Exception as exc:
            raise ModelError(f"Model request failed: {type(exc).__name__}: {exc}") from exc

        if response.usage:
            self.usage.append({
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            })
        choice = response.choices[0] if response.choices else None
        if choice is None or choice.finish_reason == "length":
            raise ModelError("Model response was incomplete")
        content = choice.message.content
        if not isinstance(content, str) or not content.strip():
            raise ModelError("Model returned no text")
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end < start:
            raise ModelError("Model returned no JSON object")
        try:
            data = json.loads(content[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ModelError(f"Model returned invalid JSON: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise ModelError("Model JSON must be an object")
        return data
