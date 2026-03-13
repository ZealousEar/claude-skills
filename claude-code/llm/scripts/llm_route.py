#!/usr/bin/env python3
"""Universal LLM Router — routes prompts to any model across all providers.

CLI-first for Codex/Kimi/Claude (zero cost), Google API for Gemini,
OpenRouter for everything else. Stdlib only — no pip dependencies.

Usage:
    python3 llm_route.py --model opus --prompt "Say hello in 3 words"
    python3 llm_route.py --model chatgpt-5.4 --prompt-file prompt.txt --system "You are..."
    python3 llm_route.py --model gemini-3-pro --prompt "Explain X" --json
    python3 llm_route.py --model opus --prompt "Hello" --route openrouter
    python3 llm_route.py --list-models [--all] [--tier 1]
    python3 llm_route.py --list-providers
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SKILL_DIR = Path.home() / ".claude" / "skills" / "llm"
REGISTRY_PATH = SKILL_DIR / "settings" / "model-registry.json"
PROMPTING_PATH = SKILL_DIR / "settings" / "prompting-overrides.json"
ROUTING_RULES_PATH = SKILL_DIR / "settings" / "routing-rules.json"

# Fallback credential locations (checked in order)
DEBATE_AGENT_ENV = (
    Path.home() / ".claude" / "skills" / "convolutional-debate-agent"
    / "api-keys" / "provider-keys.env"
)

# Defaults
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.7
DEFAULT_CLI_TIMEOUT = 600
DEFAULT_TIMEOUT = 120

# Caches (loaded once per process)
_PROMPTING_CACHE: dict | None = None
_REGISTRY_CACHE: dict | None = None

# ---------------------------------------------------------------------------
# Registry + credential loading
# ---------------------------------------------------------------------------

def load_registry(path: Path = REGISTRY_PATH) -> dict:
    """Load model registry from JSON file."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE
    if not path.exists():
        raise FileNotFoundError(f"Model registry not found: {path}")
    _REGISTRY_CACHE = json.loads(path.read_text())
    return _REGISTRY_CACHE


def load_prompting_config() -> dict:
    """Load per-model prompting overrides from prompting-overrides.json."""
    global _PROMPTING_CACHE
    if _PROMPTING_CACHE is not None:
        return _PROMPTING_CACHE
    if PROMPTING_PATH.exists():
        _PROMPTING_CACHE = json.loads(PROMPTING_PATH.read_text())
    else:
        _PROMPTING_CACHE = {"defaults": {}, "models": {}}
    return _PROMPTING_CACHE


def load_env_file(env_path: Path) -> dict[str, str]:
    """Load key=value pairs from an env file."""
    env: dict[str, str] = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and value:
                env[key] = value
    return env


def get_api_key(env_key: str) -> str:
    """Get API key: env vars -> debate agent keys -> error with setup instructions."""
    # 1. Environment variable
    key = os.environ.get(env_key)
    if key:
        return key

    # 2. Debate agent's provider-keys.env (shared credentials)
    env = load_env_file(DEBATE_AGENT_ENV)
    key = env.get(env_key)
    if key:
        return key

    raise ValueError(
        f"API key '{env_key}' not found.\n"
        f"  Set it as an environment variable, or add it to:\n"
        f"  {DEBATE_AGENT_ENV}\n"
        f"  See: ~/.claude/skills/llm/references/provider-setup.md"
    )


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------

def apply_prompting_overrides(
    model_name: str,
    system: str | None,
    temperature: float,
    prompting_cfg: dict,
) -> tuple[str | None, float]:
    """Apply model-specific system prompt wrapping and temperature override."""
    model_cfg = prompting_cfg.get("models", {}).get(model_name, {})

    # Temperature override (null means keep caller's default)
    temp_override = model_cfg.get("temperature")
    if temp_override is not None:
        temperature = temp_override

    # System prompt wrapping
    preamble = model_cfg.get("system_preamble")
    suffix = model_cfg.get("system_suffix")
    if preamble or suffix:
        parts = []
        if preamble:
            parts.append(preamble)
        if system:
            parts.append(system)
        if suffix:
            parts.append(suffix)
        system = "\n\n".join(parts)

    return system, temperature


