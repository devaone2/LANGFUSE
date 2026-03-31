"""
run_agent.py — CLI runner and automated test harness

Usage
─────
  python run_agent.py --test    Run automated suite (generates Langfuse traces)
  python run_agent.py --chat    Interactive session
  python run_agent.py --check   Check service connectivity only
"""

import argparse
import logging
import time
import uuid

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule

logging.basicConfig(level=logging.WARNING)
console = Console()


# ============================================================
# Service health checks
# ============================================================

def check_postgres() -> bool:
    try:
        from memory import LongTermMemory
        LongTermMemory().ping()
        console.print("  ✅ PostgreSQL (Long-Term Memory):  [green]Connected[/green]")
        return True
    except Exception as exc:
        console.print(f"  ❌ PostgreSQL:  [red]Failed — {exc}[/red]")
        return False


def check_redis() -> bool:
    try:
        from memory import ShortTermMemory
        ShortTermMemory().ping()
        console.print("  ✅ Redis (Short-Term Memory):      [green]Connected[/green]")
        return True
    except Exception as exc:
        console.print(f"  ❌ Redis:       [red]Failed — {exc}[/red]")
        return False


def check_langfuse() -> bool:
    from config import settings
    if not settings.langfuse_enabled:
        console.print(
            "  ⚠️  Langfuse:   [yellow]API keys not configured "
            "— traces will not be sent[/yellow]\n"
            "     [dim]Set LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY in .env[/dim]"
        )
        return True  # not fatal — agent still works
    try:
        import urllib.request
        with urllib.request.urlopen(
            f"{settings.LANGFUSE_HOST}/api/public/health", timeout=5
        ) as r:
            ok = r.status == 200
        if ok:
            console.print(
                f"  ✅ Langfuse:    [green]Healthy  ({settings.LANGFUSE_HOST})[/green]"
            )
            return True
        console.print(f"  ❌ Langfuse:   [red]Unhealthy — HTTP {r.status}[/red]")
        return False
    except Exception as exc:
        console.print(f"  ❌ Langfuse:   [red]{exc}[/red]")
        return False


def run_checks(verbose: bool = True) -> bool:
    if verbose:
        console.print("\n[bold blue]🔍 Checking service connections …[/bold blue]\n")
    ok = check_postgres() and check_redis()
    check_langfuse()
    if not ok and verbose:
        console.print(
            "\n[red]Required services unreachable.[/red] "
            "Start them with:  [bold]docker compose up -d[/bold]"
        )
    return ok


# ============================================================
# Automated test suite
# ============================================================

