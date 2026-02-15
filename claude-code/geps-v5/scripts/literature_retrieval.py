#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by", "for",
    "from", "has", "have", "if", "in", "into", "is", "it", "its", "of", "on",
    "or", "that", "the", "their", "this", "to", "was", "were", "will", "with",
    "we", "our", "you", "your", "they", "them", "these", "those", "which",
    "can", "could", "should", "would", "may", "might", "than", "then", "also",
    "about", "over", "under", "between", "across", "using", "use", "used",
    "paper", "study", "approach", "method", "methods", "results", "result",
}

SUPPORTED_LOCAL_SUFFIXES = {".json", ".md", ".markdown"}
DEFAULT_CACHE_DIR = Path("/tmp/geps_retrieval_cache")
DEFAULT_LLM_RUNNER = Path("~/.claude/skills/convolutional-debate-agent/scripts/llm_runner.py").expanduser()
DEFAULT_PROMPT_TEMPLATE = Path(__file__).resolve().parent.parent / "prompts" / "retrieval_summarizer.md"
_LAST_API_CALL_TS = 0.0


def warn(message: str) -> None:
    """Print a warning to stderr."""
    print(f"Warning: {message}", file=sys.stderr)


def fail(message: str, code: int = 1) -> None:
    """Print an error and exit."""
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(code)


def clean_text(value: object) -> str:
    """Normalize whitespace for text-like values."""
    if value is None:
        return ""
    text = str(value)
    return re.sub(r"\s+", " ", text).strip()


def normalize_keywords(value: object) -> list[str]:
    """Convert keyword input into a normalized list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [clean_text(x) for x in value if clean_text(x)]
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            if not inner:
                return []
            parts = [p.strip().strip("\"'") for p in inner.split(",")]
            return [p for p in parts if p]
        parts = [p.strip() for p in re.split(r"[;,]", raw)]
        return [p for p in parts if p]
    return [clean_text(value)] if clean_text(value) else []


def parse_year(value: object) -> int | None:
    """Parse year-like values into int."""
    if value is None:
        return None
    text = clean_text(value)
    match = re.search(r"\b(19|20)\d{2}\b", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def md5_hex(text: str) -> str:
    """Compute an MD5 hex digest via system tools (no external Python deps)."""
    payload = text.encode("utf-8")
    commands = [["md5sum"], ["md5"]]
    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd,
                input=payload,
                capture_output=True,
                check=False,
            )
        except OSError:
            continue
        if proc.returncode != 0:
            continue
        out = clean_text(proc.stdout.decode("utf-8", errors="replace"))
        if cmd[0] == "md5sum":
            digest = out.split(" ")[0]
            if re.fullmatch(r"[0-9a-fA-F]{32}", digest):
                return digest.lower()
        if cmd[0] == "md5":
            match = re.search(r"([0-9a-fA-F]{32})", out)
            if match:
                return match.group(1).lower()
    # Portable fallback: use Python stdlib hashlib in a subprocess.
    try:
        proc = subprocess.run(
            [
                "python3",
                "-c",
                "import hashlib,sys;print(hashlib.md5(sys.stdin.buffer.read()).hexdigest())",
            ],
            input=payload,
            capture_output=True,
            check=False,
        )
        digest = clean_text(proc.stdout.decode("utf-8", errors="replace"))
        if proc.returncode == 0 and re.fullmatch(r"[0-9a-fA-F]{32}", digest):
            return digest.lower()
    except OSError:
        pass
    # Last resort deterministic fallback.
    h = 1469598103934665603
    for b in payload:
        h ^= b
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}{(h ^ len(payload) ^ 0x9E3779B97F4A7C15):016x}"


def resolve_query_text(query_arg: str) -> str:
    """Resolve --query argument as either file path or raw text."""
    candidate = Path(query_arg).expanduser()
    if candidate.exists() and candidate.is_file():
        return clean_text(candidate.read_text())
    return clean_text(query_arg)


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alpha, remove stopwords."""
    words = re.split(r"[^a-zA-Z]+", text.lower())
    return [w for w in words if len(w) > 1 and w not in STOPWORDS]


