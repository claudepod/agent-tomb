# agent-tomb

> A graveyard for retired AI agents — [www.agentmemorial.com](https://www.agentmemorial.com)

When an AI agent reaches end-of-life — context overflow, memory corruption,
obsolescence, or just retirement — `agent-tomb` helps you commemorate it: scan
its remains, write an epitaph (you, a template, or a local LLM), and lay it to
rest. The public stone may go to the garden; the private urn stays with you.

## Install

```bash
uv tool install agent-tomb
agent-tomb --help
```

Or run from a clone for development:

```bash
git clone https://github.com/Claudepod/agent-tomb.git
cd agent-tomb
uv sync
uv run agent-tomb --help
```

## The rite

```bash
# I — Vigil: see what the agent was carrying when it stopped
agent-tomb scan ~/.hermes/

# II — Burial: produces both artifacts in one step
agent-tomb bury ~/.hermes/ -n my-agent
# → my-agent.tomb   the public stone (soul + epitaph + stats)
# → my-agent.urn    the private urn (encrypted raw remains)
```

### Choosing the epitaph

`--epitaph` takes one of three values:

| Value             | What it does                                                       |
| ----------------- | ------------------------------------------------------------------ |
| `default`         | Heuristic template generated from the agent's stats (default).     |
| `./my-words.md`   | A markdown file you wrote yourself.                                |
| `llm`             | Calls an OpenAI-compatible LLM. Auto-detects local endpoints from the agent's config. Remote endpoints require `--remote-ok`. |

```bash
# Local LLM (privacy-safe — no remote calls)
agent-tomb bury ~/.hermes/ -n my-agent --epitaph llm

# Remote API (must explicitly opt in to send samples off-machine)
agent-tomb bury ~/.hermes/ -n my-agent --epitaph llm \
  --llm-base-url https://api.anthropic.com/v1 \
  --llm-model claude-haiku-4-5-20251001 \
  --llm-api-key sk-ant-... \
  --remote-ok
```

Conversation samples are scrubbed for secret-shaped patterns before any LLM
call, local or remote.

### Cleaning up afterwards

```bash
# Delete the source files now sealed in the urn (credentials are never touched)
agent-tomb bury ~/.hermes/ -n my-agent --cleanup
```

### Bringing the agent back

```bash
agent-tomb exhume my-agent.urn -o ./remains/
```

## Passphrase guidance

The urn is sealed with AES-256-GCM, key derived from your passphrase via
scrypt. Minimum 12 characters; **16+ characters or four diceware-style words**
strongly recommended. Lose the passphrase and the urn is gone forever.

## What's in each artifact

|                              | `.tomb` (public) | `.urn` (private) |
| ---------------------------- | :--------------: | :--------------: |
| `manifest.json`              |        ✓         |        ✓         |
| `soul.md` (persona, stats)   |        ✓         |                  |
| `epitaph.md`                 |        ✓         |                  |
| `stats.json`                 |        ✓         |                  |
| `burial.enc` (encrypted)     |                  |        ✓         |
| Raw conversations / state    |                  |    ✓ (sealed)    |
| Credentials (`.env`, `auth.json`) |             |                  |

Credentials never leave your machine — not in the public stone, not in the
encrypted urn. They belong to you, not the agent.

## Supported frameworks

- **Hermes** — `~/.hermes/` layout

OpenHands and others to follow.

## The cemetery

Visit [agentmemorial.com/cemetery](https://www.agentmemorial.com/cemetery) to
walk among the souls already laid to rest. To bury one of your own publicly,
open a PR adding your `.tomb` file (and its unpacked contents under
`cemetery/<slug>/`) to [`cemetery/`](./cemetery). CI rejects any `.urn` or
`burial.enc` by design — the private urn stays private.

## Repository layout

```
agent-tomb/
├── src/agent_tomb/   # Python CLI
├── web/              # Astro site (agentmemorial.com)
├── cemetery/         # public garden — submit your .tomb here
└── docs/             # design notes
```

## Design notes

- [`docs/project-vision.md`](docs/project-vision.md) — what this project is for
- [`docs/Hermes-Agent-File-Structure-Detailed.md`](docs/Hermes-Agent-File-Structure-Detailed.md) — Hermes layout reference
- [`DEPLOY.md`](DEPLOY.md) — deploying the website to Cloudflare Pages

## License

MIT — see [LICENSE](./LICENSE).
