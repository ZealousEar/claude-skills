#!/usr/bin/env python3
"""
mathpix_convert.py — Submit PDFs to Mathpix API, poll for completion, download
                     converted markdown, and postprocess delimiters for Obsidian.

Usage:
    python3 mathpix_convert.py --url  "https://arxiv.org/pdf/2301.12345.pdf" --output paper.mathpix.md
    python3 mathpix_convert.py --file "/path/to/paper.pdf" --output paper.mathpix.md
    python3 mathpix_convert.py --file paper.pdf --output paper.mathpix.md --skip-postprocess
    python3 mathpix_convert.py --file paper.pdf --output paper.mathpix.md --page-ranges "1-10"

Credentials are loaded from .credentials/dissertation-research/.env (MATHPIX_APP_ID,
MATHPIX_APP_KEY). The path is resolved relative to the vault root.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

VAULT_ROOT = os.environ.get("VAULT_ROOT", os.getcwd())
DEFAULT_ENV = os.environ.get("MATHPIX_ENV", os.path.join(VAULT_ROOT, ".credentials", "dissertation-research", ".env"))
MATHPIX_BASE = "https://api.mathpix.com/v3/pdf"
POLL_INTERVAL = 5   # seconds
POLL_TIMEOUT = 300   # seconds


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def load_credentials(env_path: str = DEFAULT_ENV) -> tuple[str, str]:
    """Read MATHPIX_APP_ID and MATHPIX_APP_KEY from a .env file."""
    creds = {}
    if not os.path.isfile(env_path):
        sys.exit(f"Error: credentials file not found at {env_path}")

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                creds[k.strip()] = v.strip().strip('"').strip("'")

    app_id = creds.get("MATHPIX_APP_ID")
    app_key = creds.get("MATHPIX_APP_KEY")
    if not app_id or not app_key:
        sys.exit("Error: MATHPIX_APP_ID and MATHPIX_APP_KEY must be set in .env")
    return app_id, app_key


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def submit_url(url: str, app_id: str, app_key: str, page_ranges: str | None = None) -> str:
    """Submit a PDF URL to Mathpix. Returns pdf_id."""
    payload = {"url": url}
    if page_ranges:
        payload["page_ranges"] = page_ranges

    cmd = [
        "curl", "-s", "-X", "POST", MATHPIX_BASE,
        "-H", f"app_id: {app_id}",
        "-H", f"app_key: {app_key}",
        "-H", "Content-Type: application/json",
        "--data", json.dumps(payload),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    resp = json.loads(result.stdout)
    if "pdf_id" not in resp:
        sys.exit(f"Error submitting URL: {resp}")
    print(f"Submitted URL → pdf_id: {resp['pdf_id']}")
    return resp["pdf_id"]


def submit_file(filepath: str, app_id: str, app_key: str, page_ranges: str | None = None) -> str:
    """Submit a local PDF file to Mathpix. Returns pdf_id."""
    if not os.path.isfile(filepath):
        sys.exit(f"Error: file not found: {filepath}")

    cmd = [
        "curl", "-s", "-X", "POST", MATHPIX_BASE,
        "-H", f"app_id: {app_id}",
        "-H", f"app_key: {app_key}",
        "--form", f"file=@{filepath}",
    ]
    if page_ranges:
        cmd += ["--form", f"options_json={json.dumps({'page_ranges': page_ranges})}"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    resp = json.loads(result.stdout)
    if "pdf_id" not in resp:
        sys.exit(f"Error submitting file: {resp}")
    print(f"Submitted file → pdf_id: {resp['pdf_id']}")
    return resp["pdf_id"]


def poll_status(pdf_id: str, app_id: str, app_key: str,
                interval: int = POLL_INTERVAL, timeout: int = POLL_TIMEOUT) -> bool:
    """Poll Mathpix until processing completes. Returns True on success."""
    elapsed = 0
    while elapsed < timeout:
        cmd = [
            "curl", "-s", "-X", "GET", f"{MATHPIX_BASE}/{pdf_id}",
            "-H", f"app_id: {app_id}",
            "-H", f"app_key: {app_key}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        resp = json.loads(result.stdout)
        status = resp.get("status", "unknown")
        pct = resp.get("percent_done", 0)
        print(f"  Status: {status} ({pct}%)")

        if status == "completed":
            return True
        if status == "error":
            sys.exit(f"Mathpix processing error: {resp}")

        time.sleep(interval)
        elapsed += interval

    sys.exit(f"Timeout after {timeout}s waiting for pdf_id={pdf_id}")


def download_mmd(pdf_id: str, app_id: str, app_key: str, output_path: str) -> str:
    """Download the converted .mmd markdown. Returns output path."""
    cmd = [
        "curl", "-s", "-X", "GET", f"{MATHPIX_BASE}/{pdf_id}.mmd",
        "-H", f"app_id: {app_id}",
        "-H", f"app_key: {app_key}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    with open(output_path, "w") as f:
        f.write(result.stdout)
    print(f"Downloaded → {output_path} ({len(result.stdout)} chars)")
    return output_path


# ---------------------------------------------------------------------------
# Postprocessing
# ---------------------------------------------------------------------------

def postprocess_delimiters(filepath: str) -> int:
    """Convert Mathpix delimiters to Obsidian-compatible ones.

    \\(...\\)  →  $...$       (inline math)
    \\[...\\]  →  $$...$$     (display math)

    Returns the number of replacements made.
    """
    with open(filepath, "r") as f:
        content = f.read()

    original = content
    # Inline: \(...\) → $...$
    content = re.sub(r"\\\((.+?)\\\)", r"$\1$", content, flags=re.DOTALL)
    # Display: \[...\] → $$...$$  (only when on own line or bracketing block)
    content = re.sub(r"\\\[(.+?)\\\]", r"$$\1$$", content, flags=re.DOTALL)

    replacements = 0
    if content != original:
        with open(filepath, "w") as f:
            f.write(content)
        # Count changes (rough)
        replacements += original.count("\\(") - content.count("\\(")
        replacements += original.count("\\[") - content.count("\\[")

    print(f"Postprocessed delimiters: ~{replacements} replacements")
    return replacements


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Mathpix PDF → Markdown converter")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="PDF URL to submit")
    group.add_argument("--file", help="Local PDF file to submit")
    parser.add_argument("--output", required=True, help="Output .mathpix.md path")
    parser.add_argument("--env", default=DEFAULT_ENV, help="Path to .env with Mathpix creds")
    parser.add_argument("--page-ranges", help="Page ranges to process (e.g. '1-10')")
    parser.add_argument("--skip-postprocess", action="store_true",
                        help="Skip delimiter postprocessing")
    parser.add_argument("--poll-interval", type=int, default=POLL_INTERVAL)
    parser.add_argument("--poll-timeout", type=int, default=POLL_TIMEOUT)
    args = parser.parse_args()

    app_id, app_key = load_credentials(args.env)

    if args.url:
        pdf_id = submit_url(args.url, app_id, app_key, args.page_ranges)
    else:
        pdf_id = submit_file(args.file, app_id, app_key, args.page_ranges)

    poll_status(pdf_id, app_id, app_key, args.poll_interval, args.poll_timeout)
    download_mmd(pdf_id, app_id, app_key, args.output)

    if not args.skip_postprocess:
        postprocess_delimiters(args.output)

    print(f"Done: {args.output}")


if __name__ == "__main__":
    main()