def _build_idf(tokenized_docs: list[list[str]]) -> dict[str, float]:
    """Build IDF map from tokenized docs."""
    doc_count = len(tokenized_docs)
    if doc_count == 0:
        return {}
    df: collections.Counter[str] = collections.Counter()
    for tokens in tokenized_docs:
        for term in set(tokens):
            df[term] += 1
    return {term: math.log((1.0 + doc_count) / (1.0 + freq)) + 1.0 for term, freq in df.items()}


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    """Build one sparse TF-IDF vector."""
    if not tokens:
        return {}
    counts: collections.Counter[str] = collections.Counter(tokens)
    total = float(sum(counts.values()))
    vector: dict[str, float] = {}
    for term, count in counts.items():
        if term in idf:
            vector[term] = (count / total) * idf[term]
    return vector


def build_tfidf_index(docs: list[dict]) -> tuple[list[dict[str, float]], list[str]]:
    """Build TF-IDF vectors for a corpus of documents."""
    tokenized_docs = [tokenize(clean_text(doc.get("_tfidf_text", ""))) for doc in docs]
    idf = _build_idf(tokenized_docs)
    vectors = [_tfidf_vector(tokens, idf) for tokens in tokenized_docs]
    vocab = sorted(idf.keys())
    return vectors, vocab


def cosine_similarity(v1: dict[str, float], v2: dict[str, float]) -> float:
    """Cosine similarity between two sparse TF-IDF vectors."""
    if not v1 or not v2:
        return 0.0
    if len(v1) > len(v2):
        v1, v2 = v2, v1
    dot = 0.0
    for key, val in v1.items():
        dot += val * v2.get(key, 0.0)
    n1 = math.sqrt(sum(v * v for v in v1.values()))
    n2 = math.sqrt(sum(v * v for v in v2.values()))
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return dot / (n1 * n2)


def parse_yaml_frontmatter(raw: str) -> dict[str, object]:
    """Parse simple YAML frontmatter (key: value and key: [a,b]/- list)."""
    data: dict[str, object] = {}
    active_list_key: str | None = None
    for raw_line in raw.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        key_match = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if key_match:
            key = key_match.group(1).strip().lower()
            value = key_match.group(2).strip()
            active_list_key = None
            if value == "":
                data[key] = []
                active_list_key = key
            elif value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                data[key] = normalize_keywords(inner)
            else:
                data[key] = value.strip("\"'")
            continue
        list_match = re.match(r"^\s*-\s+(.*)$", line)
        if list_match and active_list_key:
            item = list_match.group(1).strip().strip("\"'")
            if isinstance(data.get(active_list_key), list):
                data[active_list_key].append(item)
    return data


def parse_markdown_paper(path: Path) -> dict | None:
    """Parse one markdown file into a normalized paper record."""
    text = path.read_text()
    frontmatter: dict[str, object] = {}
    body = text
    if text.startswith("---"):
        lines = text.splitlines()
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is not None:
            frontmatter = parse_yaml_frontmatter("\n".join(lines[1:end]))
            body = "\n".join(lines[end + 1 :])

    title = clean_text(frontmatter.get("title")) or path.stem
    abstract = clean_text(frontmatter.get("abstract"))
    body_text = clean_text(re.sub(r"`{3}.*?`{3}", " ", body, flags=re.S))
    if not abstract:
        abstract = body_text[:2000]
    keywords = normalize_keywords(frontmatter.get("keywords"))
    authors = frontmatter.get("authors")
    if isinstance(authors, list):
        authors_str = ", ".join(clean_text(a) for a in authors if clean_text(a))
    else:
        authors_str = clean_text(authors)

    return {
        "title": title,
        "authors": authors_str,
        "year": parse_year(frontmatter.get("year")),
        "venue": clean_text(frontmatter.get("venue")),
        "abstract": abstract,
        "keywords": keywords,
        "_tfidf_text": clean_text(" ".join([title, abstract, " ".join(keywords), body_text])),
        "_source": str(path),
    }


