# 🤖 LangGraph Multi-Agent System + Langfuse Observability

A fully local, production-grade **three-agent** AI system built with **LangGraph** for orchestration and **Langfuse** for end-to-end observability — backed by **PostgreSQL** (long-term memory) and **Redis** (short-term memory), all running in Docker.

> No ClickHouse. No MinIO. Three agents. One trace per request.

---

## The Three Agents

| Agent | Role | Input | Output |
|---|---|---|---|
| **Orchestrator** | Routes the request to the right specialist | Any user text | `REPHRASE` or `SUMMARY` decision |
| **Rephrase Agent** | Expands short sentences into rich, detailed prose | A short phrase or sentence | 3–5× longer elaborated text |
| **Summary Agent** | Condenses long text into a concise summary | A paragraph, article, or document | 15–25% length summary |

Each agent has its own **system prompt** and **independently tuned temperature**, and every LLM call is captured as a separate span in Langfuse.

---

## Architecture

```
User Input
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│                   LangGraph State Machine                    │
│                                                              │
│   START                                                      │
│     │                                                        │
│     ▼                                                        │
│  ┌─────────────────────┐                                     │
│  │   Orchestrator      │  temperature=0.0 (deterministic)    │
│  │   (LLM Node)        │  → reads user input                 │
│  │                     │  → outputs: REPHRASE | SUMMARY      │
│  └─────────┬───────────┘                                     │
│            │  conditional edge                               │
│     ┌──────┴───────┐                                         │
│     ▼              ▼                                         │
│  ┌──────────┐  ┌──────────┐                                  │
│  │ Rephrase │  │ Summary  │                                  │
│  │  Agent   │  │  Agent   │                                  │
│  │  (LLM)   │  │  (LLM)   │                                  │
│  │ temp=0.8 │  │ temp=0.2 │                                  │
│  └────┬─────┘  └────┬─────┘                                  │
│       │              │                                        │
│       └──────┬───────┘                                       │
│              ▼                                               │
│            END                                               │
└──────────────────────────────────────────────────────────────┘
    │                              │
    ▼                              ▼
PostgreSQL (LTM)              Langfuse Trace
  • conversation_history        ┌────────────────────────────┐
  • session_metrics             │  Trace: run_agent          │
  • agent turns stored          │  ├─ orchestrator span      │
                                │  │   LLM call + token count│
Redis (STM)                    │  └─ rephrase | summary span │
  • recent messages (TTL 1h)    │      LLM call + latency    │
  • session context             └────────────────────────────┘
```

### Memory Design

| Layer | Store | Database | What is Stored | Persistence |
|---|---|---|---|---|
| **LTM** | PostgreSQL | `agent_memory` | Full conversation history, routing decisions, agent outputs, session metrics | Permanent |
| **STM** | Redis | DB 0 | Last 20 messages per session (ring buffer), ephemeral context | TTL: 1 hour |
| **Traces** | PostgreSQL | `langfuse` | Every LLM span with token counts, latency, model name, metadata | Permanent |

---

## Project Structure

```
LANGFUSE/
├── docker-compose.yml    # postgres + redis + langfuse (v2) — no ClickHouse/MinIO
├── init-db.sql           # creates langfuse + agent_memory databases on first run
├── .env.example          # template — copy to .env
├── requirements.txt      # Python dependencies
├── Makefile              # convenience commands
│
├── config.py             # all settings loaded from .env (pydantic-settings)
├── memory.py             # LTM (PostgreSQL) + STM (Redis) classes
├── tools.py              # placeholder — not used in current agent design
├── agent.py              # LangGraph graph + 3 agent nodes + Langfuse wiring
└── run_agent.py          # CLI: --test | --chat | --check
```

---

## Prerequisites

