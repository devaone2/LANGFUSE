"""
agent.py — Three-agent LangGraph system with Langfuse observability

Agents
──────
  1. Orchestrator   Routes user input to the appropriate specialist
  2. Rephrase       Expands a short sentence into rich, detailed prose
  3. Summary        Condenses long text into a concise summary

Graph topology
──────────────

  START
    │
    ▼
  orchestrator_node          ← decides: REPHRASE | SUMMARY | UNKNOWN
    │
    ├─► rephrase_node  ──► END
    ├─► summary_node   ──► END
    └─► unknown_node   ──► END

Langfuse monitoring
───────────────────
  Every node execution + every LLM call is automatically captured as a
  nested span inside one root Trace per user request via CallbackHandler.
  Tags, session_id, user_id, agent metadata and routing decision are all
  surfaced in the Langfuse UI.
"""

import logging
import uuid
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from config import settings
from memory import LongTermMemory, ShortTermMemory

logger = logging.getLogger(__name__)

# ============================================================
# Memory singletons
# ============================================================
ltm = LongTermMemory()
stm = ShortTermMemory()


# ============================================================
# LLM factory
# ============================================================
def _build_llm(temperature: float = 0.5):
    provider = settings.LLM_PROVIDER.lower()
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            api_key=settings.GROQ_API_KEY,
            model=settings.GROQ_MODEL,
            temperature=temperature,
        )
    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            google_api_key=settings.GOOGLE_API_KEY,
            model=settings.GOOGLE_MODEL,
            temperature=temperature,
        )
    elif provider == "ollama":
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_MODEL,
            temperature=temperature,
        )
    else:
        raise ValueError(f"Unknown LLM_PROVIDER='{provider}'")


# ============================================================
# Per-agent LLMs  (each tuned independently)
# ============================================================
orchestrator_llm = _build_llm(temperature=0.0)   # deterministic — must be consistent
rephrase_llm     = _build_llm(temperature=0.8)   # creative — varied, expressive output
summary_llm      = _build_llm(temperature=0.2)   # factual — precise condensation


# ============================================================
# System prompts
# ============================================================
ORCHESTRATOR_SYSTEM = """\
You are an intelligent routing agent inside a multi-agent pipeline.

Your sole responsibility is to read the user's input and decide which
specialist agent should handle it.

Decision rules
──────────────
• SHORT input (a word, phrase, or one-to-two sentences that needs
  expanding, elaborating, or making more detailed)
  → reply with exactly the single word:  REPHRASE

• LONG input (a paragraph, article, conversation, or document that
  needs condensing, summarising, or shortening)
  → reply with exactly the single word:  SUMMARY

• Cannot determine which applies
  → reply with exactly the single word:  UNKNOWN

IMPORTANT: Reply with ONE word only — REPHRASE, SUMMARY, or UNKNOWN.
Do not add any explanation, punctuation, or whitespace."""

REPHRASE_SYSTEM = """\
You are an expert writing coach and language-expansion specialist.

Your task is to transform a short, brief sentence or phrase into rich,
detailed, well-structured prose.

Guidelines
──────────
• Preserve the original meaning and intent exactly.
• Add relevant context, examples, analogies, and elaboration.
• Use vivid, precise, and engaging language.
• Target 3–5× the length of the original.
• Maintain a professional yet accessible tone.
• Structure your output in clear, flowing paragraphs — no bullet lists.\
"""

SUMMARY_SYSTEM = """\
You are a concise summarisation expert.

Your task is to distil long or complex text into a clear, accurate,
and brief summary.

Guidelines
──────────
• Capture every key point and essential piece of information.
• Eliminate redundancy, filler, and tangential detail.
• Aim for 15–25 % of the original length.
• Write in clear, direct, complete sentences.
• Preserve the logical order of the original.
• Include the most important facts, figures, and conclusions.\
"""