# 4 rephrase inputs (short → long)  +  4 summary inputs (long → short)
TEST_CASES = [
    # ── Rephrase (short → long) ─────────────────────────────────────────
    {
        "agent":  "REPHRASE",
        "label":  "Single phrase — technology",
        "input":  "AI is changing the world.",
    },
    {
        "agent":  "REPHRASE",
        "label":  "Short sentence — health",
        "input":  "Exercise is good for mental health.",
    },
    {
        "agent":  "REPHRASE",
        "label":  "Brief concept — databases",
        "input":  "PostgreSQL is a powerful open-source database.",
    },
    {
        "agent":  "REPHRASE",
        "label":  "Terse phrase — teamwork",
        "input":  "Good communication builds strong teams.",
    },
    # ── Summary (long → short) ──────────────────────────────────────────
    {
        "agent":  "SUMMARY",
        "label":  "Paragraph — climate change",
        "input":  (
            "Climate change represents one of the most significant challenges facing humanity "
            "in the twenty-first century. The phenomenon, driven primarily by the release of "
            "greenhouse gases such as carbon dioxide and methane from industrial activity, "
            "transportation, and deforestation, has led to a measurable increase in global "
            "average temperatures. Scientists from the Intergovernmental Panel on Climate "
            "Change (IPCC) warn that without immediate and drastic reductions in emissions, "
            "the planet could warm by more than 1.5 degrees Celsius above pre-industrial "
            "levels within the next two decades. Consequences include rising sea levels, more "
            "frequent and severe weather events, disruption to agricultural systems, and mass "
            "extinction of species. Governments, corporations, and individuals all have a role "
            "to play in mitigation — through renewable energy adoption, carbon capture "
            "technologies, policy reform, and changes to personal consumption patterns."
        ),
    },
    {
        "agent":  "SUMMARY",
        "label":  "Article excerpt — LangGraph",
        "input":  (
            "LangGraph is an open-source library developed by the LangChain team that enables "
            "developers to build stateful, multi-actor applications powered by large language "
            "models. Unlike traditional linear chains of LLM calls, LangGraph models workflows "
            "as directed graphs, where nodes represent computation steps and edges define the "
            "flow of data between them. This graph-based approach allows for complex patterns "
            "such as loops, conditional branching, parallel execution, and human-in-the-loop "
            "interactions. The library provides a StateGraph abstraction that maintains a "
            "shared state dict across all nodes, enabling agents to read and write shared "
            "context throughout a conversation. LangGraph integrates natively with LangChain "
            "components, making it straightforward to incorporate tools, memory, and retrieval "
            "systems. It is particularly well-suited for building autonomous agents that need "
            "to reason, act, observe results, and iteratively refine their approach — a pattern "
            "commonly referred to as ReAct (Reason + Act)."
        ),
    },
    {
        "agent":  "SUMMARY",
        "label":  "Long explanation — Redis",
        "input":  (
            "Redis, which stands for Remote Dictionary Server, is an in-memory data structure "
            "store that is widely used as a database, cache, and message broker. Originally "
            "created by Salvatore Sanfilippo in 2009, Redis stores data as key-value pairs and "
            "supports a rich set of data structures including strings, hashes, lists, sets, "
            "sorted sets, bitmaps, hyperloglogs, and geospatial indexes. One of Redis's most "
            "important features is its exceptional performance — because all data is held in "
            "RAM, read and write operations are typically completed in sub-millisecond time, "
            "making it orders of magnitude faster than disk-based databases for many use cases. "
            "Redis supports optional persistence through RDB snapshots and AOF (Append-Only "
            "File) logging, allowing data to survive process restarts. Cluster mode enables "
            "horizontal scaling across multiple nodes, while Sentinel provides high availability "
            "through automatic failover. Redis Pub/Sub and Streams features make it suitable "
            "for real-time messaging and event-driven architectures. In the context of AI "
            "agent systems, Redis excels as a short-term memory store because its TTL "
            "mechanism naturally models the expiry of session context, and its speed allows "
            "low-latency access to recent conversation history during inference."
        ),
    },
    {
        "agent":  "SUMMARY",
        "label":  "Multi-sentence — observability",
        "input":  (
            "Observability in software systems refers to the ability to understand the internal "
            "state of a system by examining its external outputs — primarily logs, metrics, and "
            "traces. In the context of AI and LLM applications, observability is especially "
            "important because the behaviour of language models can be non-deterministic and "
            "difficult to debug. Platforms like Langfuse address this by capturing every LLM "
            "call, including the prompt, completion, model used, token counts, latency, and "
            "any associated cost. When agents use tools or make multiple LLM calls, Langfuse "
            "organises these into hierarchical traces — a parent trace for the overall request "
            "and child spans for each sub-operation. This structure allows engineers to quickly "
            "identify where latency is concentrated, which prompts are underperforming, and "
            "whether token usage is growing unexpectedly. Scores can be added to traces "
            "manually or programmatically, enabling continuous quality evaluation over time."
        ),
    },
]


def _agent_badge(route: str) -> str:
    colours = {"REPHRASE": "cyan", "SUMMARY": "magenta", "UNKNOWN": "yellow"}
    colour = colours.get(route, "white")
    return f"[{colour}]{route}[/{colour}]"


