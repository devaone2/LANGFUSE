"""
langchain_compat.py — Compatibility shim for langchain 1.x

Langfuse SDK v2 was written against langchain 0.x which had:
  langchain.callbacks.base.BaseCallbackHandler
  langchain.schema.agent.AgentAction / AgentFinish
  langchain.schema.document.Document

Langchain 1.x moved all of these into langchain_core.* and removed
the old top-level paths. This module injects the old paths back into
sys.modules so that Langfuse SDK v2's imports work unchanged.

Import this module ONCE before anything imports langfuse.callback.
It is safe to import multiple times (uses setdefault, no overwriting).
"""

import sys
import types
import logging

log = logging.getLogger(__name__)


def _inject(old_path: str, obj_map: dict) -> None:
    """Create a fake module at old_path and populate it with obj_map."""
    if old_path in sys.modules:
        return  # already patched or real module exists — don't touch it
    mod = types.ModuleType(old_path)
    for name, obj in obj_map.items():
        setattr(mod, name, obj)
    sys.modules[old_path] = mod


def apply():
    """Apply all shims. Called at import time."""
    try:
        import langchain as _lc
        # Only patch for langchain >= 1.0 (old paths still exist in 0.x)
        major = int(_lc.__version__.split(".")[0])
        if major < 1:
            return
    except Exception:
        return

    try:
        from langchain_core.callbacks.base import BaseCallbackHandler
        _inject("langchain.callbacks.base", {
            "BaseCallbackHandler": BaseCallbackHandler,
        })
    except ImportError as e:
        log.debug("langchain_compat: could not shim callbacks.base: %s", e)

    try:
        from langchain_core.agents import AgentAction, AgentFinish
        _inject("langchain.schema.agent", {
            "AgentAction": AgentAction,
            "AgentFinish": AgentFinish,
        })
    except ImportError as e:
        log.debug("langchain_compat: could not shim schema.agent: %s", e)

    try:
        from langchain_core.documents import Document
        _inject("langchain.schema.document", {"Document": Document})
    except ImportError as e:
        log.debug("langchain_compat: could not shim schema.document: %s", e)


# Apply automatically on import
apply()