# ============================================================
# Graph state
# ============================================================
class AgentState(TypedDict):
    messages:     Annotated[list[BaseMessage], add_messages]
    session_id:   str
    user_input:   str
    agent_route:  str   # "REPHRASE" | "SUMMARY" | "UNKNOWN"
    agent_output: str   # final text produced by the chosen sub-agent


# ============================================================
# Node 1 — Orchestrator
# ============================================================
def orchestrator_node(state: AgentState) -> AgentState:
    """
    Reads the user input and decides which specialist handles it.
    Produces a single-word routing token: REPHRASE | SUMMARY | UNKNOWN.
    """
    logger.info("[Orchestrator] Routing for session %s", state["session_id"])

    response = orchestrator_llm.invoke([
        SystemMessage(content=ORCHESTRATOR_SYSTEM),
        HumanMessage(content=f"User input:\n\n{state['user_input']}"),
    ])

    raw    = response.content.strip().upper()
    route  = raw if raw in {"REPHRASE", "SUMMARY"} else "UNKNOWN"

    logger.info("[Orchestrator] Decision → %s", route)

    # Persist the routing decision
    ltm.save_message(
        session_id=state["session_id"],
        role="orchestrator",
        content=f"Routing decision: {route}",
    )
    stm.push_message(state["session_id"], "orchestrator", f"Route → {route}")

    return {
        "messages":    [AIMessage(content=f"[Orchestrator] → {route}")],
        "agent_route": route,
    }


# ============================================================
# Node 2 — Rephrase Agent
# ============================================================
def rephrase_node(state: AgentState) -> AgentState:
    """
    Expands a short sentence or phrase into detailed, well-structured prose.
    """
    logger.info("[Rephrase Agent] Expanding input for session %s", state["session_id"])

    response = rephrase_llm.invoke([
        SystemMessage(content=REPHRASE_SYSTEM),
        HumanMessage(
            content=f"Expand and elaborate the following into rich, detailed prose:\n\n"
                    f"{state['user_input']}"
        ),
    ])

    output = response.content.strip()
    logger.info(
        "[Rephrase Agent] Input: %d chars → Output: %d chars",
        len(state["user_input"]),
        len(output),
    )

    ltm.save_message(
        session_id=state["session_id"],
        role="rephrase_agent",
        content=output,
    )
    stm.push_message(state["session_id"], "rephrase_agent", output[:200])
    ltm.upsert_metrics(state["session_id"], increment_messages=1)

    return {
        "messages":    [AIMessage(content=output)],
        "agent_output": output,
    }


# ============================================================
# Node 3 — Summary Agent
# ============================================================
def summary_node(state: AgentState) -> AgentState:
    """
    Condenses long text into a concise, accurate summary.
    """
    logger.info("[Summary Agent] Summarising input for session %s", state["session_id"])

    response = summary_llm.invoke([
        SystemMessage(content=SUMMARY_SYSTEM),
        HumanMessage(
            content=f"Summarise the following text concisely:\n\n"
                    f"{state['user_input']}"
        ),
    ])

    output = response.content.strip()
    logger.info(
        "[Summary Agent] Input: %d chars → Output: %d chars",
        len(state["user_input"]),
        len(output),
    )

    ltm.save_message(
        session_id=state["session_id"],
        role="summary_agent",
        content=output,
    )
    stm.push_message(state["session_id"], "summary_agent", output[:200])
    ltm.upsert_metrics(state["session_id"], increment_messages=1)

    return {
        "messages":    [AIMessage(content=output)],
        "agent_output": output,
    }


# ============================================================
# Fallback node — Unknown route
# ============================================================
def unknown_node(state: AgentState) -> AgentState:
    msg = (
        "I couldn't determine whether to expand or summarise your input.\n\n"
        "• Send a short phrase or sentence → I'll elaborate it into detailed prose.\n"
        "• Send a long paragraph or article → I'll condense it into a summary."
    )
    ltm.save_message(
        session_id=state["session_id"],
        role="system",
        content="[Unknown route fallback]",
    )
    return {
        "messages":    [AIMessage(content=msg)],
        "agent_output": msg,
    }


