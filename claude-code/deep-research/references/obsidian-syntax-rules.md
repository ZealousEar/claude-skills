# Obsidian Syntax Validation Rules

Quick-reference checklist for the validation phase. Fix in priority order — P0
issues break rendering completely.

---

## P0: Math Delimiters (MOST COMMON from LLM agents)

### Display math: `\[...\]` → `$$...$$`
```markdown
# BAD — Obsidian does NOT render \[...\]
\[
Y_t = \omega + \sum_{i=1}^{p} \phi_i Y_{t-i} + e_t
\]

# GOOD
$$
Y_t = \omega + \sum_{i=1}^{p} \phi_i Y_{t-i} + e_t
$$
```

### Inline math: backticks → `$...$`
```markdown
# BAD
The parameter `\beta` controls...

# GOOD
The parameter $\beta$ controls...
```

**Rule**: Anything containing `\beta`, `\phi`, `\sigma`, `_`, `^`, `\sum`,
`\frac`, `\color`, Greek letters → MUST use `$...$` not backticks.

### Mathpix postprocessing
Mathpix outputs `\(...\)` and `\[...\]`. Convert:
- `\(...\)` → `$...$`
- `\[...\]` → `$$...$$`

The `mathpix_convert.py --postprocess` handles this automatically.

---

## P1: Mermaid Syntax Errors

### Parentheses in square-bracket labels
```markdown
# BAD — Mermaid parses () as stadium-node syntax
F[Run unit root test (DFT/ADF)]

# GOOD — double-quote labels with parentheses
F["Run unit root test (DFT/ADF)"]
```

### LaTeX in Mermaid labels
```markdown
# BAD
A[Data \(x_i,y_i\)]

# GOOD
A["Data (x_i, y_i)"]
```

### Curly braces in labels
```markdown
# BAD
B[y_{t-1}]

# GOOD
B["y_(t-1)"]
```

### Literal `\n` in labels
```markdown
# BAD
TS[Time Series\nOne entity]

# GOOD
TS["Time Series — One entity"]
```

### Other Mermaid rules
- No `<br/>` tags in labels
- No numbered lists inside `[1. Item]` → `[Item]`
- No empty link labels `---|----|`
- No unsupported types: timeline, mindmap, sankey, zenuml

---

## P2: Broken LaTeX Brace Pairing

```markdown
# BAD — color group not closed
{\color{#0072B2}y_{t-k}\right)

# GOOD
{\color{#0072B2}y_{t-k}}\right)
```

---

## P3: Frontmatter Issues

### Placeholder tags
```yaml
# BAD
tags:
  - topic-tags    # ← placeholder!

# GOOD
tags:
  - specific-topic
  - another-topic
```

### Required fields
Every research note must have: `type`, `created`, at least one `source_*` field,
`tags` (real values), `status`.

---

## P4: Other

- **TikZ**: No `arrows.meta`, `external`, `tikzmark` libraries
- **Wiki-links**: `[[Note Name]]` should reference real files
- **Charts**: Valid YAML in chart blocks

---

## Quick Grep Commands

```bash
DIR="/path/to/notes"

# P0: Wrong display math
grep -rn '^\\\[' "$DIR" --include="*.md"
grep -rn '^\\\]' "$DIR" --include="*.md"

# P0: Backtick-wrapped LaTeX
grep -rn '`[^`]*\\\\[a-zA-Z]' "$DIR" --include="*.md"

# P1: Mermaid issues
grep -rn '\\\\n' "$DIR" --include="*.md"

# P3: Placeholder tags
grep -rn 'topic-tags' "$DIR" --include="*.md"
```