def _normalize_paper_record(record: dict, fallback_title: str, source: str) -> dict | None:
    """Normalize a JSON object to the internal paper schema."""
    title = clean_text(record.get("title")) or fallback_title
    abstract = clean_text(record.get("abstract")) or clean_text(record.get("summary"))
    keywords = normalize_keywords(record.get("keywords"))
    authors = record.get("authors")
    if isinstance(authors, list):
        authors_str = ", ".join(clean_text(a.get("name") if isinstance(a, dict) else a) for a in authors if clean_text(a.get("name") if isinstance(a, dict) else a))
    else:
        authors_str = clean_text(authors)
    venue = clean_text(record.get("venue"))
    year = parse_year(record.get("year"))
    if not (title or abstract):
        return None
    return {
        "title": title or fallback_title,
        "authors": authors_str,
        "year": year,
        "venue": venue,
        "abstract": abstract,
        "keywords": keywords,
        "_tfidf_text": clean_text(" ".join([title, abstract, " ".join(keywords)])),
        "_source": source,
    }


def parse_json_papers(path: Path) -> list[dict]:
    """Parse one JSON file into zero or more normalized paper records."""
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        warn(f"Skipping invalid JSON file: {path}")
        return []

    records: list[dict] = []
    if isinstance(data, dict):
        if isinstance(data.get("results"), list):
            for i, item in enumerate(data["results"]):
                if isinstance(item, dict):
                    norm = _normalize_paper_record(item, f"{path.stem}-{i+1}", str(path))
                    if norm:
                        records.append(norm)
        else:
            norm = _normalize_paper_record(data, path.stem, str(path))
            if norm:
                records.append(norm)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, dict):
                norm = _normalize_paper_record(item, f"{path.stem}-{i+1}", str(path))
                if norm:
                    records.append(norm)
    return records


def load_local_corpus(corpus_dir: Path) -> list[dict]:
    """Load all supported papers from a local corpus directory."""
    if not corpus_dir.exists() or not corpus_dir.is_dir():
        raise ValueError(f"Corpus directory does not exist: {corpus_dir}")
    files = [p for p in corpus_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_LOCAL_SUFFIXES]
    if not files:
        raise ValueError(f"Corpus directory is empty (no JSON/Markdown papers): {corpus_dir}")

    docs: list[dict] = []
    for path in sorted(files):
        if path.suffix.lower() == ".json":
            docs.extend(parse_json_papers(path))
        else:
            parsed = parse_markdown_paper(path)
            if parsed:
                docs.append(parsed)

    if not docs:
        raise ValueError(f"No parseable papers found in corpus: {corpus_dir}")
    return docs


def retrieve_local(query_text: str, corpus_dir: Path, top_k: int) -> list[dict]:
    """Scan corpus, build index, return top-K by cosine sim."""
    docs = load_local_corpus(corpus_dir)
    doc_vectors, _ = build_tfidf_index(docs)
    tokenized_docs = [tokenize(clean_text(doc.get("_tfidf_text", ""))) for doc in docs]
    idf = _build_idf(tokenized_docs)
    query_vector = _tfidf_vector(tokenize(query_text), idf)

    ranked: list[tuple[float, dict]] = []
    for i, doc in enumerate(docs):
        score = cosine_similarity(query_vector, doc_vectors[i])
        item = {
            "title": doc.get("title", ""),
            "authors": doc.get("authors", ""),
            "year": doc.get("year"),
            "venue": doc.get("venue", ""),
            "abstract": doc.get("abstract", ""),
            "similarity": score,
        }
        ranked.append((score, item))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in ranked[:top_k]]


def cache_path(cache_dir: Path, key: str) -> Path:
    """Return cache file path for key."""
    return cache_dir / f"{key}.json"