# ============================================================
# Routing condition
# ============================================================
def route_after_orchestrator(
    state: AgentState,
) -> Literal["rephrase", "summary", "unknown"]:
    match state.get("agent_route", "UNKNOWN"):
        case "REPHRASE":
            return "rephrase"
        case "SUMMARY":
            return "summary"
        case _:
            return "unknown"


# ============================================================
# Compile the graph
# ============================================================
_workflow = StateGraph(AgentState)

_workflow.add_node("orchestrator", orchestrator_node)
_workflow.add_node("rephrase",     rephrase_node)
_workflow.add_node("summary",      summary_node)
_workflow.add_node("unknown",      unknown_node)

_workflow.add_edge(START, "orchestrator")
_workflow.add_conditional_edges(
    "orchestrator",
    route_after_orchestrator,
    {
        "rephrase": "rephrase",
        "summary":  "summary",
        "unknown":  "unknown",
    },
)
_workflow.add_edge("rephrase", END)
_workflow.add_edge("summary",  END)
_workflow.add_edge("unknown",  END)

graph = _workflow.compile()


# ============================================================
# Public API
# ============================================================
def run_agent(
    user_input:  str,
    session_id:  str | None = None,
) -> tuple[str, str, str]:
    """
    Run the multi-agent pipeline for a single user input.

    Parameters
    ----------
    user_input  : The raw text from the user.
    session_id  : Optional — pass an existing ID to continue a session.

    Returns
    -------
    (response_text, agent_route, session_id)
      response_text : Text produced by the selected sub-agent.
      agent_route   : "REPHRASE" | "SUMMARY" | "UNKNOWN"
      session_id    : The session ID (new or passed-in).
    """
    if session_id is None:
        session_id = str(uuid.uuid4())

    # ── Persist human turn ──────────────────────────────────
    ltm.save_message(session_id=session_id, role="human", content=user_input)
    stm.push_message(session_id, "human", user_input)
    ltm.upsert_metrics(session_id, increment_messages=1)
    stm.set_session_info(session_id, user_id="local-user")

    # ── Langfuse callback ───────────────────────────────────
    callbacks: list = []
    if settings.langfuse_enabled:
        try:
            from langfuse.callback import CallbackHandler
            handler = CallbackHandler(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
                session_id=session_id,
                user_id="local-user",
                # Tags appear in the Langfuse filter sidebar
                tags=["multi-agent", "langgraph"],
                # Free-form metadata visible on the trace detail page
                metadata={
                    "llm_provider": settings.LLM_PROVIDER,
                    "model":        settings.GROQ_MODEL or settings.GOOGLE_MODEL,
                    "agents":       ["orchestrator", "rephrase_agent", "summary_agent"],
                    "input_length": len(user_input),
                },
            )
            callbacks.append(handler)
        except Exception as exc:
            logger.warning("Langfuse callback setup failed: %s", exc)

    # ── Run the graph ───────────────────────────────────────
    initial_state: AgentState = {
        "messages":    [HumanMessage(content=user_input)],
        "session_id":  session_id,
        "user_input":  user_input,
        "agent_route": "",
        "agent_output": "",
    }

    result = graph.invoke(
        initial_state,
        config={"callbacks": callbacks} if callbacks else {},
    )

    response = result.get("agent_output", "No output generated.")
    route    = result.get("agent_route",  "UNKNOWN")

    # ── Flush Langfuse buffer ───────────────────────────────
    for cb in callbacks:
        try:
            cb.flush()
        except Exception:
            pass

    logger.info(
        "run_agent complete | session=%s | route=%s | output_len=%d",
        session_id, route, len(response),
    )
    return response, route, session_id
