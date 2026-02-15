#!/usr/bin/env python3
"""Build a concept co-occurrence graph and detect structural holes."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

SUPPORTED_MARKDOWN_SUFFIXES = {".md", ".markdown"}
PAPER_ARRAY_KEYS = {"skills", "interests", "gaps", "related_papers"}
IDEA_ARRAY_KEYS = {"skills", "interests", "gaps"}
FRONTMATTER_ARRAY_KEYS = PAPER_ARRAY_KEYS | IDEA_ARRAY_KEYS | {"keywords"}

STOPWORDS = set(
    """
a about above after again against all am an and any are as at be because been before being below between both but by
can did do does doing down during each few for from further had has have having he her here hers herself him himself his
how i if in into is it its itself just me more most my myself no nor not of off on once only or other our ours ourselves
out over own same she should so some such than that the their theirs them themselves then there these they this those through
to too under until up very was we were what when where which while who whom why will with you your yours yourself yourselves
""".split()
)

KNOWN_MULTIWORD_TERMS = tuple(
    line.strip()
    for line in """
agent based model
artificial intelligence
causal inference
cointegration model
deep learning
difference in differences
dynamic programming
equity premium
event study
general equilibrium
high frequency
hypothesis testing
large language model
limit order book
machine learning
market microstructure
natural language processing
network effects
order book
panel regression
portfolio optimization
price discovery
reinforcement learning
stochastic volatility
time series
transaction cost
vector autoregression
""".strip().splitlines()
)

BIGRAM_HEADWORDS = {
    "analysis",
    "arbitrage",
    "benchmark",
    "book",
    "clustering",
    "dynamics",
    "economics",
    "equilibrium",
    "estimation",
    "forecasting",
    "inference",
    "learning",
    "liquidity",
    "market",
    "mechanism",
    "method",
    "model",
    "network",
    "optimization",
    "policy",
    "pricing",
    "regression",
    "risk",
    "simulation",
    "strategy",
    "system",
    "trading",
    "volatility",
}
BIGRAM_PREFIXES = {"causal", "limit", "market", "order", "portfolio", "risk", "time"}

TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9#+./_-]+")
HEADER_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$", re.MULTILINE)
BOLD_RE = re.compile(r"\*\*([^*\n]{2,200})\*\*")
CODE_RE = re.compile(r"`([^`\n]{2,120})`")
LETTER_RE = re.compile(r"[a-z]")


def _strip_quotes(value: str) -> str:
    """Remove simple wrapping quotes from a value."""
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1].strip()
    return text


def _parse_inline_list(raw: str) -> list[str]:
    """Parse a simple inline list expression like [a, b, c]."""
    inner = raw.strip()[1:-1].strip()
    if not inner:
        return []
    items: list[str] = []
    for part in inner.split(","):
        cleaned = _strip_quotes(part.strip())
        if cleaned:
            items.append(cleaned)
    return items


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split markdown text into frontmatter and body using --- markers."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", text
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return "\n".join(lines[1:idx]), "\n".join(lines[idx + 1 :])
    return "", text


def parse_simple_frontmatter(frontmatter: str) -> dict[str, object]:
    """Parse constrained YAML-like frontmatter without external dependencies."""
    parsed: dict[str, object] = {}
    current_list_key: str | None = None

    for raw_line in frontmatter.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("- "):
            if current_list_key:
                item = _strip_quotes(line[2:].strip())
                if item:
                    parsed.setdefault(current_list_key, [])
                    if isinstance(parsed[current_list_key], list):
                        parsed[current_list_key].append(item)
            continue

        if ":" not in line:
            current_list_key = None
            continue

        key_part, value_part = line.split(":", 1)
        key = key_part.strip().lower()
        value = value_part.strip()
        if not key:
            current_list_key = None
            continue

        if not value:
            parsed[key] = []
            current_list_key = key
            continue

        current_list_key = None
        if value.startswith("[") and value.endswith("]"):
            parsed[key] = _parse_inline_list(value)
        elif key in FRONTMATTER_ARRAY_KEYS and "," in value:
            parsed[key] = [_strip_quotes(item.strip()) for item in value.split(",") if item.strip()]
        else:
            parsed[key] = _strip_quotes(value)

    return parsed


def _clean_token(token: str) -> str:
    """Normalize token text and filter low-value words."""
    cleaned = token.strip(" .,:;!?()[]{}<>\"'`").strip("-_/")
    if cleaned.endswith("'s"):
        cleaned = cleaned[:-2]
    if len(cleaned) < 2 or cleaned in STOPWORDS or cleaned.isdigit():
        return ""
    if not LETTER_RE.search(cleaned):
        return ""
    return cleaned


def extract_concepts(text: str) -> list[str]:
    """Extract deduplicated concept strings from free-form text."""
    if not isinstance(text, str):
        raise ValueError("extract_concepts expects a string")

    normalized = text.lower()
    concepts: set[str] = set()

    for phrase in KNOWN_MULTIWORD_TERMS:
        if re.search(r"\b" + re.escape(phrase) + r"\b", normalized):
            concepts.add(phrase)

    tokens: list[str] = []
    for token in TOKEN_SPLIT_RE.split(normalized):
        if not token:
            continue
        cleaned = _clean_token(token)
        if cleaned:
            tokens.append(cleaned)
            concepts.add(cleaned)

    for idx in range(len(tokens) - 1):
        first = tokens[idx]
        second = tokens[idx + 1]
        if len(first) < 3 or len(second) < 3:
            continue
        if second in BIGRAM_HEADWORDS or first in BIGRAM_PREFIXES:
            concepts.add(f"{first} {second}")

    for idx in range(len(tokens) - 2):
        trigram = f"{tokens[idx]} {tokens[idx + 1]} {tokens[idx + 2]}"
        if trigram in KNOWN_MULTIWORD_TERMS:
            concepts.add(trigram)

    return sorted(concepts)


def extract_markdown_concepts(body: str) -> list[str]:
    """Extract concepts from markdown body content and key markdown signals."""
    concepts = set(extract_concepts(body))
    for heading in HEADER_RE.findall(body):
        concepts.update(extract_concepts(heading))
    for bold_term in BOLD_RE.findall(body):
        concepts.update(extract_concepts(bold_term))
    for inline_code in CODE_RE.findall(body):
        concepts.update(extract_concepts(inline_code))
    return sorted(concepts)


def _read_text(path: Path) -> str:
    """Read UTF-8 text and wrap I/O failures as ValueError."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"failed to read file {path}: {exc}") from exc