def run_test_suite():
    if not run_checks():
        return

    from agent import run_agent
    from config import settings

    provider = f"{settings.LLM_PROVIDER} / {settings.GROQ_MODEL or settings.GOOGLE_MODEL or settings.OLLAMA_MODEL}"
    console.print(
        f"\n[bold blue]🤖 Multi-Agent Test Suite[/bold blue]  "
        f"[dim]LLM: {provider}[/dim]\n"
    )

    session_id = str(uuid.uuid4())
    rows: list[dict] = []

    for i, case in enumerate(TEST_CASES, 1):
        expected = case["agent"]
        label    = case["label"]
        text     = case["input"]

        console.print(
            f"[bold]Test {i:02d}/{len(TEST_CASES):02d}[/bold]  "
            f"{_agent_badge(expected)} expected  │  {label}"
        )
        console.print(
            f"  [dim]Input ({len(text)} chars): "
            f"{text[:70].strip()}{'…' if len(text) > 70 else ''}[/dim]"
        )

        try:
            t0 = time.perf_counter()
            response, route, session_id = run_agent(text, session_id)
            elapsed = time.perf_counter() - t0

            match_icon = "✅" if route == expected else "⚠️ "
            preview = response[:110].strip() + ("…" if len(response) > 110 else "")
            console.print(
                f"  {match_icon} Routed to {_agent_badge(route)}  "
                f"[dim]{elapsed:.2f}s[/dim]  |  Output: {len(response)} chars"
            )
            console.print(f"  [dim italic]↳ {preview}[/dim italic]\n")

            rows.append({
                "n":       str(i),
                "label":   label,
                "expect":  expected,
                "got":     route,
                "match":   "✅" if route == expected else "⚠️",
                "time":    f"{elapsed:.2f}s",
                "out_len": f"{len(response):,}",
            })

        except Exception as exc:
            console.print(f"  [red]❌ Error: {exc}[/red]\n")
            rows.append({
                "n": str(i), "label": label, "expect": expected,
                "got": "ERROR", "match": "❌", "time": "—", "out_len": "—",
            })

        time.sleep(0.4)

    # ── Summary table ────────────────────────────────────────────────
    console.print(Rule("[bold]Results[/bold]"))
    tbl = Table(show_header=True, header_style="bold")
    tbl.add_column("#",           width=4)
    tbl.add_column("Test label",  style="cyan", min_width=30)
    tbl.add_column("Expected",    width=10)
    tbl.add_column("Got",         width=10)
    tbl.add_column("✓",           width=3)
    tbl.add_column("Time",        width=7, style="dim")
    tbl.add_column("Output",      width=8, style="dim")

    for r in rows:
        tbl.add_row(r["n"], r["label"], r["expect"], r["got"],
                    r["match"], r["time"], r["out_len"])
    console.print(tbl)

    correct = sum(1 for r in rows if r["match"] == "✅")
    console.print(
        f"\n  Routing accuracy: [bold green]{correct}/{len(rows)}[/bold green] correct\n"
    )

    _show_memory_stats(session_id)
    _show_langfuse_link(session_id)


# ============================================================
# Memory stats
# ============================================================

def _show_memory_stats(session_id: str):
    console.print(Rule("[bold]Memory Storage Verification[/bold]"))

    # PostgreSQL
    try:
        from memory import LongTermMemory
        ltm     = LongTermMemory()
        history = ltm.get_history(session_id)
        metrics = ltm.get_metrics(session_id)

        tbl = Table(
            title=f"PostgreSQL · conversation_history  (session …{session_id[-8:]})",
            show_lines=True,
        )
        tbl.add_column("Role",            style="cyan",  width=18)
        tbl.add_column("Content preview", style="white", min_width=55)
        tbl.add_column("Timestamp",       style="dim",   width=20)

        for msg in history[-12:]:
            preview = (msg.content[:52] + "…") if len(msg.content) > 52 else msg.content
            tbl.add_row(msg.role, preview, str(msg.timestamp)[:19])

        console.print(tbl)

        if metrics:
            console.print(
                f"  Total messages: [green]{metrics.total_messages}[/green]  │  "
                f"Agent turns stored: [green]{metrics.tool_calls_count}[/green]  │  "
                f"Session started: [dim]{str(metrics.started_at)[:19]}[/dim]"
            )
    except Exception as exc:
        console.print(f"  [red]PostgreSQL stats error: {exc}[/red]")

    # Redis
    try:
        from memory import ShortTermMemory
        stm     = ShortTermMemory()
        cached  = stm.get_recent_messages(session_id)
        info    = stm.get_session_info(session_id)

        console.print(
            f"\n  Redis STM cache: [green]{len(cached)}[/green] messages  │  "
            f"Session keys: {list(info.keys())}"
        )
    except Exception as exc:
        console.print(f"  [red]Redis stats error: {exc}[/red]")


