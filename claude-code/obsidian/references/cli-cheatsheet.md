# Obsidian CLI v1.12 Cheatsheet

Binary: `/Applications/Obsidian.app/Contents/MacOS/Obsidian`
Vault: `vault=Agentic` (MUST be first parameter)

## Pre-flight

```bash
# Check Obsidian is running
pgrep -x Obsidian > /dev/null && echo "ready" || echo "start Obsidian first"

# Verify CLI
/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic version
```

## Discovery

```bash
obs='/Applications/Obsidian.app/Contents/MacOS/Obsidian vault=Agentic'

# Search
$obs search query="machine learning" limit=10
$obs search query="status: active" format=json

# Graph health
$obs orphans                  # Notes with no incoming links
$obs orphans total            # Just the count
$obs deadends                 # Notes with no outgoing links
$obs deadends total
$obs unresolved               # Broken [[links]]
$obs unresolved total
$obs unresolved counts        # Per-file breakdown
$obs unresolved verbose       # Full details
```

## Graph Intelligence

```bash
# Backlinks (what links TO this note)
$obs backlinks path="03 Resources/Machine Learning Basics.md"

# Outgoing links (what this note links TO)
$obs links path="03 Resources/Machine Learning Basics.md"

# File metadata (size, dates, word count)
$obs file path="03 Resources/Machine Learning Basics.md"
```

## Metadata Aggregation

```bash
# Tags
$obs tags all                      # List all tags
$obs tags all counts sort=count    # Sorted by frequency

# Properties (frontmatter fields)
$obs properties all                # List all properties
$obs properties all total sort=count counts

# Tasks
$obs tasks all                     # All tasks
$obs tasks all todo                # Incomplete only
$obs tasks all done                # Completed only
$obs tasks all total               # Just the count
```

## Vault Management

```bash
# Plugins
$obs plugins enabled filter=community versions
$obs plugin:install id=dataview enable

# Note creation
$obs create name="New Research" path="03 Resources" template="Research Note v1"

# Daily note
$obs daily:append content="- New task added by Claude"

# Templates
$obs template:read name="Research Note v1" resolve title="Quantum Computing"
```

## Gotchas

1. `vault=Agentic` MUST be first param — wrong order = wrong vault
2. `tasks`/`tags`/`properties` need `all` flag for vault-wide queries
3. CLI requires Obsidian running — falls back to file ops if not
4. Paths with spaces need quotes: `path="03 Resources/Note.md"`