def _load_json(path: Path) -> object:
    """Read JSON file contents and decode it."""
    text = _read_text(path)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def _concepts_from_value(value: object) -> set[str]:
    """Extract concepts from string-like or list-like values."""
    concepts: set[str] = set()
    if value is None:
        return concepts
    if isinstance(value, str):
        concepts.update(extract_concepts(value))
        return concepts
    if isinstance(value, list):
        for item in value:
            if isinstance(item, (str, int, float)):
                concepts.update(extract_concepts(str(item)))
        return concepts
    return concepts


def parse_json_papers(payload: object, source: str) -> list[set[str]]:
    """Parse a JSON payload into document concept sets."""
    if isinstance(payload, list):
        papers = payload
    elif isinstance(payload, dict):
        if "papers" in payload:
            papers = payload["papers"]
            if not isinstance(papers, list):
                raise ValueError(f"{source}: 'papers' must be a list")
        else:
            papers = [payload]
    else:
        raise ValueError(f"{source}: expected JSON object or array")

    documents: list[set[str]] = []
    for idx, paper in enumerate(papers, start=1):
        if not isinstance(paper, dict):
            raise ValueError(f"{source}: paper {idx} must be an object")
        concepts: set[str] = set()
        for key in (
            "title",
            "abstract",
            "keywords",
            "skills",
            "interests",
            "gaps",
            "related_papers",
        ):
            concepts.update(_concepts_from_value(paper.get(key)))
        documents.append(concepts)
    return documents