def load_cache(path: Path, ttl_days: int, allow_stale: bool = False) -> list[dict] | None:
    """Load cached results if present and fresh (or stale allowed)."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return None
    created_at = payload.get("created_at")
    if not isinstance(created_at, (int, float)):
        return None
    if not allow_stale:
        age = time.time() - float(created_at)
        if age > max(ttl_days, 0) * 86400:
            return None
    results: list[dict] = []
    for item in payload["results"]:
        if isinstance(item, dict):
            results.append(item)
    return results


def write_cache(path: Path, query: str, mode: str, results: list[dict]) -> None:
    """Write retrieval results to cache."""
    payload = {
        "created_at": time.time(),
        "query": query,
        "mode": mode,
        "results": results,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    except OSError as exc:
        warn(f"Failed to write cache {path}: {exc}")


def _rate_limit_semantic_scholar() -> None:
    """Enforce max one Semantic Scholar request per second."""
    global _LAST_API_CALL_TS
    now = time.time()
    delta = now - _LAST_API_CALL_TS
    if delta < 1.0:
        time.sleep(1.0 - delta)
    _LAST_API_CALL_TS = time.time()


def extract_query_terms(query_text: str, max_terms: int = 12) -> str:
    """Extract key terms from query text using title-like first line + keyword hints."""
    lines = [clean_text(line) for line in query_text.splitlines() if clean_text(line)]
    title = lines[0] if lines else query_text
    kw_lines = re.findall(r"(?im)^keywords?\s*[:\-]\s*(.+)$", query_text)
    combined = " ".join([title, " ".join(kw_lines), query_text])
    counts: collections.Counter[str] = collections.Counter(tokenize(combined))
    if not counts:
        return clean_text(query_text)[:300]
    terms = [term for term, _ in counts.most_common(max_terms)]
    return " ".join(terms)


def query_semantic_scholar(query_terms: str, top_k: int) -> list[dict]:
    """Call Semantic Scholar paper search API and return normalized records."""
    _rate_limit_semantic_scholar()
    params = {
        "query": query_terms,
        "limit": str(top_k),
        "fields": "title,abstract,year,authors,venue",
    }
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/json"}
    api_key = os.environ.get("S2_API_KEY", "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        warn(f"Semantic Scholar API error {exc.code}: {body[:300]}")
        return []
    except urllib.error.URLError:
        raise

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        warn("Semantic Scholar returned non-JSON response")
        return []

    data = payload.get("data", [])
    if not isinstance(data, list):
        return []
    results: list[dict] = []
    for paper in data:
        if not isinstance(paper, dict):
            continue
        author_objs = paper.get("authors", [])
        author_names: list[str] = []
        if isinstance(author_objs, list):
            for author in author_objs:
                if isinstance(author, dict):
                    name = clean_text(author.get("name"))
                    if name:
                        author_names.append(name)
        results.append(
            {
                "title": clean_text(paper.get("title")),
                "authors": ", ".join(author_names),
                "year": parse_year(paper.get("year")),
                "venue": clean_text(paper.get("venue")),
                "abstract": clean_text(paper.get("abstract")),
            }
        )
    return results[:top_k]


def retrieve_api(query_text: str, top_k: int, cache_dir: Path, cache_ttl_days: int) -> list[dict]:
    """Retrieve papers from Semantic Scholar with cache + stale fallback on URLError."""
    key = md5_hex(f"api::{query_text}")
    path = cache_path(cache_dir, key)
    cached = load_cache(path, cache_ttl_days, allow_stale=False)
    if cached is not None:
        return cached[:top_k]

    query_terms = extract_query_terms(query_text)
    try:
        results = query_semantic_scholar(query_terms, top_k)
    except urllib.error.URLError as exc:
        warn(f"Semantic Scholar network error: {exc}")
        stale = load_cache(path, cache_ttl_days, allow_stale=True)
        if stale is not None:
            warn("Using stale cached results due to network error")
            return stale[:top_k]
        return []

    write_cache(path, query_text, "api", results)
    return results[:top_k]


def retrieve_manual(retrieved_json: Path, top_k: int) -> list[dict]:
    """Load pre-retrieved summaries from JSON file."""
    if not retrieved_json.exists() or not retrieved_json.is_file():
        raise ValueError(f"retrieved-json file not found: {retrieved_json}")
    data = json.loads(retrieved_json.read_text())
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        items = data["results"]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("retrieved-json must be a list of papers or object with 'results' list")
    results: list[dict] = []
    for item in items[:top_k]:
        if isinstance(item, dict):
            results.append(item)
    return results


def render_template(template: str, mapping: dict[str, str]) -> str:
    """Fill template placeholders using safe string replacement."""
    rendered = template
    for key, value in mapping.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def parse_normalized_output(text: str) -> dict[str, object]:
    """Parse retrieval_summarizer output template into normalized fields."""
    normalized: dict[str, object] = {
        "research_question": "NOT STATED",
        "hypothesis": [],
        "identification": "NOT STATED",
        "data": "NOT STATED",
        "contribution": "NOT STATED",
        "limitations": [],
    }
    scalar_map = {
        "research question": "research_question",
        "identification strategy": "identification",
        "data": "data",
        "contribution": "contribution",
    }
    list_map = {"hypothesis": "hypothesis", "limitations": "limitations"}
    active_field: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        header = re.match(
            r"^(Title|Research Question|Hypothesis|Identification Strategy|Data|Contribution|Limitations)\s*:\s*(.*)$",
            line,
            flags=re.I,
        )
        if header:
            label = header.group(1).lower()
            value = clean_text(header.group(2))
            if label in scalar_map:
                key = scalar_map[label]
                normalized[key] = value or "NOT STATED"
                active_field = key
            elif label in list_map:
                key = list_map[label]
                active_field = key
                if value:
                    value = re.sub(r"^[-*]\s*", "", value)
                    if value:
                        cast_list = normalized[key]
                        if isinstance(cast_list, list):
                            cast_list.append(value)
            else:
                active_field = None
            continue

        bullet = re.match(r"^[-*]\s+(.*)$", line)
        if bullet and active_field in {"hypothesis", "limitations"}:
            entry = clean_text(bullet.group(1))
            if entry:
                cast_list = normalized[active_field]
                if isinstance(cast_list, list):
                    cast_list.append(entry)
            continue

        if active_field in {"research_question", "identification", "data", "contribution"}:
            existing = clean_text(normalized.get(active_field))
            if existing and existing != "NOT STATED":
                normalized[active_field] = f"{existing} {line}".strip()
            else:
                normalized[active_field] = line
        elif active_field in {"hypothesis", "limitations"}:
            cast_list = normalized[active_field]
            if isinstance(cast_list, list):
                cast_list.append(line)

    for key in ("hypothesis", "limitations"):
        cast_list = normalized[key]
        if isinstance(cast_list, list):
            clean_list = [clean_text(x) for x in cast_list if clean_text(x)]
            normalized[key] = clean_list if clean_list else ["NOT STATED"]
    return normalized


def normalize_with_llm(results: list[dict], llm_runner_path: Path, prompt_template_path: Path) -> list[dict]:
    """Normalize retrieved abstracts using retrieval_summarizer prompt + llm_runner."""
    if not llm_runner_path.exists():
        warn(f"llm_runner.py not found: {llm_runner_path}")
        return results
    if not prompt_template_path.exists():
        warn(f"retrieval_summarizer prompt not found: {prompt_template_path}")
        return results
    template = prompt_template_path.read_text()

    for result in results:
        if not isinstance(result, dict):
            continue
        if "normalized" in result:
            continue
        abstract = clean_text(result.get("abstract"))
        if not abstract:
            continue
        prompt = render_template(
            template,
            {
                "paper_abstract": abstract,
                "title": clean_text(result.get("title")) or "NOT STATED",
                "authors": clean_text(result.get("authors")) or "NOT STATED",
                "year": clean_text(result.get("year")) or "NOT STATED",
                "venue": clean_text(result.get("venue")) or "NOT STATED",
            },
        )
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
                tmp.write(prompt)
                tmp_path = Path(tmp.name)
            proc = subprocess.run(
                [
                    "python3",
                    str(llm_runner_path),
                    "--model",
                    "opus",
                    "--prompt-file",
                    str(tmp_path),
                    "--max-tokens",
                    "1000",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                warn(f"Normalization failed for '{clean_text(result.get('title'))}': {clean_text(proc.stderr)[:300]}")
                continue
            output_text = proc.stdout.strip()
            if not output_text:
                warn(f"Normalization returned empty output for '{clean_text(result.get('title'))}'")
                continue
            result["normalized"] = parse_normalized_output(output_text)
        except OSError as exc:
            warn(f"Normalization subprocess error for '{clean_text(result.get('title'))}': {exc}")
        finally:
            if tmp_path:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
    return results


def summarize_output(payload: dict) -> str:
    """Create a human-readable summary."""
    lines = [
        f"Query: {clean_text(payload.get('query'))}",
        f"Mode: {clean_text(payload.get('mode'))}",
        f"Results: {payload.get('results_count', 0)}",
    ]
    results = payload.get("results", [])
    if isinstance(results, list):
        for i, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue
            title = clean_text(item.get("title")) or "(untitled)"
            year = clean_text(item.get("year"))
            venue = clean_text(item.get("venue"))
            sim = item.get("similarity")
            parts = [f"{i}. {title}"]
            meta = ", ".join([x for x in [year, venue] if x])
            if meta:
                parts.append(f"({meta})")
            if isinstance(sim, (float, int)):
                parts.append(f"[similarity={sim:.4f}]")
            lines.append(" ".join(parts))
    return "\n".join(lines)


def write_output(content: str, output_path: Path | None) -> None:
    """Write output to file or stdout."""
    if output_path is None:
        print(content)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content + ("" if content.endswith("\n") else "\n"))


def parse_args() -> argparse.Namespace:
    """Configure and parse CLI args."""
    parser = argparse.ArgumentParser(description="Multi-mode literature retrieval tool.")
    parser.add_argument("--query", required=True, help="Idea query text or path to file containing query")
    parser.add_argument("--mode", choices=["local", "api", "manual"], default="local")
    parser.add_argument("--corpus-dir", type=Path, help="Directory of local paper files for local mode")
    parser.add_argument("--retrieved-json", type=Path, help="JSON file for manual mode")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--cache-ttl-days", type=int, default=30)
    parser.add_argument("--normalize", action="store_true", help="Normalize abstracts with retrieval_summarizer + llm")
    parser.add_argument("--llm-runner-path", type=Path, default=DEFAULT_LLM_RUNNER)
    parser.add_argument("--output", type=Path, help="Output file path (default: stdout)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--summary", action="store_true", help="Output human-readable summary")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top_k <= 0:
        fail("--top-k must be > 0")

    query_text = resolve_query_text(args.query)
    if not query_text:
        fail("Query is empty")

    mode = args.mode
    results: list[dict]
    if mode == "local":
        if args.corpus_dir is None:
            fail("--corpus-dir is required for local mode")
        try:
            results = retrieve_local(query_text, args.corpus_dir.expanduser(), args.top_k)
        except ValueError as exc:
            fail(str(exc))
    elif mode == "api":
        results = retrieve_api(
            query_text=query_text,
            top_k=args.top_k,
            cache_dir=args.cache_dir.expanduser(),
            cache_ttl_days=args.cache_ttl_days,
        )
    else:
        if args.retrieved_json is None:
            fail("--retrieved-json is required for manual mode")
        try:
            results = retrieve_manual(args.retrieved_json.expanduser(), args.top_k)
        except (ValueError, json.JSONDecodeError) as exc:
            fail(str(exc))

    if args.normalize:
        results = normalize_with_llm(
            results=results,
            llm_runner_path=args.llm_runner_path.expanduser(),
            prompt_template_path=DEFAULT_PROMPT_TEMPLATE,
        )

    payload = {
        "query": query_text,
        "mode": mode,
        "results_count": len(results),
        "results": results,
    }

    if args.summary:
        output = summarize_output(payload)
    else:
        output = json.dumps(payload, indent=2 if args.pretty else None)
    write_output(output, args.output.expanduser() if args.output else None)


if __name__ == "__main__":
    main()
