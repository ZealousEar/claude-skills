#!/usr/bin/env python3
"""
ssrn_download.py — Download PDFs from SSRN with Cloudflare bypass via browser cookies.

Usage:
    python3 ssrn_download.py --ssrn-id 4502819 --output paper.pdf
    python3 ssrn_download.py --ssrn-id 4502819 --cookie-file /path/to/cookies.txt --output paper.pdf

Known limitations:
    - Cloudflare ties cf_clearance to the browser's TLS fingerprint.
    - curl's TLS fingerprint differs from Chrome, so downloads may fail even with
      valid cookies. Fallback: download manually in browser, then use mathpix_convert.py --file.
"""

import argparse
import os
import subprocess
import sys

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def _detect_vault_root() -> str:
    """Resolve vault root from VAULT_ROOT env var or by walking up from CWD."""
    env = os.environ.get("VAULT_ROOT")
    if env:
        return os.path.expanduser(env)
    d = os.path.abspath(os.getcwd())
    for _ in range(10):
        if os.path.isdir(os.path.join(d, ".obsidian")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return ""

VAULT_ROOT = _detect_vault_root()
DEFAULT_COOKIE_FILE = os.path.join(VAULT_ROOT, ".credentials", "cookies", "ssrn-cookies.txt") if VAULT_ROOT else ""

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_pdf(ssrn_id: str, cookie_file: str, output_path: str) -> bool:
    """Download an SSRN PDF using curl with full browser headers.

    Returns True on success, False if the download appears to have failed.
    """
    pdf_url = f"https://papers.ssrn.com/sol3/Delivery.cfm/{ssrn_id}.pdf?abstractid={ssrn_id}"
    referer = f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={ssrn_id}"

    cmd = [
        "curl", "-s", "-L",
        "-b", cookie_file,
        "-H", f"User-Agent: {USER_AGENT}",
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "-H", "Accept-Language: en-US,en;q=0.9",
        "-H", "Accept-Encoding: gzip, deflate, br",
        "-H", "Connection: keep-alive",
        "-H", "Upgrade-Insecure-Requests: 1",
        "-H", "Sec-Fetch-Dest: document",
        "-H", "Sec-Fetch-Mode: navigate",
        "-H", "Sec-Fetch-Site: none",
        "-H", "Sec-Fetch-User: ?1",
        "-H", f"Referer: {referer}",
        "--compressed",
        "-o", output_path,
        pdf_url,
    ]

    print(f"Downloading SSRN:{ssrn_id} → {output_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"curl failed (exit {result.returncode}): {result.stderr}", file=sys.stderr)
        return False

    return verify_pdf(output_path)


def verify_pdf(filepath: str) -> bool:
    """Check that the downloaded file is a real PDF (not an HTML error page)."""
    if not os.path.isfile(filepath):
        print("Error: output file not created", file=sys.stderr)
        return False

    size = os.path.getsize(filepath)
    if size < 1024:
        print(f"Warning: file is only {size} bytes — likely not a real PDF", file=sys.stderr)

    with open(filepath, "rb") as f:
        header = f.read(5)

    if header == b"%PDF-":
        print(f"Verified: {filepath} is a valid PDF ({size:,} bytes)")
        return True

    print("Error: downloaded file is NOT a PDF (probably HTML error page).", file=sys.stderr)
    print("Likely causes:", file=sys.stderr)
    print("  1. Cookies expired (re-export from browser)", file=sys.stderr)
    print("  2. TLS fingerprint mismatch (download manually in browser)", file=sys.stderr)
    print("  3. Paper requires institutional access", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Download SSRN PDF with Cloudflare bypass")
    parser.add_argument("--ssrn-id", required=True, help="SSRN abstract ID")
    parser.add_argument("--cookie-file", default=DEFAULT_COOKIE_FILE,
                        help="Netscape-format cookie file")
    parser.add_argument("--output", required=True, help="Output PDF path")
    args = parser.parse_args()

    if not args.cookie_file or not os.path.isfile(args.cookie_file):
        msg = f"Cookie file not found: {args.cookie_file or '(none)'}\n"
        if not VAULT_ROOT:
            msg += ("Could not detect vault root. Either:\n"
                    "  1. Set VAULT_ROOT environment variable\n"
                    "  2. Run from within an Obsidian vault directory\n"
                    "  3. Pass --cookie-file explicitly\n")
        else:
            msg += "Export cookies from browser while logged into SSRN (papers.ssrn.com)."
        sys.exit(msg)

    ok = download_pdf(args.ssrn_id, args.cookie_file, args.output)
    if not ok:
        print("\nFallback: download the PDF manually in your browser, then use:")
        print(f"  python3 mathpix_convert.py --file <downloaded.pdf> --output <slug>.mathpix.md")
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()
