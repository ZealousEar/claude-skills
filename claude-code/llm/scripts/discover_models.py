#!/usr/bin/env python3
"""Auto-discover models from OpenRouter and Google APIs.

Discovers new models, assigns tiers and routing rules, and optionally
updates the model registry. Never overwrites tier1 (manually curated) models.

Usage:
    python3 discover_models.py                        # dry-run: show diff
    python3 discover_models.py --apply                # update registry
    python3 discover_models.py --source openrouter    # only query OpenRouter
    python3 discover_models.py --source google        # only query Google
    python3 discover_models.py --json                 # output as JSON

Stdlib only — no pip dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Paths
SKILL_DIR = Path.home() / ".claude" / "skills" / "llm"
REGISTRY_PATH = SKILL_DIR / "settings" / "model-registry.json"
ROUTING_RULES_PATH = SKILL_DIR / "settings" / "routing-rules.json"

# Fallback credential locations
DEBATE_AGENT_ENV = (
    Path.home() / ".claude" / "skills" / "convolutional-debate-agent"
    / "api-keys" / "provider-keys.env"
)

# Major providers whose models qualify for tier2 (if context >= 32k)
TIER2_PROVIDERS = {
    "anthropic", "openai", "google", "meta-llama", "mistralai",
    "deepseek", "cohere", "nvidia", "amazon", "microsoft",
    "moonshotai", "moonshot", "x-ai", "z-ai", "minimax",
    "qwen", "alibaba",
}


def _load_env_file(env_path: Path) -> dict[str, str]:
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


def _get_key(env_key: str) -> str | None:
    """Try to get an API key from env vars or debate agent keys."""
    key = os.environ.get(env_key)
    if key:
        return key
    env = _load_env_file(DEBATE_AGENT_ENV)
    return env.get(env_key)


def _http_get(url: str, headers: dict | None = None, timeout: int = 30) -> dict:
    """Make an HTTP GET request and return parsed JSON."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {error_body[:500]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection error to {url}: {e.reason}") from e


# ---------------------------------------------------------------------------
# Discovery sources
# ---------------------------------------------------------------------------

def discover_openrouter() -> list[dict]:
    """Fetch all models from OpenRouter (no auth needed)."""
    print("  Querying OpenRouter /api/v1/models ...", end=" ", flush=True)
    resp = _http_get("https://openrouter.ai/api/v1/models")
    raw_models = resp.get("data", [])
    print(f"{len(raw_models)} models found")

    results = []
    for m in raw_models:
        model_id = m.get("id", "")
        if not model_id:
            continue
        ctx = m.get("context_length", 0) or 0
        results.append({
            "id": model_id,
            "name": m.get("name", model_id),
            "context_length": ctx,
            "description": m.get("description", "")[:120],
            "pricing": {
                "prompt": m.get("pricing", {}).get("prompt", "?"),
                "completion": m.get("pricing", {}).get("completion", "?"),
            },
            "_discovered_from": "openrouter",
        })
    return results


def discover_google(api_key: str) -> list[dict]:
    """Fetch generative models from Google Generative AI API."""
    print("  Querying Google GenAI /v1beta/models ...", end=" ", flush=True)
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    resp = _http_get(url)
    raw_models = resp.get("models", [])

    results = []
    for m in raw_models:
        # Only include models that support generateContent
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" not in methods:
            continue

        # Model name format: "models/gemini-3-pro-preview" -> "gemini-3-pro-preview"
        full_name = m.get("name", "")
        short_name = full_name.replace("models/", "")
        # Create OpenRouter-style ID: google/model-name
        model_id = f"google/{short_name}"

        ctx = m.get("inputTokenLimit", 0) or 0
        results.append({
            "id": model_id,
            "name": m.get("displayName", short_name),
            "context_length": ctx,
            "description": m.get("description", "")[:120],
            "_discovered_from": "google",
            "_google_api_model": short_name,
        })

    print(f"{len(results)} generative models found")
    return results


def probe_cli(name: str) -> bool:
    """Check if a CLI binary exists on PATH."""
    return shutil.which(name) is not None


# ---------------------------------------------------------------------------
# Routing and tiering
# ---------------------------------------------------------------------------

