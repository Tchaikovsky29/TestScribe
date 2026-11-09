"""Keep marked variable values out of model requests and text reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, quote_plus


@dataclass(frozen=True)
class SecretRedactor:
    values: tuple[str, ...] = ()

    @classmethod
    def from_variables(cls, variables: dict[str, str]) -> SecretRedactor:
        return cls(tuple(value for name, value in variables.items() if name.startswith("_") and value))

    def redact(self, text: str) -> str:
        variants = {
            variant
            for value in self.values
            for variant in (value, quote(value, safe=""), quote_plus(value, safe=""))
            if variant
        }
        for value in sorted(variants, key=len, reverse=True):
            text = text.replace(value, "[REDACTED]")
        return text

    def redact_data(self, data: Any) -> Any:
        if isinstance(data, str):
            return self.redact(data)
        if isinstance(data, list):
            return [self.redact_data(item) for item in data]
        if isinstance(data, dict):
            return {key: self.redact_data(value) for key, value in data.items()}
        return data
