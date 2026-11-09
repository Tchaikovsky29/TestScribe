"""Defaults for supported OpenAI-compatible model providers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    model: str
    api_key_env: str


PRESETS: dict[str, ProviderConfig] = {
    "bharatcode": ProviderConfig(
        "bharatcode", "https://bharatcode.ai/api/model/v1", "qwen-3.8-27b", "BHARATCODE_API_KEY"
    ),
    "gemini": ProviderConfig(
        "gemini", "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-3.1-flash-lite", "GEMINI_API_KEY"
    ),
    "groq": ProviderConfig(
        "groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "GROQ_API_KEY"
    ),
}


def resolve_provider(
    name: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
) -> ProviderConfig:
    """Apply optional overrides to a preset, or require an endpoint and model for custom."""
    if name == "custom":
        if not base_url or not model:
            raise ValueError("--provider custom requires --base-url and --model")
        default = ProviderConfig("custom", base_url, model, "OPENAI_API_KEY")
    else:
        try:
            default = PRESETS[name]
        except KeyError as exc:
            raise ValueError(f"Unknown provider: {name}") from exc
    selected = ProviderConfig(
        name, base_url or default.base_url, model or default.model,
        api_key_env or default.api_key_env,
    )
    if not selected.base_url.startswith(("https://", "http://")):
        raise ValueError("Provider base URL must be an HTTP(S) URL")
    return selected
