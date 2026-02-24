#!/usr/bin/env python3
"""
source_classifier.py — Classify input URLs/paths and extract metadata.

Usage:
    python3 source_classifier.py "<url_or_path>"
    python3 source_classifier.py "<url_or_path>" --json

Outputs source type, extracted IDs, and a filesystem-safe slug.
"""

import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse, parse_qs


# ---------------------------------------------------------------------------
# Classification patterns
# ---------------------------------------------------------------------------

YOUTUBE_PATTERNS = [
    r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=(?P<id>[A-Za-z0-9_-]{11})",
    r"(?:https?://)?youtu\.be/(?P<id>[A-Za-z0-9_-]{11})",
    r"(?:https?://)?(?:www\.)?youtube\.com/embed/(?P<id>[A-Za-z0-9_-]{11})",
    r"(?:https?://)?(?:www\.)?youtube\.com/live/(?P<id>[A-Za-z0-9_-]{11})",
]

ARXIV_PATTERNS = [
    r"(?:https?://)?arxiv\.org/(?:abs|pdf)/(?P<id>\d{4}\.\d{4,5}(?:v\d+)?)",
    r"(?:https?://)?ar5iv\.labs\.arxiv\.org/html/(?P<id>\d{4}\.\d{4,5}(?:v\d+)?)",
]

SSRN_PATTERNS = [
    r"(?:https?://)?(?:papers\.)?ssrn\.com/sol3/papers\.cfm\?abstract_id=(?P<id>\d+)",
    r"(?:https?://)?ssrn\.com/abstract=(?P<id>\d+)",
]


def classify(input_str: str) -> dict:
    """Classify an input string as a source type and extract metadata.

    Returns dict with keys:
        type: youtube | arxiv | ssrn | pdf_url | pdf_local | web_article
        input: original input
        id: extracted ID (video_id, arxiv_id, ssrn_id) or None
        url: canonical URL or file path
        slug: filesystem-safe slug
    """
    input_str = input_str.strip()

    # --- YouTube ---
    for pattern in YOUTUBE_PATTERNS:
        m = re.match(pattern, input_str)
        if m:
            vid = m.group("id")
            return {
                "type": "youtube",
                "input": input_str,
                "id": vid,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "slug": f"yt-{vid}",
            }

    # --- arXiv ---
    for pattern in ARXIV_PATTERNS:
        m = re.match(pattern, input_str)
        if m:
            aid = m.group("id")
            return {
                "type": "arxiv",
                "input": input_str,
                "id": aid,
                "url": f"https://arxiv.org/abs/{aid}",
                "pdf_url": f"https://arxiv.org/pdf/{aid}.pdf",
                "slug": f"arxiv-{aid}",
            }

    # --- SSRN ---
    for pattern in SSRN_PATTERNS:
        m = re.match(pattern, input_str)
        if m:
            sid = m.group("id")
            return {
                "type": "ssrn",
                "input": input_str,
                "id": sid,
                "url": f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={sid}",
                "slug": f"ssrn-{sid}",
            }

    # --- Local PDF ---
    if os.path.isfile(input_str) and input_str.lower().endswith(".pdf"):
        basename = os.path.splitext(os.path.basename(input_str))[0]
        return {
            "type": "pdf_local",
            "input": input_str,
            "id": None,
            "url": os.path.abspath(input_str),
            "slug": generate_slug(basename),
        }

    # --- Remote PDF URL ---
    parsed = urlparse(input_str)
    if parsed.scheme in ("http", "https") and parsed.path.lower().endswith(".pdf"):
        basename = os.path.splitext(os.path.basename(parsed.path))[0]
        return {
            "type": "pdf_url",
            "input": input_str,
            "id": None,
            "url": input_str,
            "slug": generate_slug(basename),
        }

    # --- Web article (fallback) ---
    if parsed.scheme in ("http", "https"):
        slug_base = parsed.path.strip("/").split("/")[-1] or parsed.netloc
        return {
            "type": "web_article",
            "input": input_str,
            "id": None,
            "url": input_str,
            "slug": generate_slug(slug_base),
        }

    # --- Unknown / bare text ---
    return {
        "type": "unknown",
        "input": input_str,
        "id": None,
        "url": input_str,
        "slug": generate_slug(input_str[:60]),
    }


def generate_slug(text: str) -> str:
    """Convert text to a filesystem-safe slug (lowercase, hyphens, max 80 chars)."""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)   # strip special chars
    text = re.sub(r"[\s_]+", "-", text)     # spaces/underscores -> hyphens
    text = re.sub(r"-{2,}", "-", text)      # collapse multiple hyphens
    text = text.strip("-")
    return text[:80] or "untitled"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Classify a source URL or path")
    parser.add_argument("input", help="URL or local file path")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Output as JSON")
    args = parser.parse_args()

    result = classify(args.input)

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        for k, v in result.items():
            print(f"{k}: {v}")


if __name__ == "__main__":
    main()
