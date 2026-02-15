# Getting Started

How to install and use the skills in this repo.

## Prerequisites

**Required:**
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Python 3.10+ (for script-based skills)
- Git (for worktree-based skills like codex-code)

**Optional:**
- Spawner framework (for structured skill scoring/creation -- not needed to just read the skills)
- Codex CLI (`npm install -g @openai/codex`) for the codex-code skill
- Obsidian 1.12+ for the obsidian skill's Tier 2 commands
- Various API keys depending on which skills you use (Mathpix, OpenRouter, Aristotle, etc.)

## Installing a Claude Code Skill

Claude Code skills go in `~/.claude/skills/`. Each skill is a directory with a `SKILL.md` and supporting files.

**Step 1:** Clone this repo (or download the skill directory you want):

```bash
git clone https://github.com/ZealousEar/claude-skills.git
cd claude-skills
```

**Step 2:** Copy the skill to your skills directory:

```bash
# Copy a single skill
cp -r claude-code-skills/aristotle-prover ~/.claude/skills/

# Or copy all Claude Code skills
cp -r claude-code-skills/* ~/.claude/skills/
```

**Step 3:** Verify it's recognized:

```bash
ls ~/.claude/skills/aristotle-prover/SKILL.md
```

**Step 4:** Set up any required environment variables. Each skill's SKILL.md lists its requirements. For example, aristotle-prover needs:

```bash
export ARISTOTLE_API_KEY="your-key-here"
```

**Step 5:** Use it in Claude Code:

```
/prove Show that the sum of two even numbers is even
```

That's it. Claude Code automatically discovers skills in `~/.claude/skills/` and makes them available as slash commands.

## Using a Spawner Skill

Spawner skills are reference material, not executable commands. You don't "install" them in the traditional sense -- you make them available for Claude to read.

**Step 1:** Copy the skill to a known location:

```bash
# Copy to the standard Spawner location
mkdir -p ~/.spawner/skills/creative
cp -r spawner-skills/arxiv-pdf-reader ~/.spawner/skills/creative/

# Or put them anywhere -- they're just files
cp -r spawner-skills/arxiv-pdf-reader ~/my-skills/
```

**Step 2:** Tell Claude to read the skill when you need its knowledge. You can do this explicitly:

```
Read ~/.spawner/skills/creative/arxiv-pdf-reader/skill.yaml
and use it to convert this arXiv paper: https://arxiv.org/abs/2502.07766
```

Or reference it in your project's CLAUDE.md / memory file so Claude loads it automatically for relevant tasks.

**Step 3:** For the full 8-file experience, read specific files as needed:

```
# When you need to know what can go wrong:
Read ~/.spawner/skills/creative/obsidian-cli/sharp-edges.yaml

# When you need architectural context:
Read ~/.spawner/skills/creative/obsidian-cli/decisions.md

# When you need validation checks:
Read ~/.spawner/skills/creative/obsidian-cli/validations.yaml
```

## Example: Pairing obsidian Skills

The `obsidian` Claude Code skill and `obsidian-cli` Spawner skill are designed to work together. Here's how to set that up.

**Step 1:** Install the Claude Code skill:

```bash
cp -r claude-code-skills/obsidian ~/.claude/skills/
```

**Step 2:** Install the Spawner skill:

```bash
mkdir -p ~/.spawner/skills/creative
cp -r spawner-skills/obsidian-cli ~/.spawner/skills/creative/
```

**Step 3:** The Claude Code skill already references the Spawner skill in its SKILL.md:

```markdown
## Domain Knowledge

Deep reference material lives in the spawner skill. Read these files for detailed
patterns, sharp edges, and architectural decisions when needed:

~/.spawner/skills/creative/obsidian-cli/
├── skill.yaml           # Core definition, 13 patterns, 13 domains
├── patterns.md          # 11 pattern deep-dives with full examples
├── sharp-edges.yaml     # 15 pitfalls with detection patterns
...
```

**Step 4:** Use it:

```
/obsidian health
```

Claude reads the Claude Code skill for the health check procedure, then references the Spawner skill's patterns and anti-patterns to make informed decisions during execution (like choosing CLI over grep for orphan detection, or checking `community-plugins.json` before using a plugin feature).

## Skill-Specific Setup

### aristotle-prover
```bash
pip install aristotlelib>=0.7.0
export ARISTOTLE_API_KEY="your-key"
```

### codex-code
```bash
npm install -g @openai/codex
codex login  # OAuth with your OpenAI account
```

### convolutional-debate-agent

For multi-model mode, you need at least one external API key:
```bash
# Copy the template
cp ~/.claude/skills/convolutional-debate-agent/api-keys/provider-keys.env.example \
   ~/.claude/skills/convolutional-debate-agent/api-keys/provider-keys.env

# Fill in your keys (any combination works)
# GOOGLE_API_KEY=...
# MOONSHOT_API_KEY=...
# OPENROUTER_API_KEY=...
# ANTHROPIC_API_KEY=...
```

Or use ChatGPT OAuth (no manual API key needed):
```bash
python3 ~/.claude/skills/convolutional-debate-agent/scripts/openai_auth.py login
```

### geps-v5
No additional setup -- uses debate skill's `llm_runner.py` and Python stdlib only.

### obsidian
- Obsidian must be installed (for Tier 2/3)
- Obsidian 1.12+ required for CLI commands
- Vault path configured in SKILL.md (update to match your vault)

### system-augmentor
No additional setup -- uses WebSearch/WebFetch (built into Claude Code) and optionally the debate skill.

### Academic Spawner skills (arxiv, ssrn, mathpix)
```bash
# Mathpix API (used by arxiv-pdf-reader, mathpix-pdf-converter, ssrn-pdf-reader)
# Get credentials at https://console.mathpix.com
echo "MATHPIX_APP_ID=your_id" >> .env
echo "MATHPIX_APP_KEY=your_key" >> .env

# For SSRN specifically, you also need browser cookies
# Export from browser in Netscape format while logged into SSRN
```

### media-transcript
```bash
npm install -g @steipete/summarize
brew install yt-dlp ffmpeg
```

### lecture-notes-sync
```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
```

## Customizing Skills

Every skill is just files. Fork the repo, modify what you need:

- **Change models:** Edit `settings/model-settings.json` in the debate skill to swap providers
- **Adjust thresholds:** Edit `settings/swarm-config.json` in codex-code to change wave sizes, timeouts
- **Add templates:** Drop new `.md` templates in your vault's template folder and update the obsidian skill
- **Modify patterns:** Edit the Spawner skill YAML files to add your own sharp edges and anti-patterns

The skills are designed to be adapted. The ones in this repo reflect my specific workflow (academic research, Obsidian knowledge management, formal verification). Yours will look different, and that's the point.

## Navigation

- [Home](Home.md) -- Back to overview
- [Claude Code Skills](Claude-Code-Skills.md) -- Deep dive on executable skills
- [Spawner Skills](Spawner-Skills.md) -- Deep dive on knowledge packs
- [Architecture](Architecture.md) -- How the two systems work together
