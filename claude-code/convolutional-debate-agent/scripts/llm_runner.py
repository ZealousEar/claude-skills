#!/usr/bin/env python3
"""Unified LLM runner for the Convolutional Debate Agent.

Calls external LLM APIs (OpenAI, Google, Moonshot, Anthropic) with a given prompt
and returns the response text. Uses only Python stdlib — no pip dependencies.

Usage:
    python3 llm_runner.py --model chatgpt-5.2 --prompt "Your prompt here"
    python3 llm_runner.py --model gemini-3.1-pro --prompt-file prompt.txt --system "You are..."
    python3 llm_runner.py --model kimi-2.5 --prompt "..." --temperature 0.7
    python3 llm_runner.py --list-models
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

# Default paths
SKILL_DIR = Path.home() / ".claude" / "skills" / "convolutional-debate-agent"
SETTINGS_PATH = SKILL_DIR / "settings" / "model-settings.json"
PROMPTING_PATH = SKILL_DIR / "settings" / "model-prompting.json"
ENV_PATH = SKILL_DIR / "api-keys" / "provider-keys.env"
OAUTH_TOKEN_PATH = SKILL_DIR / "api-keys" / "openai-oauth.json"

# Defaults
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.7
DEFAULT_CLI_TIMEOUT = 600

# Cached prompting config (loaded once per process)
_PROMPTING_CACHE: dict | None = None


def load_prompting_config() -> dict:
    """Load per-model prompting overrides from model-prompting.json."""
    global _PROMPTING_CACHE
    if _PROMPTING_CACHE is None:
        if PROMPTING_PATH.exists():
            _PROMPTING_CACHE = json.loads(PROMPTING_PATH.read_text())
        else:
            _PROMPTING_CACHE = {"defaults": {}, "models": {}}
    return _PROMPTING_CACHE


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


def load_env_file(env_path: Path) -> dict[str, str]:
    """Load key=value pairs from an env file."""
    env = {}
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


def _load_oauth_api_key(oauth_path: Path) -> str | None:
    """Try to load an OpenAI API key from OAuth token storage."""
    if not oauth_path.exists():
        return None
    try:
        data = json.loads(oauth_path.read_text())
        return data.get("openai_api_key") or None
    except (json.JSONDecodeError, OSError):
        return None


def get_api_key(env_key: str, env_path: Path) -> str:
    """Get API key from OAuth token, environment variable, or env file.

    For OpenAI, checks the OAuth token store first (from `openai_auth.py login`),
    then falls back to environment variables and env file.
    """
    # For OpenAI: check OAuth token store first
    if env_key == "OPENAI_API_KEY":
        oauth_key = _load_oauth_api_key(OAUTH_TOKEN_PATH)
        if oauth_key:
            return oauth_key

    # Check environment
    key = os.environ.get(env_key)
    if key:
        return key
    # Fall back to env file
    env = load_env_file(env_path)
    key = env.get(env_key)
    if key:
        return key

    # Provide helpful error message
    if env_key == "OPENAI_API_KEY":
        raise ValueError(
            f"OpenAI API key not found. Either:\n"
            f"  1. Run: python3 {SKILL_DIR}/scripts/openai_auth.py login\n"
            f"     (authenticate with your ChatGPT account — no API key needed)\n"
            f"  2. Set OPENAI_API_KEY as an environment variable\n"
            f"  3. Add OPENAI_API_KEY to {env_path}"
        )
    raise ValueError(
        f"API key '{env_key}' not found. Set it as an environment variable "
        f"or add it to {env_path}"
    )


def load_settings(settings_path: Path) -> dict:
    """Load and return model settings."""
    if not settings_path.exists():
        raise FileNotFoundError(f"Settings file not found: {settings_path}")
    return json.loads(settings_path.read_text())


def resolve_model(model_name: str, settings: dict) -> dict:
    """Look up a model name and its active route, returning provider config.

    Each model has:
      - "route": the active provider name (e.g. "codex", "openrouter", "claude-code")
      - "routes": dict mapping provider names to their model-specific config
    """
    models = settings.get("models", {})
    if model_name not in models:
        available = ", ".join(sorted(models.keys()))
        raise ValueError(
            f"Unknown model '{model_name}'. Available: {available}"
        )

    model_cfg = models[model_name]
    route_name = model_cfg.get("route")
    routes = model_cfg.get("routes", {})

    if not route_name:
        raise ValueError(f"Model '{model_name}' has no 'route' configured")
    if route_name not in routes:
        available_routes = ", ".join(sorted(routes.keys()))
        raise ValueError(
            f"Model '{model_name}' route '{route_name}' not in routes. "
            f"Available: {available_routes}"
        )

    if route_name == "claude-code":
        raise ValueError(
            f"Model '{model_name}' routes via claude-code (Task tool). "
            f"Use this script only for external API models."
        )

    route_cfg = routes[route_name]
    providers = settings.get("providers", {})
    if route_name not in providers:
        raise ValueError(f"Provider '{route_name}' not configured in settings")

    provider_cfg = providers[route_name]
    return {
        "model_name": model_name,
        "provider": route_name,
        "api_model": route_cfg.get("api_model", model_name),
        "base_url": provider_cfg.get("base_url", ""),
        "env_key": provider_cfg.get("env_key", ""),
        "api_style": provider_cfg.get("api_style", "openai"),
        "reasoning_effort": model_cfg.get("reasoning_effort"),
        "thinking_level": model_cfg.get("thinking_level"),
        "thinking": model_cfg.get("thinking"),
        "reasoning": model_cfg.get("reasoning"),
        "grounding": model_cfg.get("grounding"),
        "codex_config": model_cfg.get("codex_config"),
    }


def _http_request(url: str, headers: dict, body: dict, timeout: int = 120) -> dict:
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


def call_openai_compatible(
    base_url: str,
    api_key: str,
    model_id: str,
    prompt: str,
    system: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    reasoning: dict | None = None,
) -> str:
    """Call an OpenAI-compatible chat completions API.

    The optional `reasoning` dict is passed through as-is to the request body.
    OpenRouter uses this to enable provider-specific reasoning modes:
      - Claude: {"max_tokens": 16000}
      - GPT:    {"effort": "high"}
      - Gemini: {"effort": "high"}
    """
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
    body = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if reasoning:
        body["reasoning"] = reasoning

    resp = _http_request(url, headers, body)

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

    resp = _http_request(url, headers, body)

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
) -> str:
    """Call the Google Generative AI API.

    When grounding=True, enables Google Search grounding which allows the model
    to cite web sources in its response.
    """
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

    resp = _http_request(url, headers, body)

    candidates = resp.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"No candidates in API response: {json.dumps(resp)[:500]}")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError(f"No parts in candidate: {json.dumps(resp)[:500]}")
    # With thinking enabled, response may contain thought parts followed by text parts.
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

    Uses `codex exec` in non-interactive mode. Requires Codex CLI to be
    installed and authenticated (e.g., via `codex login`).
    No API key needed — Codex uses its own stored credentials.
    codex_config: optional dict of -c key=value overrides (e.g. model_context_window for 1M context).
    """
    codex_bin = shutil.which("codex")
    if not codex_bin:
        raise RuntimeError(
            "Codex CLI not found on PATH. Install it or switch to the 'openai' "
            "provider with an API key."
        )

    # Build the full prompt with system instructions if provided
    full_prompt = ""
    if system:
        full_prompt += f"{system}\n\n"
    full_prompt += prompt

    # Write prompt and prepare output file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix="debate-prompt-", delete=False
    ) as pf:
        pf.write(full_prompt)
        prompt_file = pf.name

    output_file = prompt_file.replace("debate-prompt-", "debate-output-")

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
        # Pass prompt via stdin to handle arbitrarily long prompts
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

        # Read output from -o file if it exists, otherwise use stdout
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
        # Clean up temp files
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
    """Call a Kimi model via the locally installed Kimi CLI.

    Uses `kimi --quiet -p` in non-interactive mode. Requires Kimi CLI to be
    installed and authenticated (e.g., via `kimi login`).
    No API key needed — Kimi CLI uses its own stored credentials.
    """
    kimi_bin = shutil.which("kimi")
    if not kimi_bin:
        raise RuntimeError(
            "Kimi CLI not found on PATH. Install it or switch to the 'openrouter' "
            "or 'moonshot' route."
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
    """Call a Claude model via the locally installed Claude Code CLI.

    Uses `claude -p` in non-interactive mode. Requires Claude Code CLI to be
    installed and authenticated.
    No API key needed — Claude CLI uses its own stored credentials.
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise RuntimeError(
            "Claude CLI not found on PATH. Install it or switch to the 'openrouter' "
            "route with an API key."
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


def _find_fallback_route(model_name: str, settings: dict) -> dict | None:
    """Find a non-CLI API fallback route for a model.

    Looks up the model's ``routes`` dict for a route backed by a real API
    (not a CLI wrapper).  Prefers ``openrouter``, then any other API route.
    Returns a resolved provider config dict (same shape as ``resolve_model``
    output) or ``None`` if no fallback exists.
    """
    CLI_STYLES = {"codex", "kimi-cli", "claude-cli", "claude-code", "aristotle"}

    models = settings.get("models", {})
    model_cfg = models.get(model_name)
    if not model_cfg:
        return None

    routes = model_cfg.get("routes", {})
    providers = settings.get("providers", {})

    # Prefer openrouter, then try any other non-CLI route
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
    }


def _call_api_route(
    model_config: dict,
    prompt: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
    env_path: Path = ENV_PATH,
) -> str:
    """Call a model via its API route (non-CLI). Extracted for fallback reuse."""
    api_model = model_config["api_model"]
    api_style = model_config.get("api_style", "openai")
    api_key = get_api_key(model_config["env_key"], env_path)

    if api_style == "anthropic":
        return call_anthropic(api_key, api_model, prompt, system, temperature, max_tokens)
    elif api_style == "google":
        return call_google(
            api_key, api_model, prompt, system, temperature=1.0,
            max_tokens=max_tokens, thinking_level=model_config.get("thinking_level"),
            grounding=bool(model_config.get("grounding")),
        )
    else:
        return call_openai_compatible(
            model_config["base_url"], api_key, api_model, prompt, system, temperature, max_tokens,
            reasoning=model_config.get("reasoning"),
        )


def call_model(
    model_config: dict,
    prompt: str,
    system: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    env_path: Path = ENV_PATH,
    timeout: int = DEFAULT_CLI_TIMEOUT,
    settings: dict | None = None,
) -> str:
    """Route to the appropriate API based on provider config.

    For CLI-based routes (codex, kimi-cli, claude-cli), wraps the call in a
    try/except.  On timeout or crash, automatically falls back to an API route
    (e.g. OpenRouter) if one is configured for that model in *settings*.
    """
    # Apply per-model prompting overrides (temperature, system preamble/suffix)
    prompting_cfg = load_prompting_config()
    system, temperature = apply_prompting_overrides(
        model_config["model_name"], system, temperature, prompting_cfg
    )

    api_model = model_config["api_model"]
    api_style = model_config.get("api_style", "openai")

    # CLI-based routes — no API key needed, with auto-fallback on failure
    if api_style in ("codex", "kimi-cli", "claude-cli"):
        try:
            if api_style == "codex":
                return call_codex(api_model, prompt, system, timeout=timeout, reasoning_effort=model_config.get("reasoning_effort"), codex_config=model_config.get("codex_config"))
            elif api_style == "kimi-cli":
                return call_kimi(api_model, prompt, system, timeout=timeout, thinking=bool(model_config.get("thinking")))
            else:
                return call_claude_cli(api_model, prompt, system, timeout=timeout)
        except RuntimeError as e:
            if "not found on PATH" in str(e):
                raise  # setup issue, don't fallback
            # Timeout, non-zero exit, empty response, crash → try API fallback
            if settings:
                fallback = _find_fallback_route(model_config["model_name"], settings)
                if fallback:
                    print(
                        f"WARNING: {api_style} failed ({e}), falling back to "
                        f"{fallback['provider']}",
                        file=sys.stderr,
                    )
                    return _call_api_route(fallback, prompt, system, temperature, max_tokens, env_path)
            raise

    # API-based routes
    api_key = get_api_key(model_config["env_key"], env_path)

    if api_style == "anthropic":
        return call_anthropic(api_key, api_model, prompt, system, temperature, max_tokens)
    elif api_style == "google":
        # Gemini 3 is optimized for temperature=1.0; lower values cause looping/degraded reasoning
        return call_google(
            api_key, api_model, prompt, system, temperature=1.0,
            max_tokens=max_tokens, thinking_level=model_config.get("thinking_level"),
            grounding=bool(model_config.get("grounding")),
        )
    else:
        # Default to OpenAI-compatible (covers OpenRouter, direct OpenAI, Moonshot, etc.)
        return call_openai_compatible(
            model_config["base_url"], api_key, api_model, prompt, system, temperature, max_tokens,
            reasoning=model_config.get("reasoning"),
        )


def list_models(settings: dict) -> None:
    """Print available models with their active route and alternatives."""
    models = settings.get("models", {})
    print("Available models:\n")
    for name in sorted(models.keys()):
        cfg = models[name]
        active_route = cfg.get("route", "?")
        routes = cfg.get("routes", {})
        active_cfg = routes.get(active_route, {})
        active_model_id = active_cfg.get("api_model", active_cfg.get("task_model", ""))

        tag = ""
        if active_route == "claude-code":
            tag = " (Task tool)"
        elif active_route == "codex":
            tag = " (Codex CLI)"
        elif active_route == "kimi-cli":
            tag = " (Kimi CLI)"
        elif active_route == "claude-cli":
            tag = " (Claude CLI)"

        alt_routes = [r for r in routes if r != active_route]
        alt_str = f"  alt: {', '.join(alt_routes)}" if alt_routes else ""

        print(f"  {name:18s}  via {active_route:12s}  ->  {active_model_id}{tag}{alt_str}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Call external LLM APIs for the Convolutional Debate Agent."
    )
    parser.add_argument("--model", help="Model name from settings (e.g., 'chatgpt-5.2')")
    parser.add_argument("--prompt", help="The prompt to send")
    parser.add_argument("--prompt-file", type=Path, help="Read prompt from file instead of --prompt")
    parser.add_argument("--system", help="Optional system prompt")
    parser.add_argument("--system-file", type=Path, help="Read system prompt from file")
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--settings", type=Path, default=SETTINGS_PATH, help="Path to model-settings.json")
    parser.add_argument("--env-file", type=Path, default=ENV_PATH, help="Path to API keys env file")
    parser.add_argument("--timeout", type=int, default=DEFAULT_CLI_TIMEOUT, help="CLI subprocess timeout in seconds (default: 600)")
    parser.add_argument("--list-models", action="store_true", help="List available models and exit")
    parser.add_argument("--json", action="store_true", help="Wrap output in JSON with model metadata")
    args = parser.parse_args()

    settings = load_settings(args.settings)

    if args.list_models:
        list_models(settings)
        sys.exit(0)

    if not args.model:
        parser.error("--model is required (or use --list-models)")

    # Resolve prompt
    if args.prompt_file:
        prompt = args.prompt_file.read_text()
    elif args.prompt:
        prompt = args.prompt
    else:
        parser.error("--prompt or --prompt-file is required")

    # Resolve system prompt
    system = None
    if args.system_file:
        system = args.system_file.read_text()
    elif args.system:
        system = args.system

    # Resolve model config and call
    try:
        model_config = resolve_model(args.model, settings)
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
            env_path=args.env_file,
            timeout=args.timeout,
            settings=settings,
        )
    except Exception as e:
        print(f"Error calling {args.model}: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        output = {
            "model": args.model,
            "provider": model_config["provider"],
            "api_model": model_config["api_model"],
            "response": response,
        }
        print(json.dumps(output, indent=2))
    else:
        print(response)


if __name__ == "__main__":
    main()
