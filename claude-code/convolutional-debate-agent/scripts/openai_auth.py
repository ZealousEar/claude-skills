#!/usr/bin/env python3
"""OAuth Device Flow authentication for OpenAI, matching the Codex CLI flow.

Authenticates with your ChatGPT account via browser — no manual API key needed.
After login, exchanges the OAuth token for an OpenAI API key automatically.

Usage:
    python3 openai_auth.py login       # Authenticate via browser
    python3 openai_auth.py status      # Show current auth status
    python3 openai_auth.py refresh     # Refresh tokens and API key
    python3 openai_auth.py logout      # Clear stored tokens
    python3 openai_auth.py token       # Print current API key (for piping)
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

# --- Constants (from Codex CLI source: codex-rs/core/src/auth.rs) ---

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
ISSUER = "https://auth.openai.com"

# Device flow endpoints
DEVICE_USERCODE_URL = f"{ISSUER}/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = f"{ISSUER}/api/accounts/deviceauth/token"
DEVICE_VERIFY_URL = f"{ISSUER}/codex/device"
DEVICE_CALLBACK_URL = f"{ISSUER}/deviceauth/callback"

# Standard OAuth token endpoint (for code exchange, refresh, API key exchange)
OAUTH_TOKEN_URL = f"{ISSUER}/oauth/token"

# Token refresh interval (days) — matches Codex CLI's 8-day staleness check
TOKEN_REFRESH_DAYS = 8

# Default paths
SKILL_DIR = Path.home() / ".claude" / "skills" / "convolutional-debate-agent"
TOKEN_FILE = SKILL_DIR / "api-keys" / "openai-oauth.json"

# Polling
DEFAULT_POLL_INTERVAL = 5
DEVICE_CODE_TIMEOUT = 900  # 15 minutes


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


_COMMON_HEADERS = {
    "User-Agent": "convolutional-debate-agent/1.0",
    "Accept": "application/json",
}


def _post_json(url: str, body: dict, timeout: int = 30) -> tuple[int, dict]:
    """POST JSON and return (status_code, parsed_response)."""
    data = json.dumps(body).encode("utf-8")
    headers = {**_COMMON_HEADERS, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body_text)
        except json.JSONDecodeError:
            return e.code, {"error": body_text}


def _post_form(url: str, params: dict, timeout: int = 30) -> tuple[int, dict]:
    """POST form-encoded data and return (status_code, parsed_response)."""
    data = urllib.parse.urlencode(params).encode("utf-8")
    headers = {**_COMMON_HEADERS, "Content-Type": "application/x-www-form-urlencoded"}
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body_text)
        except json.JSONDecodeError:
            return e.code, {"error": body_text}


def _save_tokens(token_path: Path, token_data: dict) -> None:
    """Save tokens to file with restrictive permissions (0600)."""
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps(token_data, indent=2) + "\n")
    os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600


def _load_tokens(token_path: Path) -> dict | None:
    """Load tokens from file, or return None if not found."""
    if not token_path.exists():
        return None
    try:
        return json.loads(token_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _is_stale(token_data: dict) -> bool:
    """Check if tokens are older than TOKEN_REFRESH_DAYS."""
    last_refresh = token_data.get("last_refresh")
    if not last_refresh:
        return True
    try:
        refreshed_at = datetime.fromisoformat(last_refresh)
        age_days = (datetime.now(timezone.utc) - refreshed_at).days
        return age_days >= TOKEN_REFRESH_DAYS
    except (ValueError, TypeError):
        return True


# --- Device Flow ---

def request_device_code() -> dict:
    """Step 1: Request a device code and user code from OpenAI."""
    status, resp = _post_json(DEVICE_USERCODE_URL, {"client_id": CLIENT_ID})
    if status != 200:
        raise RuntimeError(
            f"Failed to request device code (HTTP {status}): {resp}"
        )
    required = ("device_auth_id", "user_code")
    for key in required:
        if key not in resp:
            raise RuntimeError(f"Missing '{key}' in device code response: {resp}")
    return resp


def poll_for_authorization(device_auth_id: str, user_code: str, interval: int) -> dict:
    """Step 3: Poll until the user authorizes (or timeout)."""
    start = time.time()
    while time.time() - start < DEVICE_CODE_TIMEOUT:
        time.sleep(interval)
        status, resp = _post_json(DEVICE_TOKEN_URL, {
            "device_auth_id": device_auth_id,
            "user_code": user_code,
        })
        if status == 200:
            # Authorized — response contains authorization_code + PKCE values
            return resp
        if status in (403, 404):
            # Not yet authorized, keep polling
            sys.stdout.write(".")
            sys.stdout.flush()
            continue
        # Unexpected error
        raise RuntimeError(
            f"Unexpected response while polling (HTTP {status}): {resp}"
        )
    raise TimeoutError("Device authorization timed out (15 minutes). Please try again.")


def exchange_code_for_tokens(authorization_code: str, code_verifier: str) -> dict:
    """Step 4: Exchange the authorization code for OAuth tokens."""
    status, resp = _post_form(OAUTH_TOKEN_URL, {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": DEVICE_CALLBACK_URL,
        "client_id": CLIENT_ID,
        "code_verifier": code_verifier,
    })
    if status != 200:
        raise RuntimeError(
            f"Token exchange failed (HTTP {status}): {resp}"
        )
    return resp


def exchange_token_for_api_key(id_token: str) -> str | None:
    """Exchange an id_token for an OpenAI API key (token exchange grant)."""
    status, resp = _post_form(OAUTH_TOKEN_URL, {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "client_id": CLIENT_ID,
        "requested_token": "openai-api-key",
        "subject_token": id_token,
        "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
    })
    if status != 200:
        print(f"  Warning: API key exchange failed (HTTP {status}): {resp}", file=sys.stderr)
        return None
    # The response should contain the API key
    api_key = resp.get("access_token") or resp.get("api_key") or resp.get("token")
    return api_key


def refresh_tokens(refresh_token: str) -> dict:
    """Refresh OAuth tokens using the refresh token."""
    status, resp = _post_form(OAUTH_TOKEN_URL, {
        "client_id": CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "openid profile email",
    })
    if status == 401:
        error_code = resp.get("error", "")
        permanent_errors = (
            "refresh_token_expired",
            "refresh_token_reused",
            "refresh_token_invalidated",
        )
        if error_code in permanent_errors:
            raise RuntimeError(
                f"Refresh token is no longer valid ({error_code}). "
                f"Please run 'login' again to re-authenticate."
            )
        raise RuntimeError(f"Token refresh failed (HTTP 401): {resp}")
    if status != 200:
        raise RuntimeError(f"Token refresh failed (HTTP {status}): {resp}")
    return resp


# --- Commands ---

def do_login(token_path: Path) -> None:
    """Full device flow login: get code → user authorizes → exchange → store."""
    print("Authenticating with your ChatGPT account...\n")

    # Step 1: Request device code
    device_resp = request_device_code()
    device_auth_id = device_resp["device_auth_id"]
    user_code = device_resp["user_code"]
    interval = int(device_resp.get("interval", DEFAULT_POLL_INTERVAL))

    # Step 2: Show instructions and open browser
    verify_url = DEVICE_VERIFY_URL
    print(f"  1. Open this URL in your browser:")
    print(f"     {verify_url}\n")
    print(f"  2. Enter this code when prompted:")
    print(f"     {user_code}\n")

    # Try to open browser automatically
    try:
        webbrowser.open(verify_url)
        print("  (Browser opened automatically)")
    except Exception:
        print("  (Could not open browser automatically — please open the URL manually)")

    print(f"\nWaiting for authorization", end="")
    sys.stdout.flush()

    # Step 3: Poll for authorization
    try:
        auth_resp = poll_for_authorization(device_auth_id, user_code, interval)
    except TimeoutError as e:
        print(f"\n{e}")
        sys.exit(1)

    print(" done!\n")

    authorization_code = auth_resp.get("authorization_code")
    code_verifier = auth_resp.get("code_verifier")
    if not authorization_code or not code_verifier:
        print(f"Error: Missing authorization_code or code_verifier in response.", file=sys.stderr)
        sys.exit(1)

    # Step 4: Exchange code for tokens
    print("Exchanging code for tokens...")
    token_resp = exchange_code_for_tokens(authorization_code, code_verifier)

    id_token = token_resp.get("id_token", "")
    access_token = token_resp.get("access_token", "")
    refresh_token_val = token_resp.get("refresh_token", "")

    # Step 5: Exchange id_token for API key
    api_key = None
    if id_token:
        print("Obtaining API key from ChatGPT account...")
        api_key = exchange_token_for_api_key(id_token)

    # Step 6: Store everything
    token_data = {
        "auth_mode": "chatgpt_oauth",
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token_val,
        "openai_api_key": api_key,
        "last_refresh": datetime.now(timezone.utc).isoformat(),
    }
    _save_tokens(token_path, token_data)

    print(f"\nLogin successful! Tokens saved to {token_path}")
    if api_key:
        print(f"API key obtained: {api_key[:12]}...{api_key[-4:]}")
        print("\nYou can now use 'chatgpt-5.2' and other OpenAI models in the debate agent")
        print("without setting OPENAI_API_KEY manually.")
    else:
        print("\nWarning: Could not obtain API key via token exchange.")
        print("You may need to set OPENAI_API_KEY manually in provider-keys.env")


def do_refresh(token_path: Path) -> None:
    """Refresh stored tokens and re-exchange for API key."""
    token_data = _load_tokens(token_path)
    if not token_data:
        print("No stored tokens found. Run 'login' first.", file=sys.stderr)
        sys.exit(1)

    rt = token_data.get("refresh_token")
    if not rt:
        print("No refresh token stored. Run 'login' first.", file=sys.stderr)
        sys.exit(1)

    print("Refreshing tokens...")
    try:
        resp = refresh_tokens(rt)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Update only fields that were returned
    if resp.get("id_token"):
        token_data["id_token"] = resp["id_token"]
    if resp.get("access_token"):
        token_data["access_token"] = resp["access_token"]
    if resp.get("refresh_token"):
        token_data["refresh_token"] = resp["refresh_token"]

    # Re-exchange for API key
    id_token = token_data.get("id_token")
    if id_token:
        print("Re-obtaining API key...")
        api_key = exchange_token_for_api_key(id_token)
        if api_key:
            token_data["openai_api_key"] = api_key

    token_data["last_refresh"] = datetime.now(timezone.utc).isoformat()
    _save_tokens(token_path, token_data)

    print("Tokens refreshed successfully.")
    api_key = token_data.get("openai_api_key")
    if api_key:
        print(f"API key: {api_key[:12]}...{api_key[-4:]}")


def do_status(token_path: Path) -> None:
    """Show current authentication status."""
    token_data = _load_tokens(token_path)
    if not token_data:
        print("Status: Not logged in")
        print(f"  Run: python3 {__file__} login")
        return

    print("Status: Logged in (ChatGPT OAuth)")
    print(f"  Token file: {token_path}")

    last_refresh = token_data.get("last_refresh", "unknown")
    print(f"  Last refresh: {last_refresh}")

    stale = _is_stale(token_data)
    print(f"  Tokens stale: {'yes (run refresh)' if stale else 'no'}")

    api_key = token_data.get("openai_api_key")
    if api_key:
        print(f"  API key: {api_key[:12]}...{api_key[-4:]}")
    else:
        print("  API key: not available")

    has_refresh = bool(token_data.get("refresh_token"))
    print(f"  Refresh token: {'present' if has_refresh else 'missing'}")


def do_logout(token_path: Path) -> None:
    """Clear stored tokens."""
    if token_path.exists():
        token_path.unlink()
        print("Logged out. Tokens cleared.")
    else:
        print("No stored tokens to clear.")


def do_token(token_path: Path) -> None:
    """Print the current API key to stdout (for piping/scripting)."""
    token_data = _load_tokens(token_path)
    if not token_data:
        print("Not logged in.", file=sys.stderr)
        sys.exit(1)

    # Auto-refresh if stale
    if _is_stale(token_data):
        rt = token_data.get("refresh_token")
        if rt:
            try:
                resp = refresh_tokens(rt)
                if resp.get("id_token"):
                    token_data["id_token"] = resp["id_token"]
                if resp.get("access_token"):
                    token_data["access_token"] = resp["access_token"]
                if resp.get("refresh_token"):
                    token_data["refresh_token"] = resp["refresh_token"]
                id_token = token_data.get("id_token")
                if id_token:
                    api_key = exchange_token_for_api_key(id_token)
                    if api_key:
                        token_data["openai_api_key"] = api_key
                token_data["last_refresh"] = datetime.now(timezone.utc).isoformat()
                _save_tokens(token_path, token_data)
            except RuntimeError as e:
                print(f"Auto-refresh failed: {e}", file=sys.stderr)

    api_key = token_data.get("openai_api_key")
    if api_key:
        print(api_key)
    else:
        print("No API key available. Run 'login' or 'refresh'.", file=sys.stderr)
        sys.exit(1)


# --- Main ---

def main() -> None:
    parser = argparse.ArgumentParser(
        description="OpenAI OAuth authentication for the Convolutional Debate Agent. "
                    "Log in with your ChatGPT account — no manual API key needed."
    )
    parser.add_argument(
        "command",
        choices=["login", "logout", "status", "refresh", "token"],
        help="login: authenticate via browser | "
             "status: show auth status | "
             "refresh: refresh tokens | "
             "logout: clear tokens | "
             "token: print API key",
    )
    parser.add_argument(
        "--token-file", type=Path, default=TOKEN_FILE,
        help=f"Path to token storage file (default: {TOKEN_FILE})",
    )
    args = parser.parse_args()

    commands = {
        "login": do_login,
        "logout": do_logout,
        "status": do_status,
        "refresh": do_refresh,
        "token": do_token,
    }
    commands[args.command](args.token_file)


if __name__ == "__main__":
    main()
