# EAGV3 Session 9 — Growing-Graph Agent with Browser Skill

A multi-skill AI agent built on a dynamically growing DAG (Directed Acyclic Graph) orchestrator. Session 9 adds a four-layer Browser skill on top of the Session 8 runtime, enabling the agent to fetch, interact with, and visually understand web pages.

## Overview

The system routes a user query through a pipeline of specialised skills (Planner, Researcher, Distiller, etc.). The graph grows at runtime: the Planner seeds the initial DAG, and each skill can emit successor nodes, causing the graph to expand dynamically. Session 9 introduces the **Browser skill** — a cascade across four extraction layers — as a first-class skill in the orchestrator.

```
User query
    │
    ▼
Planner ──► Researcher(s) ──► Distiller ──► [Critic] ──► Formatter
              │
              └──► Browser ──► url_extractor ──► Comparator ──► Formatter
```

## Architecture

### Core Orchestrator (`flow.py`)

The central orchestrator maintains a `NetworkX DiGraph` where each node is a skill invocation. The graph **grows** during execution via five mechanisms:

1. **Planner's seed plan** — initial DAG from the first Planner node
2. **Dynamic successors** — any skill can emit `successors` in its output
3. **Static `internal_successors`** — YAML-declared automatic follow-ups (e.g., Coder always spawns SandboxExecutor)
4. **Critic auto-insertion** — skills marked `critic: true` in YAML automatically get a Critic node gated on every outgoing edge
5. **Recovery re-planning** — failed nodes trigger a new Planner invocation with a failure report

The executor runs ready nodes in parallel using `asyncio.gather`, persisting each node's state atomically to disk.

### Skills (`agent_config.yaml` + `skills.py`)

Each skill is a YAML entry referencing a Markdown prompt file. No per-skill Python classes — the dispatcher in `skills.py` handles all skills uniformly:

| Skill | Description | Special dispatch |
|---|---|---|
| `planner` | Decomposes queries into DAGs; also handles recovery sub-graphs | Standard LLM |
| `researcher` | Multi-step web research (web_search, fetch_url tools) | MCP tool loop |
| `retriever` | Searches FAISS memory index | MCP tool loop |
| `distiller` | Extracts structured fields from raw content; triggers Critic | Standard LLM |
| `critic` | Evaluates upstream output; emits `pass`/`fail` + rationale | Standard LLM |
| `summariser` | Condenses long content | Standard LLM |
| `formatter` | Renders the final user-facing answer | Standard LLM |
| `coder` | Emits Python code; always followed by sandbox_executor | Standard LLM |
| `sandbox_executor` | Runs code in an isolated subprocess | Direct (no gateway) |
| `browser` | Four-layer web cascade (see below) | Direct (no gateway) |
| `url_extractor` | Parses slugs from list pages; fans out to detail-browser nodes | Direct (regex) |
| `comparator` | Compares N BrowserOutput payloads into a structured table | Standard LLM |

### Browser Skill (`browser/`)

The Browser skill implements a cost-ordered cascade, stopping at the first layer that produces a useful result:

```
Layer 1  — HTTP fetch + trafilatura extraction  (no LLM, free)
Layer 2a — Deterministic Playwright selectors   (only if caller supplies selectors)
Layer 2b — A11y text-only driver               (Playwright + /v1/chat, cheap)
Layer 3  — Set-of-Marks vision driver          (Playwright + /v1/vision, expensive)
```

**Escalation rule:** a layer escalates when its output is empty, too short (< 200 chars), or the goal requires interaction. Gateway blocks (CAPTCHA, Cloudflare, login walls) are detected at each layer and surface as `error_code="gateway_blocked"`, triggering Planner recovery.

Key files:
- `browser/skill.py` — cascade wrapper; the only new file in Session 9
- `browser/driver.py` — `BaseDriver`, `A11yDriver`, `SetOfMarksDriver`
- `browser/dom.py` — Playwright element enumeration; produces the interactive-element legend
- `browser/highlight.py` — Pillow-based screenshot annotation for Set-of-Marks
- `browser/client.py` — typed V9 gateway client (`/v1/chat`, `/v1/vision`, `/v1/embed`)

### Memory (`memory.py`)

A typed four-kind memory service backed by a FAISS vector index with keyword search as fallback:

