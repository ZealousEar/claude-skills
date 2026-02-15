# arxiv-pdf-reader

Reference skill for reliably resolving and downloading arXiv papers as PDFs.

## Files

- `skill.yaml` — core instructions, URL rules, and edge-case handling for arXiv retrieval.

## How it works

The skill normalizes arXiv identifiers and maps them to valid PDF endpoints. It accounts for versioned IDs, category formats, and common URL mistakes that break downloads. The output is a deterministic fetch pattern you can reuse in automation or manual workflows.
