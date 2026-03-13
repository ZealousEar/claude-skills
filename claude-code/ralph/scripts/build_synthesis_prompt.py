#!/usr/bin/env python3
"""Build synthesis prompt for the Ralph analytics loop.

Combines the original prompt with SQL query results to create a synthesis
prompt for the second LLM call.

Usage:
    python build_synthesis_prompt.py \
        --prompt-file /path/to/original-prompt.txt \
        --sql-results /path/to/sql-results.json \
        --output /path/to/synthesis-prompt.txt
"""

import argparse
import json
import sys
from pathlib import Path

SYNTHESIS_SUFFIX = """

## SQL Query Results

The following queries were executed against the production database. Use these results to ground your analysis:

{formatted}

## Your Task

Based on the SQL results above, provide your finding as a JSON object (in a json code fence) with these fields:
- finding_title: Concise title
- finding_summary: 2-3 paragraphs with specific numbers from the results
- funnel_stages_affected: list of stage numbers (1-9)
- key_metrics: dict of metric_name to value
- sql_queries_used: abbreviated queries
- recommendation: specific actionable recommendation
- confidence: high/medium/low
- evidence_strength: description of reliability
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build synthesis prompt from original prompt + SQL results."
    )
    parser.add_argument("--prompt-file", required=True,
                        help="Path to original user prompt")
    parser.add_argument("--sql-results", required=True,
                        help="Path to sql-results.json")
    parser.add_argument("--output", required=True,
                        help="Path to write synthesis prompt")
    args = parser.parse_args()

    # Read original prompt
    prompt_path = Path(args.prompt_file)
    if not prompt_path.exists():
        print(f"ERROR: Prompt file not found: {args.prompt_file}", file=sys.stderr)
        return 1
    original_prompt = prompt_path.read_text()

    # Read SQL results
    try:
        sql_data = json.loads(Path(args.sql_results).read_text())
        formatted = sql_data.get("formatted", "No SQL results available.")
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: Cannot read SQL results: {e}", file=sys.stderr)
        formatted = "SQL results unavailable."

    # Build synthesis prompt
    synthesis = original_prompt + SYNTHESIS_SUFFIX.format(formatted=formatted)

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(synthesis)

    # Copy system prompt if it exists
    system_path = Path(str(args.prompt_file) + ".system")
    synth_system_path = Path(str(args.output) + ".system")
    if system_path.exists():
        synth_system_path.write_text(system_path.read_text())

    return 0


if __name__ == "__main__":
    sys.exit(main())