- **fact** — classified facts; embedded at write time
- **preference** — user preferences; embedded at write time  
- **tool_outcome** — results of tool calls; embedded at write time
- **scratchpad** — run-scoped items; not embedded

Reads use vector similarity (FAISS cosine) first, falling back to keyword overlap when the vector path returns nothing. Memory is read once at session start and injected into every skill's prompt (`MEMORY HITS` block).

### Recovery (`recovery.py`)

Failure classification and recovery decisions are centralised here, keeping `flow.py` focused on graph mechanics:

| Failure reason | Action |
|---|---|
| `transient` (5xx, timeout) | `skip` — gateway already retried |
| `validation_error` (malformed NodeSpec) | `skip` — prompt bug, not a runtime issue |
| `upstream_failure` on `planner` | `skip` — avoids infinite Planner loops |
| `upstream_failure` on any other skill | `replan` — queues a new Planner with failure report |

Critic failures (verdict=`fail`) follow a separate path: the child node is skipped and a recovery Planner is queued. A per-target cap prevents infinite critic-fail loops.

### Persistence (`persistence.py`)

Sessions are stored under `state/sessions/<sid>/`:

```
state/sessions/<sid>/
    graph.json          # NetworkX DiGraph serialised via node_link_data
    query.txt           # verbatim user query
    nodes/
        n_001.json      # NodeState (includes prompt_sent for replay)
        n_002.json
        ...
```

All writes are atomic (write to `.tmp`, then `os.replace`). The graph is JSON (not pickle) so it is readable by students and survives Python upgrades.

### Gateway (`gateway.py`)

Bridge to `llm_gatewayV9` running on `:8109`. Auto-starts the gateway if it is not already up. V9 adds two capabilities over V8:

- `/v1/vision` — typed shim for single-image vision calls (used by Browser Layer 3)
- `/v1/cost/by_agent` — per-agent USD pricing so each skill's cost is attributable

## Project Structure

```
S9SharedCode/
├── run_demo.sh              # Demo runner: pytest + 5 canonical queries
├── code/
│   ├── flow.py              # Orchestrator: Graph + Executor
│   ├── skills.py            # Skill registry + per-node execution
│   ├── gateway.py           # V9 gateway bridge
│   ├── memory.py            # Vector + keyword memory service
│   ├── recovery.py          # Failure classification + recovery decisions
│   ├── persistence.py       # Session + node state on disk
│   ├── schemas.py           # Pydantic contracts (AgentResult, NodeSpec, etc.)
│   ├── artifacts.py         # Byte-level artifact storage
│   ├── sandbox.py           # Python subprocess sandbox for Coder
│   ├── vector_index.py      # FAISS wrapper
│   ├── replay.py            # CLI replay of a session
│   ├── replay_html.py       # HTML replay renderer
│   ├── mcp_runner.py        # Multi-turn MCP tool-use loop
│   ├── mcp_server.py        # MCP server (search_knowledge, web_search, etc.)
│   ├── decision.py          # (legacy) single-turn decision layer
│   ├── perception.py        # (legacy) observation / goal layer
│   ├── action.py            # (legacy) tool dispatch layer
│   ├── agent_config.yaml    # Skill catalogue (prompts, tools, temperatures)
│   ├── pyproject.toml       # Project metadata and dependencies
│   ├── requirements.txt     # Flat dependency list
│   ├── .env.example         # Provider API key template
│   ├── VALIDATION.md        # Session 9 integration validation log
│   ├── browser/
│   │   ├── skill.py         # BrowserSkill cascade wrapper (NEW in S9)
│   │   ├── driver.py        # A11yDriver + SetOfMarksDriver
│   │   ├── dom.py           # Interactive element enumeration
│   │   ├── highlight.py     # Screenshot annotation
│   │   ├── client.py        # V9 gateway client
│   │   └── __init__.py
│   ├── prompts/             # Markdown system prompts for each skill
│   ├── state/               # Runtime state (memory, FAISS index, sessions)
│   ├── replays/             # HTML replay files from previous sessions
│   └── tests/               # Unit tests
└── logs/                    # Demo run logs (one file per query slug)
```

## Setup

### Prerequisites

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/) package manager
- `llm_gatewayV9` running on `:8109` (sibling directory `../llm_gatewayV9`)
- Playwright browsers (installed automatically by `uv sync`)

