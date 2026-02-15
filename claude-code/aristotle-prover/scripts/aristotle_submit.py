"""
Aristotle API submission script.

Usage:
  python3 aristotle_submit.py --mode informal --prompt "Prove that ..."
  python3 aristotle_submit.py --mode informal --input-file prompt.txt
  python3 aristotle_submit.py --mode formal --input-file theorem.lean
  python3 aristotle_submit.py --mode formal --input-file theorem.lean --context-file defs.lean

Output: JSON with status, solution_path, and solution_content.
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

def check_setup():
    """Verify aristotlelib and API key are available."""
    api_key = os.environ.get("ARISTOTLE_API_KEY", "")
    if not api_key:
        print(json.dumps({
            "status": "error",
            "error": "ARISTOTLE_API_KEY environment variable is not set.",
            "fix": "export ARISTOTLE_API_KEY='arstl_YOUR_KEY'"
        }))
        sys.exit(1)

    try:
        import aristotlelib
    except ImportError:
        print(json.dumps({
            "status": "error",
            "error": "aristotlelib not installed.",
            "fix": "pip install aristotlelib"
        }))
        sys.exit(1)

    return api_key


async def submit_proof(
    mode: str,
    prompt: str | None = None,
    input_file: str | None = None,
    output_file: str | None = None,
    context_files: list[str] | None = None,
    polling_interval: int = 15,
    max_failures: int = 30,
):
    """Submit a proof request to Aristotle and wait for the result."""
    import aristotlelib
    from aristotlelib import Project, ProjectInputType

    api_key = os.environ["ARISTOTLE_API_KEY"]
    aristotlelib.set_api_key(api_key)

    # Determine input type
    if mode == "formal":
        input_type = ProjectInputType.FORMAL_LEAN
    else:
        input_type = ProjectInputType.INFORMAL

    # Determine output path
    if not output_file:
        output_file = tempfile.mktemp(suffix=".lean", prefix="aristotle_solution_")

    # Build kwargs
    kwargs = {
        "output_file_path": output_file,
        "project_input_type": input_type,
        "validate_lean_project": False,
        "wait_for_completion": True,
        "polling_interval_seconds": polling_interval,
        "max_polling_failures": max_failures,
    }

    # Input source: file or inline content
    if input_file:
        kwargs["input_file_path"] = input_file
    elif prompt:
        kwargs["input_content"] = prompt
    else:
        return {"status": "error", "error": "No prompt or input file provided."}

    # Add context files if provided
    if context_files:
        kwargs["formal_input_context_file_paths"] = context_files

    # Submit and wait
    try:
        solution_path = await Project.prove_from_file(**kwargs)
    except Exception as e:
        return {
            "status": "error",
            "error": f"{type(e).__name__}: {str(e)}",
        }

    # Read solution
    sol = Path(solution_path)
    if sol.exists():
        content = sol.read_text()
        return {
            "status": "success",
            "solution_path": str(solution_path),
            "solution_content": content,
        }
    else:
        return {
            "status": "error",
            "error": f"Solution file not found at {solution_path}",
        }


def main():
    parser = argparse.ArgumentParser(description="Submit proof to Aristotle API")
    parser.add_argument("--mode", choices=["informal", "formal"], default="informal",
                        help="Input mode: informal (natural language) or formal (Lean 4)")
    parser.add_argument("--prompt", type=str, default=None,
                        help="Inline prompt text (informal mode)")
    parser.add_argument("--input-file", type=str, default=None,
                        help="Path to input file (.txt for informal, .lean for formal)")
    parser.add_argument("--output-file", type=str, default=None,
                        help="Path to save the solution .lean file")
    parser.add_argument("--context-file", type=str, action="append", default=None,
                        help="Lean context file(s) for additional definitions (repeatable)")
    parser.add_argument("--polling-interval", type=int, default=15,
                        help="Seconds between status polls (default: 15)")
    parser.add_argument("--max-failures", type=int, default=30,
                        help="Max polling failures before giving up (default: 30)")

    args = parser.parse_args()

    check_setup()

    result = asyncio.run(submit_proof(
        mode=args.mode,
        prompt=args.prompt,
        input_file=args.input_file,
        output_file=args.output_file,
        context_files=args.context_file,
        polling_interval=args.polling_interval,
        max_failures=args.max_failures,
    ))

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