# ============================================================
# Langfuse link
# ============================================================

def _show_langfuse_link(session_id: str):
    from config import settings
    console.print()
    if settings.langfuse_enabled:
        console.print(
            Panel.fit(
                f"[bold green]📊 Langfuse traces generated![/bold green]\n\n"
                f"Open the dashboard:  [link={settings.LANGFUSE_HOST}]{settings.LANGFUSE_HOST}[/link]\n\n"
                f"Filter by Session ID:\n[dim]{session_id}[/dim]\n\n"
                f"You will see [bold]three nested spans[/bold] per request:\n"
                f"  1. [cyan]orchestrator[/cyan] — routing LLM call\n"
                f"  2. [cyan]rephrase[/cyan] or [magenta]summary[/magenta] — specialist LLM call\n"
                f"  Metadata, token counts, and latency are on each span.",
                border_style="green",
                title="Langfuse",
            )
        )
    else:
        console.print(
            "[yellow]⚠️  Langfuse not configured — add API keys to .env "
            "to see traces in the UI.[/yellow]"
        )


# ============================================================
# Interactive chat
# ============================================================

def run_interactive():
    if not run_checks():
        return

    from agent import run_agent
    from config import settings

    session_id = str(uuid.uuid4())
    console.print(
        Panel.fit(
            f"[bold green]💬 Multi-Agent Interactive Chat[/bold green]\n\n"
            f"Send a [cyan]short phrase[/cyan] → [bold]Rephrase Agent[/bold] expands it\n"
            f"Send a [magenta]long paragraph[/magenta] → [bold]Summary Agent[/bold] condenses it\n\n"
            f"LLM: [dim]{settings.LLM_PROVIDER}[/dim]  │  "
            f"Session: [dim]{session_id[:12]}…[/dim]\n"
            f"Type [bold]exit[/bold] to quit.",
            border_style="green",
        )
    )

    while True:
        try:
            user_input = console.input("\n[bold yellow]You:[/bold yellow] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Session ended.[/dim]")
            break

        if user_input.lower() in {"exit", "quit", "q"}:
            console.print("[dim]Session ended.[/dim]")
            break
        if not user_input:
            continue

        with console.status("[dim]Processing …[/dim]", spinner="dots"):
            try:
                response, route, session_id = run_agent(user_input, session_id)
            except Exception as exc:
                console.print(f"[red]Error: {exc}[/red]")
                continue

        badge = _agent_badge(route)
        console.print(f"\n[bold blue]Agent[/bold blue] [{badge}]: {response}")

    _show_memory_stats(session_id)
    _show_langfuse_link(session_id)


# ============================================================
# Entry point
# ============================================================

def main():
    console.print(
        Panel.fit(
            "[bold blue]🚀 LangGraph Multi-Agent System[/bold blue]\n"
            "[dim]Orchestrator  ·  Rephrase Agent  ·  Summary Agent[/dim]\n"
            "[dim]Observability: Langfuse  ·  LTM: PostgreSQL  ·  STM: Redis[/dim]",
            border_style="blue",
        )
    )

    parser = argparse.ArgumentParser(description="Multi-agent LangGraph runner")
    grp    = parser.add_mutually_exclusive_group()
    grp.add_argument("--test",  action="store_true", help="Run automated test suite")
    grp.add_argument("--chat",  action="store_true", help="Start interactive chat")
    grp.add_argument("--check", action="store_true", help="Check service connectivity")
    args = parser.parse_args()

    if args.check:
        run_checks()
    elif args.chat:
        run_interactive()
    else:
        run_test_suite()   # default


if __name__ == "__main__":
    main()