### Installation

```bash
cd code
uv sync
uv run playwright install chromium
```

### Configuration

Copy `.env.example` to `.env` and fill in your API keys. Minimum required: one worker provider (Gemini recommended) for LLM calls.

```bash
cp code/.env.example code/.env
# edit .env with your keys
```

Supported providers: Gemini, Cerebras, NVIDIA, GitHub Models, OpenRouter. Embedding uses Ollama (local) with Gemini as fallback.

### Start the Gateway

```bash
cd ../llm_gatewayV9 && uv run main.py
```

## Usage

### Run a query

```bash
cd code
uv run python flow.py "Find the populations of London, Paris, and Berlin."
```

### Resume a session

```bash
uv run python flow.py --resume <session-id> ""
```

### Replay a session

```bash
uv run python replay.py <session-id>
```

### Inspect a node's rendered prompt

```bash
python3 -c "import json; print(json.load(open('state/sessions/<sid>/nodes/n_001.json'))['prompt_sent'])"
```

### Clear state between demos

```bash
./run_demo.sh wipe
```

## Demo Queries

The `run_demo.sh` script runs a curated set of queries that each exercise one orchestrator feature:

| Slug | Query shape | Feature demonstrated |
|---|---|---|
| `hello` | planner → formatter | Smallest possible DAG; no research needed |
| `shannon` | planner → researcher → formatter | Single-item query; USER_QUERY flow |
| `populations` | planner → researcher×3 → formatter | Parallel fan-out; per-worker scoping |
| `structured` | planner → researcher×N → distiller → critic → formatter | Auto-critic insertion |
| `fail` | planner → formatter | Graceful-fail-by-planning (planner recognises doomed input) |
| `browser` | planner → browser → distiller → formatter | Session 9 Browser skill end-to-end |

```bash
./run_demo.sh            # run pytest + all 5 canonical queries
./run_demo.sh browser    # Session 9 Browser skill demo (requires Playwright)
./run_demo.sh tests      # unit tests only
./run_demo.sh shannon    # single query
```

## Tests

```bash
cd code
uv run pytest tests/ -v
```

Test suite covers:
- `test_recovery.py` — 22 recovery policy tests
- `test_recovery_amnesia.py` — 3 recovery Planner amnesia fix tests
- `test_critic_autoinsert.py` — 4 critic auto-insertion tests
- `test_url_extractor.py` — URL extractor slug parsing
- `test_replay_html.py` — HTML replay rendering
- `test_natural_vision_search.py` — Browser natural Layer 3 escalation

## Key Design Decisions

**Per-worker scoping:** fan-out workers (e.g., three Researcher nodes for three cities) receive their individual sub-question via `metadata.question` (rendered as a `QUESTION:` block), not the full `USER_QUERY`. This prevents each worker from researching all three cities instead of one.

**Critic auto-insertion covers pre-planned edges:** the Critic gate reads the graph's actual outgoing edges (not just dynamically added nodes), so a `distiller → formatter` edge pre-wired by the Planner also gets a Critic spliced in. Earlier versions only saw newly-added nodes and the `critic: true` flag was a no-op for pre-planned shapes.

**Recovery Planner amnesia fix:** when recovering from a node failure, the recovery Planner receives the IDs of already-completed nodes so it can reference their outputs directly (`n:2`, `n:3`, etc.) instead of re-emitting fresh fan-out siblings that duplicate work.

**Browser cascade economics:** Layer 1 (trafilatura) is free and handles most static content (Wikipedia, article pages). Layer 2b (a11y) handles most interactive content including most canvas apps because aria-labelled toolbars + coordinate drag actions cover them. Layer 3 (vision) fires only when the page has no DOM grip at all and the goal requires acting on pixel content.

## Typed Contracts

All inter-layer communication uses Pydantic models defined in `schemas.py`:

- `AgentResult` — what every skill returns to the orchestrator
- `NodeSpec` — a node the orchestrator will add to the graph
- `NodeState` — persisted per-node state (includes `prompt_sent` for replay)
- `BrowserOutput` — typed payload from the Browser skill (includes `path`, `content`, `actions`)
- `MemoryItem` — one record in the memory store
- `ErrorCode` — structured failure taxonomy for the Browser skill
