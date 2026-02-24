# Research Note Template — Deep Research Skill

This is a structural guide for the synthesis phase. Section count and depth are
driven by the content — not every section appears in every note. The template
provides the **shape**, not rigid constraints.

---

## Frontmatter

```yaml
---
type: research-note
version: v1
created: "YYYY-MM-DD"
# Source fields — include only those that apply:
source_video: <youtube_url>           # if YouTube source
source_video_title: "<title>"
source_video_author: <author>
source_paper: <arxiv_or_ssrn_url>     # if academic paper source
source_paper_id: <arxiv_id or ssrn_id>
source_article: <blog_url>            # if web article source
sources:                              # if multiple sources
  - url: <url1>
    type: youtube
  - url: <url2>
    type: arxiv
tags:
  - <topic-tag-1>
  - <topic-tag-2>
  - <content-type>                    # e.g. implementation-reference, literature-review
status: active                        # active | archived | draft
---
```

## Title

```markdown
# Research Note: <Topic Title>
```

## Question

One clear question this note answers. Drives the entire note structure.

```markdown
## Question

How does X work, why does it matter, and how should we apply it in our projects?
```

## Key Idea

2-4 paragraph executive summary of the core insight. Include the canonical
code/formula/diagram if there is one.

```markdown
## Key Idea

<Core insight in 2-4 paragraphs>

### <Canonical Implementation / Formula>

![[slide_NNNN_Ts.png]]

<code block or math block>
```

## Numbered Content Sections

Use `## N. Section Title` for major sections. H3/H4 for subsections.
Number and depth are content-driven — use as many or as few as the material
requires. Typical range: 4-10 sections.

```markdown
## 1. Origin and History

<Context, creator, evolution, key dates>

---

## 2. Core Mechanism

### Why the Default Approach Fails

<Explain the problem the technique solves>

### Why This Approach Succeeds

<Explain the mechanism step by step>

> "Direct quote from source" -- Attribution

---

## 3. Implementation Guide

### Phase 1: <Setup>

![[slide_NNNN_Ts.png]]

<Steps, code blocks, configuration>

### Phase 2: <Execution>

<Steps, code blocks, examples>

---

## 4. Common Mistakes and Pitfalls

| Mistake | Why It Fails | Fix |
|---------|-------------|-----|
| ... | ... | ... |

---

## 5. Comparison with Alternatives

| Feature | Approach A | Approach B | This Approach |
|---------|-----------|-----------|---------------|
| ... | ... | ... | ... |
```

## Evidence Section

Cite primary sources (the input content) and secondary sources (web research).

```markdown
## Evidence

### Primary Sources
- [Source Title](url) — <one-line summary of relevance>

### Secondary Sources
- [Blog Post](url) — <summary>
- [GitHub Repo](url) — <summary>
- [HN Discussion](url) — <summary>
```

## Implications

How this connects to our specific projects and work.

```markdown
## Implications for Our Projects

- **Project X**: <how this applies>
- **Workflow Y**: <what to change>
- **Open question**: <what remains unclear>
```

## Internal Links

Link to raw extraction artifacts and related vault notes.

```markdown
## Links

- Raw transcript: [[raw-transcript.md]]
- Mathpix conversion: [[slug.mathpix.md]]
- Related notes: [[Other Note]], [[Another Note]]
```

---

## Formatting Rules

1. **Math**: `$$...$$` for display, `$...$` for inline. NEVER `\[...\]` or backticks for math.
2. **Slides**: `![[slide_NNNN_Ts.png]]` — Obsidian wiki-link embed syntax.
3. **Code**: Fenced with language identifier. No bare backtick-wrapped code.
4. **Quotes**: `> "quote" -- attribution` format.
5. **Tables**: GitHub-flavored markdown. Comparison tables encouraged.
6. **Separators**: `---` between major sections.
7. **Links**: `[text](url)` for external, `[[note]]` for internal.
8. **Frontmatter**: YAML, no placeholders. All fields must have real values or be omitted.