def parse_markdown_document(path: Path, array_keys: set[str]) -> set[str]:
    """Parse markdown file and return extracted concept set."""
    text = _read_text(path)
    frontmatter_text, body = split_frontmatter(text)
    frontmatter = parse_simple_frontmatter(frontmatter_text) if frontmatter_text else {}

    concepts: set[str] = set()
    for key in array_keys:
        concepts.update(_concepts_from_value(frontmatter.get(key)))
    for key in ("title", "abstract", "keywords", "summary", "topic"):
        concepts.update(_concepts_from_value(frontmatter.get(key)))

    concepts.update(extract_markdown_concepts(body))
    return concepts


def load_corpus_documents(corpus_dir: Path | None, papers_json: Path | None) -> list[set[str]]:
    """Load source documents from corpus directory and optional papers JSON."""
    documents: list[set[str]] = []

    if papers_json is not None:
        documents.extend(parse_json_papers(_load_json(papers_json), str(papers_json)))

    if corpus_dir is None:
        return documents

    for path in sorted(corpus_dir.iterdir()):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".json":
            documents.extend(parse_json_papers(_load_json(path), str(path)))
        elif suffix in SUPPORTED_MARKDOWN_SUFFIXES:
            documents.append(parse_markdown_document(path, PAPER_ARRAY_KEYS))

    return documents


def load_idea_documents(ideas_dir: Path | None) -> list[set[str]]:
    """Load IDEA-*.md files as overlay documents."""
    if ideas_dir is None:
        return []
    documents: list[set[str]] = []
    for path in sorted(ideas_dir.glob("IDEA-*.md")):
        if path.is_file():
            documents.append(parse_markdown_document(path, IDEA_ARRAY_KEYS))
    return documents


def _edge_key(concept_a: str, concept_b: str) -> tuple[str, str]:
    """Return canonical undirected edge key."""
    return (concept_a, concept_b) if concept_a <= concept_b else (concept_b, concept_a)


def build_counts(documents: list[set[str]]) -> tuple[Counter[str], Counter[tuple[str, str]]]:
    """Build concept frequencies and co-occurrence counts by document."""
    frequencies: Counter[str] = Counter()
    cooccurrence: Counter[tuple[str, str]] = Counter()

    for concepts in documents:
        sorted_concepts = sorted(set(concepts))
        for concept in sorted_concepts:
            frequencies[concept] += 1
        for left_idx in range(len(sorted_concepts)):
            for right_idx in range(left_idx + 1, len(sorted_concepts)):
                cooccurrence[_edge_key(sorted_concepts[left_idx], sorted_concepts[right_idx])] += 1

    return frequencies, cooccurrence


def compute_pmi(freq_a: int, freq_b: int, cooccur_ab: int, total_docs: int, max_pmi: float) -> float:
    """Compute clamped pointwise mutual information for a pair."""
    if total_docs <= 0 or freq_a <= 0 or freq_b <= 0 or cooccur_ab <= 0:
        return 0.0
    p_a = freq_a / total_docs
    p_b = freq_b / total_docs
    p_ab = cooccur_ab / total_docs
    raw = math.log2(p_ab / (p_a * p_b))
    if raw < 0.0:
        return 0.0
    if raw > max_pmi:
        return max_pmi
    return raw


def compute_structural_holes(
    frequencies: dict[str, int],
    neighbors: dict[str, set[str]],
    cooccurrence: Counter[tuple[str, str]],
    alpha: float,
    top_n: int,
) -> list[dict[str, object]]:
    """Compute top structural-hole pairs via neighbor-set compatibility."""
    concepts = sorted(frequencies)
    results: list[dict[str, object]] = []

    for left_idx in range(len(concepts)):
        concept_a = concepts[left_idx]
        neigh_a = neighbors.get(concept_a, set())
        for right_idx in range(left_idx + 1, len(concepts)):
            concept_b = concepts[right_idx]
            neigh_b = neighbors.get(concept_b, set())
            union = neigh_a | neigh_b
            if not union:
                continue
            compat = len(neigh_a & neigh_b) / len(union)
            if compat <= 0.0:
                continue

            cooccur_ab = cooccurrence.get(_edge_key(concept_a, concept_b), 0)
            hole_score = (
                frequencies[concept_a]
                * frequencies[concept_b]
                * math.pow(compat, alpha)
                / (1 + cooccur_ab)
            )
            if hole_score <= 0.0:
                continue

            results.append(
                {
                    "concept_a": concept_a,
                    "concept_b": concept_b,
                    "hole_score": round(hole_score, 6),
                    "compat": round(compat, 6),
                    "freq_a": frequencies[concept_a],
                    "freq_b": frequencies[concept_b],
                    "cooccur": cooccur_ab,
                }
            )

    results.sort(
        key=lambda item: (
            -float(item["hole_score"]),
            -float(item["compat"]),
            -int(item["freq_a"]),
            -int(item["freq_b"]),
            str(item["concept_a"]),
            str(item["concept_b"]),
        )
    )
    return results[:top_n]