def resolve_model(
    model_name: str,
    registry: dict,
    route_override: str | None = None,
) -> dict:
    """Look up a model and return its provider config.

    If route_override is given (e.g. --route openrouter), use that route
    instead of the default. Fails if the model doesn't have that route.
    """
    models = registry.get("models", {})
    if model_name not in models:
        available = ", ".join(
            n for n, m in sorted(models.items())
            if m.get("_source") == "manual" or m.get("tier", 3) <= 2
        )
        raise ValueError(
            f"Unknown model '{model_name}'. Available: {available}"
        )

    model_cfg = models[model_name]
    routes = model_cfg.get("routes", {})
    route_name = route_override or model_cfg.get("route")

    if not route_name:
        raise ValueError(f"Model '{model_name}' has no 'route' configured")
    if route_name not in routes:
        available_routes = ", ".join(sorted(routes.keys()))
        raise ValueError(
            f"Model '{model_name}' has no route '{route_name}'. "
            f"Available routes: {available_routes}"
        )

    # Special case: aristotle is not a general LLM
    if route_name == "aristotle":
        raise ValueError(
            f"Model '{model_name}' is the Aristotle theorem prover. "
            f"Use /prove instead of /llm for formal verification."
        )

    route_cfg = routes[route_name]
    providers = registry.get("providers", {})

    # CLI routes don't need a provider entry
    api_style = None
    base_url = ""
    env_key = ""
    if route_name in providers:
        provider_cfg = providers[route_name]
        api_style = provider_cfg.get("api_style")
        base_url = provider_cfg.get("base_url", "")
        env_key = provider_cfg.get("env_key", "")
    else:
        # Infer api_style from route name
        cli_styles = {"claude-cli": "claude-cli", "codex": "codex", "kimi-cli": "kimi-cli"}
        api_style = cli_styles.get(route_name, "openai")

    return {
        "model_name": model_name,
        "provider": route_name,
        "api_model": route_cfg.get("api_model", model_name),
        "base_url": base_url,
        "env_key": env_key,
        "api_style": api_style,
        "reasoning_effort": model_cfg.get("reasoning_effort"),
        "thinking_level": model_cfg.get("thinking_level"),
        "thinking": model_cfg.get("thinking"),
        "reasoning": model_cfg.get("reasoning"),
        "grounding": model_cfg.get("grounding"),
        "codex_config": model_cfg.get("codex_config"),
    }


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _http_request(url: str, headers: dict, body: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Make an HTTP POST request and return parsed JSON response."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"API error {e.code} from {url}:\n{error_body}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection error to {url}: {e.reason}") from e


# ---------------------------------------------------------------------------
# Provider call functions
# ---------------------------------------------------------------------------

def call_openai_compatible(
    base_url: str,
    api_key: str,
    model_id: str,
    prompt: str,
    system: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    reasoning: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Call an OpenAI-compatible chat completions API (OpenRouter, Moonshot, etc.)."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = url + "/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body: dict = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if reasoning:
        body["reasoning"] = reasoning

    resp = _http_request(url, headers, body, timeout=timeout)

    choices = resp.get("choices", [])
    if not choices:
        raise RuntimeError(f"No choices in API response: {json.dumps(resp)[:500]}")
    return choices[0].get("message", {}).get("content", "")


def call_anthropic(
    api_key: str,
    model_id: str,
    prompt: str,
    system: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Call the Anthropic Messages API."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    body: dict = {
        "model": model_id,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    resp = _http_request(url, headers, body, timeout=timeout)

    content = resp.get("content", [])
    if not content:
        raise RuntimeError(f"No content in API response: {json.dumps(resp)[:500]}")
    return content[0].get("text", "")


def call_google(
    api_key: str,
    model_id: str,
    prompt: str,
    system: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    thinking_level: str | None = None,
    grounding: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Call the Google Generative AI API (supports thinkingLevel + grounding)."""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{model_id}:generateContent?key={api_key}"
    )
    headers = {"Content-Type": "application/json"}

    generation_config: dict = {
        "temperature": temperature,
        "maxOutputTokens": max_tokens,
    }
    if thinking_level:
        generation_config["thinkingConfig"] = {
            "thinkingLevel": thinking_level,
        }

    body: dict = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }
    if grounding:
        body["tools"] = [{"google_search": {}}]
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    resp = _http_request(url, headers, body, timeout=timeout)

    candidates = resp.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"No candidates in API response: {json.dumps(resp)[:500]}")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError(f"No parts in candidate: {json.dumps(resp)[:500]}")
    # With thinking enabled, response may have thought parts then text parts.
    # Extract the last text part (the actual response, not the thoughts).
    text_parts = [p.get("text", "") for p in parts if "text" in p]
    return text_parts[-1] if text_parts else ""


def call_codex(
    model_id: str,
    prompt: str,
    system: str | None = None,
    timeout: int = DEFAULT_CLI_TIMEOUT,
    reasoning_effort: str | None = None,
    codex_config: dict | None = None,
) -> str:
    """Call an OpenAI model via the locally installed Codex CLI.

    Uses `codex exec` in non-interactive mode. No API key needed.
    codex_config: optional dict of -c key=value overrides (e.g. model_context_window).
    """
    codex_bin = shutil.which("codex")
    if not codex_bin:
        raise RuntimeError(
            "Codex CLI not found on PATH. Install it or use --route openrouter."
        )

    full_prompt = ""
    if system:
        full_prompt += f"{system}\n\n"
    full_prompt += prompt

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix="llm-prompt-", delete=False
    ) as pf:
        pf.write(full_prompt)
        prompt_file = pf.name

    output_file = prompt_file.replace("llm-prompt-", "llm-output-")

    try:
        cmd = [
            codex_bin, "exec",
            "-m", model_id,
            "--full-auto",
            "--skip-git-repo-check",
            "-o", output_file,
        ]
        if reasoning_effort:
            cmd.extend(["-c", f'reasoning_effort="{reasoning_effort}"'])
        # Apply codex_config overrides (e.g. model_context_window for 1M context)
        if codex_config:
            for key, value in codex_config.items():
                if key.startswith("_"):
                    continue  # skip metadata keys like _note
                cmd.extend(["-c", f"{key}={value}"])

        result = subprocess.run(
            cmd,
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(
                f"Codex exec failed (exit {result.returncode}): {stderr or result.stdout[:500]}"
            )

        out_path = Path(output_file)
        if out_path.exists() and out_path.stat().st_size > 0:
            response = out_path.read_text().strip()
        else:
            response = result.stdout.strip()

        if not response:
            raise RuntimeError("Codex returned empty response")
        return response

    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Codex exec timed out after {timeout}s")
    finally:
        for f in (prompt_file, output_file):
            try:
                Path(f).unlink(missing_ok=True)
            except OSError:
                pass


def call_kimi(
    model_id: str,
    prompt: str,
    system: str | None = None,
    timeout: int = DEFAULT_CLI_TIMEOUT,
    thinking: bool = False,
) -> str:
    """Call a Kimi model via the locally installed Kimi CLI. No API key needed."""
    kimi_bin = shutil.which("kimi")
    if not kimi_bin:
        raise RuntimeError(
            "Kimi CLI not found on PATH. Install it or use --route openrouter."
        )

    full_prompt = ""
    if system:
        full_prompt += f"{system}\n\n"
    full_prompt += prompt

    try:
        cmd = [kimi_bin, "--quiet", "-m", model_id]
        if thinking:
            cmd.append("--thinking")
        cmd.extend(["-p", full_prompt])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(
                f"Kimi CLI failed (exit {result.returncode}): {stderr or result.stdout[:500]}"
            )

        response = result.stdout.strip()
        if not response:
            raise RuntimeError("Kimi CLI returned empty response")
        return response

    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Kimi CLI timed out after {timeout}s")


def call_claude_cli(
    model_id: str,
    prompt: str,
    system: str | None = None,
    timeout: int = DEFAULT_CLI_TIMEOUT,
) -> str:
    """Call a Claude model via the locally installed Claude Code CLI. No API key needed."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise RuntimeError(
            "Claude CLI not found on PATH. Install it or use --route openrouter."
        )

    full_prompt = ""
    if system:
        full_prompt += f"{system}\n\n"
    full_prompt += prompt

    try:
        cmd = [
            claude_bin, "-p",
            "--model", model_id,
            "--tools", "",
            "--no-session-persistence",
        ]
        result = subprocess.run(
            cmd,
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(
                f"Claude CLI failed (exit {result.returncode}): {stderr or result.stdout[:500]}"
            )

        response = result.stdout.strip()
        if not response:
            raise RuntimeError("Claude CLI returned empty response")
        return response

    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Claude CLI timed out after {timeout}s")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _find_fallback_route(model_name: str, registry: dict) -> dict | None:
    """Find a non-CLI API fallback route for a model.

    Looks up the model's ``routes`` dict for a route backed by a real API
    (not a CLI wrapper).  Prefers ``openrouter``, then any other API route.
    Returns a resolved provider config dict or ``None`` if no fallback exists.
    """
    CLI_STYLES = {"codex", "kimi-cli", "claude-cli", "claude-code", "aristotle"}

    models = registry.get("models", {})
    model_cfg = models.get(model_name)
    if not model_cfg:
        return None

    routes = model_cfg.get("routes", {})
    providers = registry.get("providers", {})

    candidates = []
    for route_name, route_cfg in routes.items():
        provider_cfg = providers.get(route_name, {})
        api_style = provider_cfg.get("api_style", route_name)
        if api_style in CLI_STYLES:
            continue
        candidates.append((route_name, route_cfg, provider_cfg, api_style))

    if not candidates:
        return None

    # Sort: openrouter first
    candidates.sort(key=lambda c: (0 if c[0] == "openrouter" else 1, c[0]))
    route_name, route_cfg, provider_cfg, api_style = candidates[0]

    return {
        "model_name": model_name,
        "provider": route_name,
        "api_model": route_cfg.get("api_model", model_name),
        "base_url": provider_cfg.get("base_url", ""),
        "env_key": provider_cfg.get("env_key", ""),
        "api_style": api_style,
        "reasoning_effort": model_cfg.get("reasoning_effort"),
        "thinking_level": model_cfg.get("thinking_level"),
        "thinking": model_cfg.get("thinking"),
        "reasoning": model_cfg.get("reasoning"),
        "grounding": model_cfg.get("grounding"),
        "codex_config": model_cfg.get("codex_config"),
    }


def _call_api_route(
    model_config: dict,
    prompt: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Call a model via its API route (non-CLI). Extracted for fallback reuse."""
    api_model = model_config["api_model"]
    api_style = model_config.get("api_style", "openai")
    api_key = get_api_key(model_config["env_key"])

    if api_style == "anthropic":
        return call_anthropic(api_key, api_model, prompt, system, temperature, max_tokens, timeout=timeout)
    elif api_style == "google":
        return call_google(
            api_key, api_model, prompt, system, temperature=1.0,
            max_tokens=max_tokens,
            thinking_level=model_config.get("thinking_level"),
            grounding=bool(model_config.get("grounding")),
            timeout=timeout,
        )
    else:
        return call_openai_compatible(
            model_config["base_url"], api_key, api_model, prompt, system,
            temperature, max_tokens,
            reasoning=model_config.get("reasoning"),
            timeout=timeout,
        )


def call_model(
    model_config: dict,
    prompt: str,
    system: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int = DEFAULT_TIMEOUT,
    registry: dict | None = None,
) -> str:
    """Route to the appropriate provider based on model config.

    For CLI-based routes (codex, kimi-cli, claude-cli), wraps the call in a
    try/except.  On timeout or crash, automatically falls back to an API route
    (e.g. OpenRouter) if one is configured for that model in *registry*.
    """
    # Apply per-model prompting overrides
    prompting_cfg = load_prompting_config()
    system, temperature = apply_prompting_overrides(
        model_config["model_name"], system, temperature, prompting_cfg
    )

    api_model = model_config["api_model"]
    api_style = model_config.get("api_style", "openai")

    # CLI-based routes — no API key needed, with auto-fallback on failure
    if api_style in ("codex", "kimi-cli", "claude-cli"):
        # Use CLI timeout (600s) unless caller explicitly set a lower value
        cli_timeout = max(timeout, DEFAULT_CLI_TIMEOUT) if timeout == DEFAULT_TIMEOUT else timeout
        try:
            if api_style == "codex":
                return call_codex(
                    api_model, prompt, system, timeout=cli_timeout,
                    reasoning_effort=model_config.get("reasoning_effort"),
                    codex_config=model_config.get("codex_config"),
                )
            elif api_style == "kimi-cli":
                return call_kimi(
                    api_model, prompt, system, timeout=cli_timeout,
                    thinking=bool(model_config.get("thinking")),
                )
            else:
                return call_claude_cli(api_model, prompt, system, timeout=cli_timeout)
        except RuntimeError as e:
            if "not found on PATH" in str(e):
                raise  # setup issue, don't fallback
            # Timeout, non-zero exit, empty response, crash → try API fallback
            if registry:
                fallback = _find_fallback_route(model_config["model_name"], registry)
                if fallback:
                    print(
                        f"WARNING: {api_style} failed ({e}), falling back to "
                        f"{fallback['provider']}",
                        file=sys.stderr,
                    )
                    return _call_api_route(fallback, prompt, system, temperature, max_tokens, timeout=timeout)
            raise

    # API-based routes — need a key
    api_key = get_api_key(model_config["env_key"])

    if api_style == "anthropic":
        return call_anthropic(
            api_key, api_model, prompt, system, temperature, max_tokens,
            timeout=timeout,
        )
    elif api_style == "google":
        return call_google(
            api_key, api_model, prompt, system, temperature=1.0,
            max_tokens=max_tokens,
            thinking_level=model_config.get("thinking_level"),
            grounding=bool(model_config.get("grounding")),
            timeout=timeout,
        )
    else:
        # Default: OpenAI-compatible (OpenRouter, Moonshot, etc.)
        return call_openai_compatible(
            model_config["base_url"], api_key, api_model, prompt, system,
            temperature, max_tokens,
            reasoning=model_config.get("reasoning"),
            timeout=timeout,
        )


# ---------------------------------------------------------------------------
# List / display
# ---------------------------------------------------------------------------

def list_models(
    registry: dict,
    show_all: bool = False,
    tier_filter: int | None = None,
) -> None:
    """Print available models with tier-based filtering."""
    models = registry.get("models", {})

    # Determine which tiers to show
    if tier_filter is not None:
        show_tiers = {tier_filter}
    elif show_all:
        show_tiers = {1, 2, 3}
    else:
        show_tiers = {1, 2}

    # Group by tier
    by_tier: dict[int, list[tuple[str, dict]]] = {}
    for name, cfg in sorted(models.items()):
        tier = cfg.get("tier", 3)
        if tier in show_tiers:
            by_tier.setdefault(tier, []).append((name, cfg))

    tier_labels = {1: "Tier 1 — Curated", 2: "Tier 2 — Notable", 3: "Tier 3 — All Discovered"}

    total_shown = 0
    for tier in sorted(by_tier.keys()):
        entries = by_tier[tier]
        total_shown += len(entries)
        print(f"\n{tier_labels.get(tier, f'Tier {tier}')} ({len(entries)} models):")
        print(f"  {'Name':20s}  {'Route':14s}  {'API Model':40s}  Description")
        print(f"  {'─' * 20}  {'─' * 14}  {'─' * 40}  {'─' * 40}")
        for name, cfg in entries:
            route = cfg.get("route", "?")
            routes = cfg.get("routes", {})
            route_cfg = routes.get(route, {})
            api_model = route_cfg.get("api_model", "")
            desc = cfg.get("description", "")[:40]

            tag = ""
            style_tags = {
                "claude-cli": " (CLI)", "codex": " (CLI)",
                "kimi-cli": " (CLI)", "aristotle": " (prover)",
            }
            tag = style_tags.get(route, "")

            print(f"  {name:20s}  {route + tag:14s}  {api_model:40s}  {desc}")

    total = len(models)
    hidden = total - total_shown
    if hidden > 0:
        print(f"\n  ({hidden} more models hidden — use --all or --tier 3 to show)")
    print()


def list_providers(registry: dict) -> None:
    """Print configured providers."""
    providers = registry.get("providers", {})
    print("\nConfigured providers:\n")
    print(f"  {'Name':14s}  {'Style':12s}  {'Auth':20s}  Note")
    print(f"  {'─' * 14}  {'─' * 12}  {'─' * 20}  {'─' * 40}")
    for name, cfg in sorted(providers.items()):
        style = cfg.get("api_style", "?")
        env_key = cfg.get("env_key", "—")
        note = cfg.get("note", cfg.get("base_url", ""))[:40]
        print(f"  {name:14s}  {style:12s}  {env_key:20s}  {note}")
    print()


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Universal LLM Router — route prompts to any model across all providers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s --model opus --prompt "Say hello in 3 words"
  %(prog)s --model chatgpt-5.4 --prompt-file prompt.txt --system "You are a poet"
  %(prog)s --model gemini-3-pro --prompt "Explain X" --json
  %(prog)s --model opus --prompt "Hello" --route openrouter
  %(prog)s --list-models
  %(prog)s --list-models --all
  %(prog)s --list-providers
""",
    )
    parser.add_argument("--model", "-m", help="Model name (e.g., opus, chatgpt-5.4, gemini-3-pro)")
    parser.add_argument("--prompt", "-p", help="The prompt to send")
    parser.add_argument("--prompt-file", type=Path, help="Read prompt from file")
    parser.add_argument("--system", "-s", help="System prompt")
    parser.add_argument("--system-file", type=Path, help="Read system prompt from file")
    parser.add_argument("--route", help="Force a specific provider route (e.g., openrouter, claude-cli)")
    parser.add_argument("--temperature", "-t", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--timeout", type=int, default=DEFAULT_CLI_TIMEOUT, help="Request timeout in seconds (default: 600)")
    parser.add_argument("--json", action="store_true", help="Output JSON with metadata")
    parser.add_argument("--list-models", action="store_true", help="List available models")
    parser.add_argument("--list-providers", action="store_true", help="List configured providers")
    parser.add_argument("--all", action="store_true", help="Show all tiers (with --list-models)")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3], help="Filter by tier (with --list-models)")
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH, help="Path to model-registry.json")
    args = parser.parse_args()

    registry = load_registry(args.registry)

    # List modes
    if args.list_models:
        list_models(registry, show_all=args.all, tier_filter=args.tier)
        sys.exit(0)
    if args.list_providers:
        list_providers(registry)
        sys.exit(0)

    # Require model for call mode
    if not args.model:
        parser.error("--model is required (or use --list-models / --list-providers)")

    # Resolve prompt
    if args.prompt_file:
        if not args.prompt_file.exists():
            parser.error(f"Prompt file not found: {args.prompt_file}")
        prompt = args.prompt_file.read_text()
    elif args.prompt:
        prompt = args.prompt
    else:
        # Try stdin
        if not sys.stdin.isatty():
            prompt = sys.stdin.read()
        else:
            parser.error("--prompt or --prompt-file is required (or pipe via stdin)")

    # Resolve system prompt
    system = None
    if args.system_file:
        if not args.system_file.exists():
            parser.error(f"System file not found: {args.system_file}")
        system = args.system_file.read_text()
    elif args.system:
        system = args.system

    # Resolve model and call
    try:
        model_config = resolve_model(args.model, registry, route_override=args.route)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        response = call_model(
            model_config,
            prompt,
            system=system,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
            registry=registry,
        )
    except Exception as e:
        print(f"Error calling {args.model}: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        output = {
            "model": args.model,
            "provider": model_config["provider"],
            "api_model": model_config["api_model"],
            "api_style": model_config["api_style"],
            "response": response,
        }
        print(json.dumps(output, indent=2))
    else:
        print(response)


if __name__ == "__main__":
    main()