def load_routing_rules() -> list[dict]:
    """Load routing rules from JSON file."""
    if not ROUTING_RULES_PATH.exists():
        return []
    data = json.loads(ROUTING_RULES_PATH.read_text())
    return data.get("rules", [])


def apply_routing_rules(model_id: str, rules: list[dict]) -> dict:
    """Match a model ID against routing rules, return provider assignment."""
    for rule in rules:
        pattern = rule.get("pattern", "")
        if re.match(pattern, model_id):
            return {
                "provider": rule["provider"],
                "api_style": rule.get("api_style", "openai"),
            }
    # Fallback to openrouter
    return {"provider": "openrouter", "api_style": "openai"}


def compute_tier(model_info: dict) -> int:
    """Compute tier: 1 if manual, 2 if major provider + context>=32k, 3 otherwise."""
    if model_info.get("_source") == "manual":
        return 1

    model_id = model_info.get("id", "")
    # Extract provider prefix (e.g., "anthropic" from "anthropic/claude-opus-4-6")
    provider_prefix = model_id.split("/")[0] if "/" in model_id else ""
    ctx = model_info.get("context_length", 0) or 0

    if provider_prefix in TIER2_PROVIDERS and ctx >= 32768:
        return 2
    return 3


# ---------------------------------------------------------------------------
# Registry diffing and merging
# ---------------------------------------------------------------------------

def diff_registry(
    current: dict, discovered: list[dict]
) -> dict[str, list]:
    """Compute added/updated models (never touches tier1)."""
    current_models = current.get("models", {})

    # Build lookup of current models by their OpenRouter-style IDs
    current_ids: set[str] = set()
    for name, cfg in current_models.items():
        for route_cfg in cfg.get("routes", {}).values():
            api_model = route_cfg.get("api_model", "")
            if api_model:
                current_ids.add(api_model)

    added = []
    for model in discovered:
        model_id = model["id"]
        if model_id not in current_ids:
            model["tier"] = compute_tier(model)
            added.append(model)

    return {"added": added, "total_discovered": len(discovered)}


def _model_name_from_id(model_id: str) -> str:
    """Convert 'google/gemini-3-pro-preview' -> 'gemini-3-pro-preview'."""
    if "/" in model_id:
        return model_id.split("/", 1)[1]
    return model_id


def merge_registry(current: dict, discovered: list[dict], rules: list[dict]) -> dict:
    """Add new models to registry. Never overwrite tier1 (_source=manual)."""
    current_models = current.get("models", {})

    # Collect all known API model IDs
    known_api_ids: set[str] = set()
    for cfg in current_models.values():
        for route_cfg in cfg.get("routes", {}).values():
            api_model = route_cfg.get("api_model", "")
            if api_model:
                known_api_ids.add(api_model)

    added_count = 0
    for model in discovered:
        model_id = model["id"]
        if model_id in known_api_ids:
            continue

        # New model — create registry entry
        routing = apply_routing_rules(model_id, rules)
        short_name = _model_name_from_id(model_id)

        # Avoid name collisions
        reg_name = short_name
        counter = 2
        while reg_name in current_models:
            reg_name = f"{short_name}-{counter}"
            counter += 1

        tier = compute_tier(model)

        # Build routes
        routes: dict = {}
        provider = routing["provider"]
        if provider == "google" and model.get("_google_api_model"):
            routes["google"] = {"api_model": model["_google_api_model"]}
        routes[provider if provider != "google" else "openrouter"] = {"api_model": model_id}
        # For non-google models, the openrouter route IS the primary
        if provider != "google" and "openrouter" not in routes:
            routes["openrouter"] = {"api_model": model_id}

        entry = {
            "tier": tier,
            "_source": "discovered",
            "_discovered_from": model.get("_discovered_from", "unknown"),
            "_discovered_at": datetime.now(timezone.utc).isoformat(),
            "description": model.get("description", ""),
            "context_length": model.get("context_length"),
            "route": provider,
            "routes": routes,
        }

        current_models[reg_name] = entry
        known_api_ids.add(model_id)
        added_count += 1

    # Update meta
    tier_counts = {1: 0, 2: 0, 3: 0}
    for cfg in current_models.values():
        t = cfg.get("tier", 3)
        tier_counts[t] = tier_counts.get(t, 0) + 1

    current["_meta"] = {
        "last_discovery": datetime.now(timezone.utc).isoformat(),
        "tier1_count": tier_counts[1],
        "tier2_count": tier_counts[2],
        "tier3_count": tier_counts[3],
        "total_count": sum(tier_counts.values()),
    }

    current["models"] = current_models
    return current


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-discover models from OpenRouter and Google APIs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s                          # dry-run: show what would change
  %(prog)s --apply                  # update model-registry.json
  %(prog)s --source openrouter      # only query OpenRouter
  %(prog)s --source google          # only query Google
  %(prog)s --json                   # output diff as JSON