def build_graph_payload(documents: list[set[str]], min_freq: int, holes: int, alpha: float) -> dict[str, object]:
    """Build final graph payload with metadata, nodes, edges, and holes."""
    total_docs = len(documents)
    raw_frequencies, raw_cooccurrence = build_counts(documents)
    frequencies = {concept: freq for concept, freq in raw_frequencies.items() if freq >= min_freq}

    neighbors: dict[str, set[str]] = {concept: set() for concept in frequencies}
    cooccurrence: Counter[tuple[str, str]] = Counter()
    for pair, count in raw_cooccurrence.items():
        source, target = pair
        if source in frequencies and target in frequencies:
            cooccurrence[pair] = count
            neighbors[source].add(target)
            neighbors[target].add(source)

    max_pmi = math.log2(total_docs) if total_docs > 1 else 0.0
    nodes = [
        {"concept": concept, "freq": freq}
        for concept, freq in sorted(frequencies.items(), key=lambda item: (-item[1], item[0]))
    ]

    edges: list[dict[str, object]] = []
    for (source, target), cooccur in cooccurrence.items():
        pmi = compute_pmi(frequencies[source], frequencies[target], cooccur, total_docs, max_pmi)
        edges.append(
            {
                "source": source,
                "target": target,
                "cooccur": cooccur,
                "pmi": round(pmi, 6),
            }
        )
    edges.sort(key=lambda item: (-float(item["pmi"]), -int(item["cooccur"]), str(item["source"]), str(item["target"])))

    payload: dict[str, object] = {
        "metadata": {
            "total_docs": total_docs,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "alpha": alpha,
        },
        "nodes": nodes,
        "edges": edges,
        "structural_holes": compute_structural_holes(frequencies, neighbors, cooccurrence, alpha, holes),
    }
    return payload


def summarize_graph(payload: dict[str, object]) -> str:
    """Render summary text with metadata and top 10 holes."""
    metadata = payload.get("metadata", {})
    total_docs = int(metadata.get("total_docs", 0))
    total_nodes = int(metadata.get("total_nodes", 0))
    total_edges = int(metadata.get("total_edges", 0))
    alpha = float(metadata.get("alpha", 1.0))

    lines = [
        f"Total documents: {total_docs}",
        f"Total nodes: {total_nodes}",
        f"Total edges: {total_edges}",
        f"Alpha: {alpha}",
        "Top structural holes:",
    ]

    holes = payload.get("structural_holes", [])
    if isinstance(holes, list) and holes:
        for idx, hole in enumerate(holes[:10], start=1):
            if not isinstance(hole, dict):
                continue
            lines.append(
                f"{idx}. {hole.get('concept_a')} <-> {hole.get('concept_b')} "
                f"(score={hole.get('hole_score')}, compat={hole.get('compat')}, cooccur={hole.get('cooccur')})"
            )
    else:
        lines.append("none")

    return "\n".join(lines)


def summarize_validation(validation: dict[str, object]) -> str:
    """Render summary text for validate mode."""
    return "\n".join(
        [
            "Validation successful.",
            f"Corpus documents: {validation.get('corpus_docs', 0)}",
            f"Idea documents: {validation.get('idea_docs', 0)}",
            f"Total documents: {validation.get('total_docs', 0)}",
            f"Average concepts per document: {validation.get('avg_concepts_per_doc', 0)}",
        ]
    )


