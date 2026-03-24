# Claude Skills Repository

This repo contains Claude Code skills and Spawner knowledge packs. When a user opens this repo in Claude Code, help them get set up.

## First-Run Setup

When the user first interacts with you in this repo, run through the following setup flow. Be conversational — don't dump everything at once.

### Step 1: Install skills

Check if skills are already installed:
```bash
ls ~/.claude/skills/ 2>/dev/null
```

If not installed (or partially installed), offer to run the installer:
```bash
bash install.sh
```

This symlinks all skills from `claude-code/` into `~/.claude/skills/`. Explain that symlinks mean they get updates automatically when they `git pull`.

If skills already exist as directories (not symlinks), mention the `--force` flag to replace them, but confirm first.

### Step 2: Configure API keys

Walk through each skill's requirements **one at a time**. Ask the user which skills they plan to use, then only configure those. Don't overwhelm them with every key at once.

Here's what each skill needs:

#### Skills with zero setup (work immediately)
- **system-augmentor** — uses Claude Code's built-in WebSearch/WebFetch
- **geps-v5** — uses debate skill's llm_runner, Python stdlib only
- **obsidian** — works if Obsidian is installed (1.12+ for CLI commands)

#### Skills that need API keys or tools

**convolutional-debate-agent** (`/debate`):
- Needs at least one external LLM provider key for multi-model debates
- Template exists at `~/.claude/skills/convolutional-debate-agent/api-keys/provider-keys.env.example`
- Help the user copy it and fill in whichever keys they have:
  ```bash
  cp ~/.claude/skills/convolutional-debate-agent/api-keys/provider-keys.env.example \
     ~/.claude/skills/convolutional-debate-agent/api-keys/provider-keys.env
  ```
- Supported keys: `OPENROUTER_API_KEY`, `GOOGLE_API_KEY`, `MOONSHOT_API_KEY`
- Alternative: ChatGPT OAuth login (no API key needed):
  ```bash
  python3 ~/.claude/skills/convolutional-debate-agent/scripts/openai_auth.py login
  ```

**llm** (model router, also required by `/ralph`):
- CLI-first: works with any installed CLI (Claude Code, Codex, Kimi)
- For additional providers, set env vars: `GOOGLE_API_KEY`, `OPENROUTER_API_KEY`
- Verify with: `python3 ~/.claude/skills/llm/scripts/llm_route.py --list-models`

**ralph** (`/ralph`):
- Depends on the `llm` skill (installed automatically by `install.sh`)
- No additional keys needed beyond what's configured for `llm`
- Uses whichever models are available through the llm router

**deep-research** (`/research`):
- **VAULT_ROOT**: Ask the user for their Obsidian vault path, then:
  ```bash
  export VAULT_ROOT="/path/to/their/vault"
  ```
  Or explain it auto-detects if they run Claude Code from within their vault directory.
- **Mathpix** (for PDF→Markdown conversion): `MATHPIX_APP_ID` and `MATHPIX_APP_KEY`
  - Get credentials at https://console.mathpix.com
  - Store in `$VAULT_ROOT/.credentials/dissertation-research/.env`
- **YouTube extraction**: `npm install -g @steipete/summarize && brew install yt-dlp ffmpeg jq`
- **SSRN** (optional): Browser cookies in Netscape format

**aristotle-prover** (`/prove`):
- `pip install aristotlelib>=0.7.0`
- `ARISTOTLE_API_KEY` — get from Harmonic

**codex-code** (`/CodexCode`):
- `npm install -g @openai/codex`
- `codex login` (OAuth with OpenAI account)

### Step 3: Verify

After setup, offer to test a skill. Suggest starting with something simple:
- `/debate "Is P=NP?"` — tests multi-model routing
- `python3 ~/.claude/skills/llm/scripts/llm_route.py --list-models` — tests model discovery

## Skill Dependency Map

```
ralph ──requires──▶ llm
geps-v5 ──uses──▶ convolutional-debate-agent (llm_runner.py)
deep-research ──optional──▶ VAULT_ROOT env var
```

All other skills are standalone.

## Directory Structure

```
claude-code/           # Executable Claude Code skills (→ ~/.claude/skills/)
├── aristotle-prover/  # /prove — Lean 4 formal theorem prover
├── codex-code/        # /CodexCode — parallel Codex agent swarm
├── convolutional-debate-agent/  # /debate — multi-model adversarial debates
├── deep-research/     # /research — multi-source research pipeline
├── geps-v5/           # /geps — evolutionary portfolio search
├── llm/               # Universal model router (dependency for ralph)
├── obsidian/          # /obsidian — vault automation
├── ralph/             # /ralph — autonomous idea generation loop
└── system-augmentor/  # /improve — capability gap auditor

spawner/               # Knowledge packs (non-executable reference material)

docs/                  # Getting-Started.md, Architecture.md, etc.
install.sh             # Symlink installer
```

## Important Notes

- Never hardcode user-specific paths. Use environment variables or auto-detection.
- API keys go in `.env` files (gitignored) or environment variables, never in code.
- The `state/` directories are gitignored — they contain user-specific session data.
- Skills use `~/.claude/skills/` paths with `$HOME` expansion, not absolute paths.
