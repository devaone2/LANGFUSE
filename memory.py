"""
memory.py — Unified memory layer for the LangGraph agent

Long-Term Memory (LTM)  → PostgreSQL
  • Persists conversation history across sessions
  • Stores agent-created notes
  • Records per-session metrics (tokens, tool calls, etc.)

Short-Term Memory (STM) → Redis
  • Caches recent messages for the current session (TTL-based)
  • Stores ephemeral agent state (e.g., current plan, last tool result)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import redis
from sqlalchemy import (
    Column, DateTime, Integer, JSON, String, Text, create_engine, text
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import settings

logger = logging.getLogger(__name__)


# ============================================================
# SQLAlchemy Models (PostgreSQL)
# ============================================================

class Base(DeclarativeBase):
    pass


class ConversationHistory(Base):
    """One row per message turn. Stores both user & assistant messages."""
    __tablename__ = "conversation_history"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    session_id  = Column(String(255), nullable=False, index=True)
    role        = Column(String(50),  nullable=False)       # human / assistant / tool
    content     = Column(Text,        nullable=False)
    tool_calls  = Column(JSON,        nullable=True)        # serialised tool call info
    timestamp   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AgentNote(Base):
    """Structured notes saved by the agent via the save_note tool."""
    __tablename__ = "agent_notes"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(255), nullable=False, index=True)
    title      = Column(String(255), nullable=False)
    content    = Column(Text,        nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SessionMetrics(Base):
    """Aggregate metrics per session — updated after each agent run."""
    __tablename__ = "session_metrics"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    session_id        = Column(String(255), nullable=False, unique=True, index=True)
    langfuse_trace_id = Column(String(255), nullable=True)
    total_messages    = Column(Integer, default=0)
    tool_calls_count  = Column(Integer, default=0)
    started_at        = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at        = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                               onupdate=lambda: datetime.now(timezone.utc))


# ============================================================
# Long-Term Memory — PostgreSQL
# ============================================================

class LongTermMemory:
    """
    Persistent memory backed by PostgreSQL.
    Creates tables on first use (no migration needed for dev).
    """

    def __init__(self):
        self.engine = create_engine(
            settings.POSTGRES_URL,
            pool_pre_ping=True,
            echo=False,
        )
        Base.metadata.create_all(self.engine)
        self._Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        logger.info("LTM (PostgreSQL) initialised at %s", settings.POSTGRES_URL)

    # --- Conversation history ---

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[dict] = None,
    ) -> None:
        with self._Session() as db:
            db.add(ConversationHistory(
                session_id=session_id,
                role=role,
                content=content,
                tool_calls=tool_calls,
            ))
            db.commit()

    def get_history(self, session_id: str, limit: int = 50) -> list[ConversationHistory]:
        with self._Session() as db:
            return (
                db.query(ConversationHistory)
                .filter_by(session_id=session_id)
                .order_by(ConversationHistory.timestamp)
                .limit(limit)
                .all()
            )

    # --- Notes ---

    def save_note(self, session_id: str, title: str, content: str) -> int:
        with self._Session() as db:
            note = AgentNote(session_id=session_id, title=title, content=content)
            db.add(note)
            db.commit()
            db.refresh(note)
            return note.id

    def get_notes(self, session_id: str) -> list[AgentNote]:
        with self._Session() as db:
            return (
                db.query(AgentNote)
                .filter_by(session_id=session_id)
                .order_by(AgentNote.created_at)
                .all()
            )

    # --- Session metrics ---

    def upsert_metrics(
        self,
        session_id: str,
        *,
        increment_messages: int = 0,
        increment_tool_calls: int = 0,
        langfuse_trace_id: Optional[str] = None,
    ) -> None:
        with self._Session() as db:
            metrics = db.query(SessionMetrics).filter_by(session_id=session_id).first()
            if metrics is None:
                metrics = SessionMetrics(session_id=session_id)
                db.add(metrics)
            metrics.total_messages   = (metrics.total_messages   or 0) + increment_messages
            metrics.tool_calls_count = (metrics.tool_calls_count or 0) + increment_tool_calls
            metrics.updated_at = datetime.now(timezone.utc)
            if langfuse_trace_id:
                metrics.langfuse_trace_id = langfuse_trace_id
            db.commit()

    def get_metrics(self, session_id: str) -> Optional[SessionMetrics]:
        with self._Session() as db:
            return db.query(SessionMetrics).filter_by(session_id=session_id).first()

    # --- Health check ---

    def ping(self) -> bool:
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True


# ============================================================
# Short-Term Memory — Redis
# ============================================================

class ShortTermMemory:
    """
    Ephemeral session cache backed by Redis.
    All keys include session_id prefix and carry a TTL.
    """

    def __init__(self):
        self.client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            db=settings.REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        logger.info("STM (Redis) initialised at %s:%d", settings.REDIS_HOST, settings.REDIS_PORT)

    # --- Recent message buffer (ring buffer of last 20) ---

    def push_message(self, session_id: str, role: str, content: str) -> None:
        key = f"session:{session_id}:messages"
        entry = json.dumps({"role": role, "content": content,
                            "ts": datetime.now(timezone.utc).isoformat()})
        self.client.lpush(key, entry)
        self.client.ltrim(key, 0, 19)       # keep only latest 20
        self.client.expire(key, settings.SESSION_TTL)

    def get_recent_messages(self, session_id: str) -> list[dict]:
        key = f"session:{session_id}:messages"
        raw = self.client.lrange(key, 0, -1)
        return [json.loads(m) for m in reversed(raw)]  # chronological order

    # --- Arbitrary key-value session context ---

    def set_context(self, session_id: str, key: str, value) -> None:
        rkey = f"session:{session_id}:ctx:{key}"
        self.client.setex(rkey, settings.SESSION_TTL, json.dumps(value))

    def get_context(self, session_id: str, key: str):
        rkey = f"session:{session_id}:ctx:{key}"
        raw = self.client.get(rkey)
        return json.loads(raw) if raw is not None else None

    # --- Session info (stored as hash) ---

    def set_session_info(self, session_id: str, **kwargs) -> None:
        key = f"session:{session_id}:info"
        self.client.hset(key, mapping={k: str(v) for k, v in kwargs.items()})
        self.client.expire(key, settings.SESSION_TTL)

    def get_session_info(self, session_id: str) -> dict:
        key = f"session:{session_id}:info"
        return self.client.hgetall(key)

    # --- Health check ---

    def ping(self) -> bool:
        return self.client.ping()

    # --- Utility ---

    def session_message_count(self, session_id: str) -> int:
        return self.client.llen(f"session:{session_id}:messages")
