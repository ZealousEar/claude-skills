#!/usr/bin/env python3
"""SQL executor for the Ralph analytics loop.

Parses SQL queries from fenced code blocks in LLM responses,
executes them via psql subprocess, and writes structured results.

Usage:
    python sql_executor.py \
        --response /path/to/result.json \
        --output /path/to/sql-results.json \
        --db mydb \
        --config /path/to/ralph-config.json
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("~/.claude/skills/ralph/settings/ralph-config.json").expanduser()
PSQL_PATHS = [
    "/opt/homebrew/opt/postgresql@17/bin/psql",
    "/opt/homebrew/opt/libpq/bin/psql",
    "/usr/local/bin/psql",
    "psql",
]


def find_psql() -> str:
    """Find the psql binary."""
    for p in PSQL_PATHS:
        try:
            result = subprocess.run(
                [p, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return p
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    print("ERROR: psql not found", file=sys.stderr)
    sys.exit(1)


def load_sql_config(config_path: str) -> dict:
    """Load sql_execution config section."""
    defaults = {
        "max_queries_per_iteration": 5,
        "query_timeout_seconds": 30,
        "max_rows_per_query": 200,
        "db_name": "",
    }
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)
        sql_cfg = cfg.get("sql_execution", {})
        defaults.update({k: sql_cfg[k] for k in defaults if k in sql_cfg})
    except (OSError, json.JSONDecodeError):
        pass
    return defaults


def extract_sql_queries(text: str) -> list[str]:
    """Extract SQL queries from fenced code blocks.

    Matches ```sql ... ``` blocks. Falls back to any ``` ... ```
    blocks that look like SQL (contain SELECT, INSERT, WITH, etc.).
    """
    queries = []

    # Match ```sql ... ``` blocks
    sql_fence_pattern = r"```sql\s*\n(.*?)```"
    for match in re.finditer(sql_fence_pattern, text, re.DOTALL | re.IGNORECASE):
        query = match.group(1).strip()
        if query:
            queries.append(query)

    if queries:
        return queries

    # Fallback: any fenced block that looks like SQL
    generic_fence = r"```\s*\n(.*?)```"
    sql_keywords = re.compile(
        r"\b(SELECT|INSERT|UPDATE|DELETE|WITH|CREATE|ALTER|DROP)\b",
        re.IGNORECASE,
    )
    for match in re.finditer(generic_fence, text, re.DOTALL):
        block = match.group(1).strip()
        if sql_keywords.search(block):
            queries.append(block)

    return queries


def execute_query(
    psql_path: str,
    db_name: str,
    query: str,
    timeout: int,
    max_rows: int,
) -> dict:
    """Execute a single SQL query via psql and return structured result."""
    # Wrap query with row limit if it doesn't already have one
    q = query.rstrip().rstrip(";")
    has_limit = re.search(r"\bLIMIT\s+\d+", q, re.IGNORECASE)
    if not has_limit:
        q = f"{q} LIMIT {max_rows}"
    q += ";"

    try:
        result = subprocess.run(
            [
                psql_path,
                "-d", db_name,
                "-t",        # tuples only (no header/footer for counting)
                "-A",        # unaligned output
                "-F", "\t",  # tab-separated
                "-c", q,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            return {
                "sql": query,
                "success": False,
                "error": result.stderr.strip()[:500],
                "columns": [],
                "rows": [],
                "row_count": 0,
            }

        # Parse tab-separated output
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        rows = []
        for line in lines:
            rows.append(line.split("\t"))

        # Also run with headers to get column names
        header_result = subprocess.run(
            [
                psql_path,
                "-d", db_name,
                "-A",
                "-F", "\t",
                "-c", q,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        columns = []
        if header_result.returncode == 0 and header_result.stdout.strip():
            header_lines = header_result.stdout.strip().split("\n")
            if header_lines:
                columns = header_lines[0].split("\t")

        return {
            "sql": query,
            "success": True,
            "error": None,
            "columns": columns,
            "rows": rows[:max_rows],
            "row_count": len(rows),
        }

    except subprocess.TimeoutExpired:
        return {
            "sql": query,
            "success": False,
            "error": f"Query timed out after {timeout}s",
            "columns": [],
            "rows": [],
            "row_count": 0,
        }
    except Exception as e:
        return {
            "sql": query,
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "columns": [],
            "rows": [],
            "row_count": 0,
        }


def format_results_for_prompt(results: list[dict]) -> str:
    """Format SQL results into a readable string for the synthesis prompt."""
    parts = []
    for i, r in enumerate(results, 1):
        parts.append(f"### Query {i}")
        parts.append(f"```sql\n{r['sql']}\n```")

        if not r["success"]:
            parts.append(f"**ERROR:** {r['error']}")
            parts.append("")
            continue

        if r["row_count"] == 0:
            parts.append("*No rows returned.*")
            parts.append("")
            continue

        # Format as markdown table
        columns = r["columns"] if r["columns"] else [f"col_{j}" for j in range(len(r["rows"][0]) if r["rows"] else 0)]
        if columns:
            parts.append("| " + " | ".join(columns) + " |")
            parts.append("| " + " | ".join(["---"] * len(columns)) + " |")
            for row in r["rows"][:50]:  # Cap display at 50 rows
                parts.append("| " + " | ".join(row) + " |")
            if r["row_count"] > 50:
                parts.append(f"*... {r['row_count'] - 50} more rows*")
        else:
            for row in r["rows"][:50]:
                parts.append("\t".join(row))

        parts.append(f"\n*{r['row_count']} rows returned.*")
        parts.append("")

    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute SQL queries from LLM response via psql."
    )
    parser.add_argument("--response", required=True,
                        help="Path to LLM result JSON (contains 'response' field)")
    parser.add_argument("--output", required=True,
                        help="Path to write SQL results JSON")
    parser.add_argument("--db", help="Database name (overrides config)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH),
                        help="Path to ralph-config.json")
    args = parser.parse_args()

    # Load config
    sql_config = load_sql_config(args.config)
    db_name = args.db or sql_config["db_name"]
    max_queries = sql_config["max_queries_per_iteration"]
    timeout = sql_config["query_timeout_seconds"]
    max_rows = sql_config["max_rows_per_query"]

    # Load LLM response
    try:
        with open(args.response, "r") as f:
            result = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: Cannot read response file: {e}", file=sys.stderr)
        return 1

    response_text = result.get("response", "")
    if not response_text:
        output = {
            "queries_attempted": 0,
            "queries_succeeded": 0,
            "results": [],
            "formatted": "No response text to parse.",
        }
        Path(args.output).write_text(json.dumps(output, indent=2))
        return 0

    # Extract SQL queries
    queries = extract_sql_queries(response_text)
    if not queries:
        output = {
            "queries_attempted": 0,
            "queries_succeeded": 0,
            "results": [],
            "formatted": "No SQL queries found in LLM response.",
        }
        Path(args.output).write_text(json.dumps(output, indent=2))
        print("No SQL queries found in response")
        return 0

    # Cap at max queries
    queries = queries[:max_queries]
    psql_path = find_psql()

    # Execute queries
    results = []
    succeeded = 0
    for i, query in enumerate(queries, 1):
        print(f"  Executing query {i}/{len(queries)}...", end=" ", flush=True)
        r = execute_query(psql_path, db_name, query, timeout, max_rows)
        results.append(r)
        if r["success"]:
            succeeded += 1
            print(f"OK ({r['row_count']} rows)")
        else:
            print(f"FAILED: {r['error'][:80]}")

    # Format for synthesis prompt
    formatted = format_results_for_prompt(results)

    # Write output
    output = {
        "queries_attempted": len(queries),
        "queries_succeeded": succeeded,
        "results": results,
        "formatted": formatted,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(output, indent=2, ensure_ascii=False))

    print(f"SQL execution: {succeeded}/{len(queries)} queries succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