""",
    )
    parser.add_argument("--apply", action="store_true", help="Update registry (default: dry-run)")
    parser.add_argument("--source", choices=["openrouter", "google", "all"], default="all",
                        help="Which source to query (default: all)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    args = parser.parse_args()

    # Load current registry
    if not args.registry.exists():
        print(f"Error: Registry not found: {args.registry}", file=sys.stderr)
        sys.exit(1)
    current = json.loads(args.registry.read_text())

    # Probe CLIs
    print("Probing CLIs:")
    for cli in ["claude", "codex", "kimi"]:
        found = probe_cli(cli)
        print(f"  {cli}: {'found' if found else 'NOT found'}")

    # Discover models
    print("\nDiscovering models:")
    all_discovered: list[dict] = []

    if args.source in ("openrouter", "all"):
        try:
            all_discovered.extend(discover_openrouter())
        except Exception as e:
            print(f"  OpenRouter discovery failed: {e}", file=sys.stderr)

    if args.source in ("google", "all"):
        google_key = _get_key("GOOGLE_API_KEY")
        if google_key:
            try:
                all_discovered.extend(discover_google(google_key))
            except Exception as e:
                print(f"  Google discovery failed: {e}", file=sys.stderr)
        else:
            print("  Skipping Google (no GOOGLE_API_KEY found)")

    # Compute diff
    diff = diff_registry(current, all_discovered)
    added = diff["added"]

    # Count by tier
    tier_counts = {1: 0, 2: 0, 3: 0}
    for m in added:
        t = m.get("tier", 3)
        tier_counts[t] = tier_counts.get(t, 0) + 1

    print(f"\nDiscovery results:")
    print(f"  Total discovered: {diff['total_discovered']}")
    print(f"  New models:       {len(added)}")
    print(f"    Tier 2 (notable): {tier_counts[2]}")
    print(f"    Tier 3 (other):   {tier_counts[3]}")

    if args.json:
        output = {
            "total_discovered": diff["total_discovered"],
            "new_models": len(added),
            "tier2_new": tier_counts[2],
            "tier3_new": tier_counts[3],
            "added": [
                {"id": m["id"], "tier": m["tier"], "name": m.get("name", ""),
                 "context_length": m.get("context_length", 0)}
                for m in added[:50]  # Cap output
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        # Show notable additions (tier 2)
        tier2 = [m for m in added if m.get("tier") == 2]
        if tier2:
            print(f"\nNotable new models (tier 2):")
            for m in tier2[:20]:
                ctx = m.get("context_length", 0)
                ctx_str = f"{ctx // 1000}k" if ctx else "?"
                print(f"  {m['id']:50s}  ctx={ctx_str:>6s}  {m.get('name', '')[:30]}")
        if tier_counts[3] > 0:
            print(f"\n  + {tier_counts[3]} tier 3 models (use --json to see all)")

    if not added:
        print("\nRegistry is up to date. No new models found.")
        return

    if args.apply:
        rules = load_routing_rules()
        updated = merge_registry(current, all_discovered, rules)
        # Write atomically
        tmp_path = args.registry.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(updated, indent=2) + "\n")
        tmp_path.rename(args.registry)
        print(f"\nRegistry updated: {args.registry}")
        print(f"  Added {len(added)} models ({tier_counts[2]} tier2, {tier_counts[3]} tier3)")
    else:
        print(f"\nDry run — use --apply to update the registry.")


if __name__ == "__main__":
    main()