- **Docker Desktop** (or Docker Engine + Compose plugin)
- **Python 3.10+**
- A **free LLM API key** — pick one:
  - [Groq](https://console.groq.com) *(recommended — fast, very generous free tier)*
  - [Google AI Studio](https://aistudio.google.com) *(Gemini 1.5 Flash)*
  - [Ollama](https://ollama.com) *(fully local, no key needed)*

---

## Quick Start

### 1. Start Docker services

```bash
docker compose up -d
```

This brings up three containers:

| Container | Port | Purpose |
|---|---|---|
| `agent_postgres` | 5432 | Langfuse traces + Agent LTM |
| `agent_redis` | 6379 | Agent STM session cache |
| `langfuse_server` | 3000 | Langfuse observability UI |

Wait about 20 seconds for Langfuse to complete its database migrations.

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in at minimum:

```env
# Free Groq API key → https://console.groq.com
GROQ_API_KEY=gsk_...

# Langfuse keys — see step 3
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

### 3. Get Langfuse API keys

1. Open **http://localhost:3000**
2. Sign up (no email verification)
3. Create a project (e.g., `multi-agent`)
4. Go to **Settings → API Keys → Create new key**
5. Copy both keys into `.env`

### 4. Install and run

```bash
pip install -r requirements.txt

python run_agent.py --test    # run 8 automated tests (generates Langfuse traces)
python run_agent.py --chat    # interactive chat
python run_agent.py --check   # connectivity check only
```

Or use `make`:
```bash
make check
make test
make chat
```

---

## Viewing Traces in Langfuse

After running the agent, open **http://localhost:3000 → Traces**. Each `run_agent` call produces **one trace** with **two nested LLM spans**:

```
Trace: run_agent  [session: abc123…]
  │
  ├── orchestrator (LLM span)
  │     model: llama-3.1-8b-instant
  │     input: user text
  │     output: "REPHRASE"
  │     tokens: 85 in / 1 out  │  latency: 0.4s
  │
  └── rephrase (LLM span)                   ← or "summary"
        model: llama-3.1-8b-instant
        input: system prompt + user text
        output: expanded prose
        tokens: 210 in / 420 out  │  latency: 1.2s
```

**Filtering in the UI:**
- Filter by `session_id` to see all turns in one conversation
- Filter by tag `multi-agent` to isolate this system's traces
- Each span shows token usage, cost estimate, and exact latency

---

## Supported LLM Providers

Set `LLM_PROVIDER` in `.env` to switch providers:

### Groq (default — recommended)
```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.1-8b-instant
```
Free tier: ~14,400 requests/day. No credit card required.

### Google Gemini
```env
LLM_PROVIDER=google
GOOGLE_API_KEY=AIza...
GOOGLE_MODEL=gemini-1.5-flash
```

### Ollama (fully local)
```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```
Requires Ollama running: `ollama pull llama3.2`

---

## Database Schema (PostgreSQL `agent_memory`)

```sql
-- Full message history per session
conversation_history (
    id          SERIAL PRIMARY KEY,
    session_id  VARCHAR(255),   -- groups messages by conversation
    role        VARCHAR(50),    -- human | orchestrator | rephrase_agent | summary_agent
    content     TEXT,
    tool_calls  JSON,           -- routing decision metadata
    timestamp   TIMESTAMPTZ
)

-- Per-session aggregate metrics
session_metrics (
    id                 SERIAL PRIMARY KEY,
    session_id         VARCHAR(255) UNIQUE,
    langfuse_trace_id  VARCHAR(255),
    total_messages     INTEGER,
    tool_calls_count   INTEGER,   -- re-used to count agent invocations
    started_at         TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ
)
```

Connect with any PostgreSQL client:
```
host: localhost   port: 5432
user: postgres    password: postgres123
database: agent_memory
```

---

## Agent Behaviour Details

### Orchestrator Agent
- Temperature: `0.0` (fully deterministic — must route consistently)
- Outputs exactly one word: `REPHRASE`, `SUMMARY`, or `UNKNOWN`
- Routing logic: input length and intent — short/fragmentary → rephrase; long/complete → summarise

### Rephrase Agent
- Temperature: `0.8` (creative and varied)
- Target expansion: 3–5× the original length
- Adds context, examples, analogies, and elaboration while preserving meaning

### Summary Agent
- Temperature: `0.2` (factual and precise)
- Target compression: 15–25% of original length
- Preserves all key information; eliminates redundancy and filler

---

## Makefile Reference

```bash
make up          # start all Docker containers
make down        # stop containers
make logs        # tail container logs
make ps          # show container status
make setup       # copy .env.example → .env
make install     # pip install -r requirements.txt
make check       # verify all service connections
make test        # run automated test suite (generates traces)
make chat        # start interactive chat
make clean       # remove containers + volumes ⚠️ deletes all data
```

---

## Troubleshooting

**Langfuse UI not loading at :3000**
Run `docker compose logs langfuse-server` — it may still be running migrations (allow 30s).

**`connection refused` on PostgreSQL / Redis**
Run `docker compose ps` to check container health. Ensure Docker Desktop is running.

**LLM quota errors**
Groq free tier resets daily. Try switching `GROQ_MODEL` to `mixtral-8x7b-32768` or use the `google` provider.

**Agent always routes to UNKNOWN**
Check your LLM API key is valid. The orchestrator may be failing silently — run `python run_agent.py --check` and look for errors.

**Traces not appearing in Langfuse**
Verify both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set in `.env` and belong to the same project.

---

## Security Notes

> This stack is for **local development only**.

- Rotate `NEXTAUTH_SECRET`, `SALT`, and `ENCRYPTION_KEY` before exposing to any network
- Add `.env` to `.gitignore` — never commit your API keys
- The database credentials in `docker-compose.yml` should be changed for shared environments