def validate_args(args: argparse.Namespace) -> None:
    """Validate CLI arguments and path types."""
    if args.corpus_dir is None and args.papers_json is None and args.ideas_dir is None:
        raise ValueError("provide at least one source: --corpus-dir, --papers-json, or --ideas-dir")
    if args.holes <= 0:
        raise ValueError(f"--holes must be a positive integer, got {args.holes!r}")
    if args.min_freq <= 0:
        raise ValueError(f"--min-freq must be a positive integer, got {args.min_freq!r}")
    if args.alpha < 0:
        raise ValueError(f"--alpha must be >= 0, got {args.alpha!r}")

    if args.corpus_dir is not None:
        if not args.corpus_dir.exists():
            raise ValueError(f"--corpus-dir path does not exist: {args.corpus_dir}")
        if not args.corpus_dir.is_dir():
            raise ValueError(f"--corpus-dir must be a directory: {args.corpus_dir}")

    if args.papers_json is not None:
        if not args.papers_json.exists():
            raise ValueError(f"--papers-json path does not exist: {args.papers_json}")
        if not args.papers_json.is_file():
            raise ValueError(f"--papers-json must be a file: {args.papers_json}")

    if args.ideas_dir is not None:
        if not args.ideas_dir.exists():
            raise ValueError(f"--ideas-dir path does not exist: {args.ideas_dir}")
        if not args.ideas_dir.is_dir():
            raise ValueError(f"--ideas-dir must be a directory: {args.ideas_dir}")

    if args.output is not None and args.output.exists() and args.output.is_dir():
        raise ValueError(f"--output must be a file path, got directory: {args.output}")


def emit_output(output_text: str, output_path: Path | None) -> None:
    """Write output text to stdout or to a file."""
    if output_path is None:
        print(output_text)
        return

    parent = output_path.parent
    if parent and not parent.exists():
        raise ValueError(f"output directory does not exist: {parent}")

    text = output_text
    if not text.endswith("\n"):
        text += os.linesep
    try:
        output_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"failed to write output file {output_path}: {exc}") from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build concept co-occurrence graph and structural holes from a corpus."
    )
    parser.add_argument("--corpus-dir", type=Path, help="Directory of paper files (.json/.md/.markdown).")
    parser.add_argument("--papers-json", type=Path, help="Single JSON file containing paper objects.")
    parser.add_argument("--ideas-dir", type=Path, help="Directory of IDEA-*.md files used as overlay input.")
    parser.add_argument("--output", type=Path, help="Output file path. Defaults to stdout.")
    parser.add_argument("--holes", type=int, default=20, help="Top-N structural hole candidates.")
    parser.add_argument("--alpha", type=float, default=1.0, help="Exponent for compatibility in hole score.")
    parser.add_argument("--min-freq", type=int, default=2, help="Minimum document frequency for nodes.")
    parser.add_argument("--pretty", action="store_true", help="Print indented JSON.")
    parser.add_argument("--validate", action="store_true", help="Dry-run input parsing and validation only.")
    parser.add_argument("--summary", action="store_true", help="Print human-readable summary instead of JSON.")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> str:
    """Execute validation or graph construction and return output text."""
    validate_args(args)
    corpus_docs = load_corpus_documents(args.corpus_dir, args.papers_json)
    idea_docs = load_idea_documents(args.ideas_dir)
    documents = corpus_docs + idea_docs

    if args.validate:
        concept_counts = [len(doc) for doc in documents]
        avg_concepts = round(mean(concept_counts), 4) if concept_counts else 0.0
        validation: dict[str, object] = {
            "valid": True,
            "corpus_docs": len(corpus_docs),
            "idea_docs": len(idea_docs),
            "total_docs": len(documents),
            "avg_concepts_per_doc": avg_concepts,
        }
        if args.summary:
            return summarize_validation(validation)
        return json.dumps(validation, indent=2 if args.pretty else None)

    payload = build_graph_payload(documents, min_freq=args.min_freq, holes=args.holes, alpha=args.alpha)
    if args.summary:
        return summarize_graph(payload)
    return json.dumps(payload, indent=2 if args.pretty else None)


def main() -> None:
    """CLI entrypoint."""
    try:
        args = parse_args()
        emit_output(run(args), args.output)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
